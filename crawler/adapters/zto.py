"""中通快递自建招聘门户 hr.zto.com 适配器（纯 httpx，零登录、零浏览器）。

⚠️ 为什么这个源以前是缺的：缺口台账把中通记成 `no_stable_jd`（「没有稳定逐岗链接」）。
   **这个判断是错的**，和六大行是同一类错误——只看了官网首页（校招页确实只有「蓝天计划」
   项目介绍 + 宣讲会 + 一个投递按钮，没有岗位列表），就断定整家公司没有一岗一页。
   实际上社招/校招在 /social 与 /campus-position 下有完整的逐岗列表，且有可冷加载的详情页：
       https://hr.zto.com/position-detail?id={id}
   2026-09-05 实测：新开标签页直接打开该 URL，渲染出完整「职位描述 / 任职资格 / 工作地点」，
   免登录，标题与列表一致。

接口是怎么找到的（猜不出来，记下省得下次重挖）：
  · 前端是 Vue3 SPA，列表数据走 XHR，**浏览器 network 面板抓不到**（只记到静态资源）。
  · 路由表在 js/app.*.js 里：`path:"/position-detail", name:"PositionDetail"`。
  · 接口路径在同一份 bundle：`getPostInfoPageList` / `getPostInfoDetail`。
  · **API 域名不在 hr.zto.com 上**——打 hr.zto.com 任何 POST 都回 405（静态服务器）。
    真正的网关写在 webpack 模块 "759a" 里：PROD.HostName = https://recruiting.gw.zt-express.com

postType 取值（实测 2026-09-05）：1=社招 79 岗、2=校招 22 岗、3=一线招聘 201 岗。
🚫 **刻意不抓 postType=3（一线招聘）**，两条理由缺一不可：
   ① 隐私：该档返回体里 `contactUserName` / `contactUserPhone` / `contactUserLandline`
      带**真实 HR 姓名与手机号**（社招/校招档这三个字段是 null）。不入库、不传播。
   ② 相关性：内容是挂车驾驶员 / 装卸工 / 分拣员，与本产品目标用户（科技/消费求职者）无关，
      201 条会直接淹掉 101 条有效岗（见 CLAUDE.md「精准 > 规模」）。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


class ZtoAdapter(BaseAdapter):
    name = "zto"
    company_name = "中通快递"

    API_BASE = "https://recruiting.gw.zt-express.com"
    LIST_PATH = "/website/post/getPostInfoPageList"
    DETAIL_PATH = "/website/post/getPostInfoDetail"
    # 前端逐岗详情页；冷加载可渲染，作为 jd_url 写库。
    DETAIL_URL = "https://hr.zto.com/position-detail?id={job_id}"

    PAGE_SIZE = 50          # 实测接口接受 50，且 pageSize 原样回显
    POST_TYPE = 1           # 1=社招；子类覆盖为 2=校招。3=一线，见模块注释，不抓。
    _DETAIL_CAP = 500       # 两档合计约 101 岗，500 足够覆盖全量

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://hr.zto.com",
            "Referer": "https://hr.zto.com/",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False

        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:

            def fetch_page(page_no: int) -> PageResult:
                response = client.post(
                    self.API_BASE + self.LIST_PATH,
                    json={"postType": self.POST_TYPE, "pageNum": page_no, "pageSize": self.PAGE_SIZE},
                )
                response.raise_for_status()
                result = (response.json() or {}).get("result") or {}
                return PageResult(
                    items=list(result.get("list") or []),
                    total=result.get("total"),
                    total_pages=result.get("pages"),
                )

            rows, total, complete = paginate_all(
                fetch_page,
                page_size=self.PAGE_SIZE,
                max_pages=60,
                delay_seconds=0.2,
                label=f"{self.name}(postType={self.POST_TYPE})",
            )
            self.reported_total = total
            self.fetch_complete = complete

            # 列表不带正文（qualification 恒为 null），正文只在详情接口里 → 逐岗补。
            # 快档 daily 可用 env CRAWL_DETAIL_CAP=0 跳过，此时岗位仍入库、只是没正文（薄卡）。
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap]:
                job_id = row.get("id")
                if job_id is None:
                    continue
                try:
                    detail = client.post(self.API_BASE + self.DETAIL_PATH, json={"id": job_id})
                    detail.raise_for_status()
                    payload = (detail.json() or {}).get("result") or {}
                except Exception:
                    # 单个岗位补正文失败不该炸穿整源（沿用 gllue/顺丰的教训：
                    # 「一页/一条拿不到就 raise」会把整源几千个在招岗一起扔掉）。
                    continue
                row["duties"] = payload.get("duties")
                row["qualification"] = payload.get("qualification")

        return json.dumps(rows, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        rows = json.loads(html or "[]")
        jobs: List[RawJob] = []
        for row in rows:
            job_id = row.get("id")
            title = (row.get("postNameOut") or "").strip()
            if job_id is None or not title:
                continue
            jobs.append(
                RawJob(
                    company=self._company_of(row),
                    title=title,
                    location=(row.get("workPlaceNameStr") or "").strip() or None,
                    summary=self._summary_of(row),
                    jd_url=self.DETAIL_URL.format(job_id=job_id),
                    experience=(row.get("requireAgeName") or "").strip() or None,
                    education=(row.get("educationName") or "").strip() or None,
                )
            )
        return jobs

    def _company_of(self, row: dict) -> str:
        """按 deptNameStr 的品牌前缀区分中通系子品牌（官网列表页就是这么显示的）。

        ⚠️ 只在前缀确实以「中通」开头时才采用，否则回落到源公司名——
        必投清单用 `%中通%` 匹配，前缀跑掉会让这些岗从「中通」的覆盖统计里掉出去
        （同 CLAUDE.md 里京东/网易派生子公司那条：只映**清单里仍能匹配**的名字）。
        """
        dept = (row.get("deptNameStr") or "").strip()
        brand = dept.split("-", 1)[0].strip()
        if brand.startswith("中通"):
            return brand
        return self.company_name

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        parts = [(row.get("duties") or "").strip(), (row.get("qualification") or "").strip()]
        text = "\n".join(p for p in parts if p)
        return text or None


class ZtoCampusAdapter(ZtoAdapter):
    """中通校招（postType=2）。

    与社招是两个独立源：board 判定靠 source_url 里的 `campus` 令牌
    （classify_source_board 规则④），故校招源必须用 /campus-position 这个路径。
    """

    name = "zto_campus"
    POST_TYPE = 2
