"""顺丰**校园招聘**门户 crs-pub.sf-express.com 适配器（纯 httpx，零登录、零浏览器）。

⚠️ 与 `sf_express.py`（社招）是**两套完全不同的系统**，别混：
    社招 hr.sf-express.com  → POST /SearchJob.do，岗位 id 是 `id,positionType` 二元组
    校招 crs-pub.sf-express.com → GET /api/web/position/query，岗位 id 是单个自增整数
两边的 id 空间不相干，jd_url 模板也不同；共用 adapter 只会互相污染。

## 接口是怎么找到的（2026-09-18 live，猜不出来，记下省得下次重挖）
前端是 Vue2 SPA（hash 路由），列表数据走 XHR：
  · 路由表在 `/cr/static/js/app.<hash>.js`：`path:"/positionList"` / `path:"/postDetail/:id"`
    / `path:"/traineeList"` / `path:"/traineePositionDetail/:id"`。
  · API 前缀在 `/static/js/config.js`：`__APP_ENV__API_BASE_URL__: "/api"`。
  · 真正的接口名在**懒加载分块**里（manifest 的 chunk map → `/cr/static/js/{id}.{hash}.js`），
    主包里搜不到：`web/position/query`（列表）、`web/position/findById/{id}`（详情）、
    `web/position/queryDict/{type}`（字典）。

- 列表：`GET /api/web/position/query?pageSize={n}&pageNum={p}`（PageHelper 风格，零鉴权）
  返回 `{total,pages,pageNum,size,hasNextPage,list:[...]}`。
  ✅ `pageNum` 与 `pageSize` **都真实生效**（live 对拍 page1∩page2 = 0 条、三页并集 = total=120；
     pageSize 10/50/100/200 如实回显，无上限截断）。这一条必须每次接源都验——
     同一晚接的美的就栽在「pageNum 被静默忽略、永远返第 1 页」上（见 midea_campus.py）。
  · `regionIds=` 是服务端地区筛选参数（页面的城市筛选器用），我们要全量故不传。
  · **不要拿 `hasNextPage` 当收尾判据**：走 `paginate_all` 的「自报 total / totalPages」口径，
    短页不判末页（CLAUDE.md「列表抓取上限与短页误判」）。

- 正文：**列表行自带全文**（`postDuty` 岗位职责 + `jobRequirement` 任职要求），
  不需要逐岗详情 → 零薄卡、也不烧 detail 预算。

- 逐岗 jd_url：`https://crs-pub.sf-express.com/#/postDetail/{id}`
  这是**站点自己拼的链接**，不是我们猜的：列表卡片的模板里就是
  `attrs:{href:"#/postDetail/"+a.id, target:"_blank"}`（另一处是
  `$router.push({path:"/postDetail/"+t.item.id})`）。
  ⚠️ hash 路由，`canonicalize_jd_url` 对 `#` 后面原样不碰，符合唯一索引口径。

## 判死信号（给 enrich.ENRICH_REGISTRY 用，证据见 enrich._detail_sf_express_campus）
详情接口 `GET /api/web/position/findById/{id}` 回的 `status` 才是在招开关，**列表行里没有这个字段**。

⚠️ **别想着靠页面文案判死——这个站的详情页不随撤岗消失**（2026-09-18 Playwright 真渲染实测）：
   已撤下的 2100（status=2）与 2267（status=0）照样渲染出完整岗位名 + 正文 + 「申请职位」按钮
   （620 / 846 字），和在招岗**长得一模一样**；只有 id 彻底不存在时才渲染出 312 字的空壳。
   同 CLAUDE.md 里浦发那条边界。两个后果：
     ① 判死只能读接口的 `status`，`audit_dead_links` 那套 DEAD_MARKERS 对这个源一个都匹配不上
        —— 所以它必须走 httpx 的 ENRICH_REGISTRY + liveness-sweep，不能指望浏览器巡检；
     ② 库里一旦留着已撤岗，用户点进去会看到一个「可以投递」的完整页面，
        察觉不到它已经关了 —— 这个源的 sweep 覆盖率比一般源更要紧。

## 诚实边界
- `staffGroup=C`（实习生通道 /traineeList）2026-09-18 实测 `total=0`，当前没有在招实习岗；
  它与主列表是**同一个接口的不同筛选**，等顺丰重开时主列表会带 `internTypeName` 出现，
  parse 已按该字段分流，无需改代码。**「现在返 0」不等于「顺丰没有实习」**（CLAUDE.md 立碑），
  真要下这个结论得去看它的实习生招聘页自己怎么说。
- 另外两个筛选值 `positionType=consulting`（顾问/人才项目）与 `specialCategory=1` 同日实测也是 0。
"""
import json
import logging
from typing import List, Optional

import httpx

import normalizer

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_page_cap

logger = logging.getLogger(__name__)

_HOST = "https://crs-pub.sf-express.com"


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SfExpressCampusAdapter(BaseAdapter):
    name = "sf_express_campus"
    company_name = "顺丰"
    official_hosts = ("crs-pub.sf-express.com",)

    LIST_API = f"{_HOST}/api/web/position/query"
    DETAIL_API = f"{_HOST}/api/web/position/findById/{{job_id}}"
    DETAIL_URL = f"{_HOST}/#/postDetail/{{job_id}}"
    PAGE_SIZE = 50

    def should_skip(self, source_url: str) -> Optional[str]:
        # 站点是 SPA + openresty，HEAD 预检对 `#/positionList` 这种 hash 路由没有意义
        # （服务端永远回同一份 index.html）。走默认实现只会白花一次 5s 超时。
        # 2026-09-18 实测：对 https://crs-pub.sf-express.com/#/positionList 的 HEAD 返 200，
        # 默认实现也不会跳过——这里显式返回 None 是为了让「为什么不预检」有据可查。
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{_HOST}/",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False

        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers()) as client:

            def fetch_page(page_no: int) -> PageResult:
                resp = client.get(self.LIST_API, params={
                    "pageSize": self.PAGE_SIZE,
                    "pageNum": page_no,
                })
                resp.raise_for_status()
                payload = resp.json() or {}
                rows = payload.get("list")
                total = _int_or_none(payload.get("total"))
                # 「HTTP 200 + 结构不对」必须抛错记 failed，不许安静返 0 条 ——
                # 安静返 0 正是「对方没开校招」这类错误结论的来源（CLAUDE.md 立碑）。
                # 注意：`list: []` + `total: 0` 是**合法的空态**（季结束），照常放行。
                if not isinstance(rows, list) or total is None:
                    raise RuntimeError(
                        "sf_express_campus: position/query 结构异常"
                        f"（list={type(rows).__name__} total={payload.get('total')!r}）")
                return PageResult(items=rows, total=total,
                                  total_pages=_int_or_none(payload.get("pages")))

            rows, total, complete = paginate_all(
                fetch_page,
                page_size=self.PAGE_SIZE,
                max_pages=resolve_page_cap(self.PAGE_SIZE),
                delay_seconds=0.2,
                label=self.name,
            )

        # 按 id 去重（同一岗不会在两页里重复出现，但翻页期间上下架会让分页窗口滑动）。
        by_id = {}
        for row in rows:
            job_id = _int_or_none((row or {}).get("id"))
            if job_id is not None:
                by_id[job_id] = row

        self.reported_total = total
        # 抓全 = 翻页没被截断 **且** 去重后条数够自报总数。去重会吃掉滑窗重复，
        # 只看 paginate_all 的 complete 会把「翻页期间掉了几条」说成抓全。
        self.fetch_complete = bool(complete) and (total is None or len(by_id) >= total)
        if not self.fetch_complete:
            logger.info("%s: 未抓全（got=%d reported_total=%s）", self.name, len(by_id), total)
        return json.dumps({"list": list(by_id.values())}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs: List[RawJob] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = _int_or_none(row.get("id"))
            title = str(row.get("positionName") or "").strip()
            if job_id is None or not title:
                continue
            location = str(row.get("demandCity") or "").strip()
            # 后置地区过滤（所有源通用的正确性兜底，CLAUDE.md 核心产品原则#1）。
            # ⚠️ 用原始整串判，不要用 `_first_city` 的结果：「全国」这类整串能过
            # （live 实测 location_in_source_regions("全国", {"CN"}) → True），砍开反而更脆。
            if not _in_source_regions(location, getattr(self, "regions", None)):
                continue
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=_first_city(location) or None,
                job_type=_job_type_of(row),
                summary=_summary_of(row),
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=str(row.get("createDate") or "")[:10] or None,
                education=str(row.get("educationName") or "").strip() or None,
            ))
        return jobs


def _in_source_regions(location: str, regions) -> bool:
    """后置地区过滤，判据跟着 `sources.regions` 走（默认 {CN}）。

    **「只丢能确证在范围外的岗」，不是「不能自证在范围内就丢」** —— 与
    `avature._in_regions` 的 facet 源分支同一套道理：这是单租户的中国区校招门户，
    host 本身就保证了地区，后置过滤只是防漏网，不该反过来当准入门槛。
    `derive_country_code` 认不出的地点返回 None，而 None 既可能是没收录的中国县级市，
    也可能是没收录的外国城市 —— 把 None 当「不在中国」就是丢真岗。

    📊 2026-09-18 live 实测这一条的影响面（顺丰校招 120 行，逐条看过、不是抽样）：
      严格判据丢 1 个 —— id=2328「经营管理岗（经营分析方向）」`demandCity` 是空串；
      放开后 0 个被丢，且**没有任何一行**的 `derive_country_code` 落在 CN 之外
      （全部 120 行的地点取值只有中国地级市名与「全国」）。
    ⚠️ 台湾红线不受影响：`台北市` 能被识别成 TW（code 非 None）→ 仍走严格分支被丢。
    诚实代价：哪天顺丰在这个门户上挂「识别不出国家的外国城市」岗，会漏进来；
    校招门户挂海外岗的概率极低，且真出现时 `sources.regions` 才是该动的旋钮。
    """
    if normalizer.location_in_source_regions(location, regions):
        return True
    return normalizer.derive_country_code(location) is None


def _first_city(location: str) -> str:
    """多城市岗的 `demandCity` 是「成都市,武汉市,深圳市」这种逗号串，取第一个做 location。

    与 lenovo/huawei_campus 同口径：**筛选用第一个城市，全部城市写进 summary**。
    不把整串交给 normalizer 的原因是 `normalize_city` 对逗号串只会挑出其中一个
    （live 实测「上海市,佛山市」→ 上海、「成都市,武汉市,深圳市」→ 深圳，挑哪个取决于
    别名表命中顺序），行为不可预期；取第一个至少是确定的。
    """
    return (location.split(",")[0] or "").strip()


def _job_type_of(row: dict) -> str:
    """三桶分类的信号交给 normalizer，adapter 只如实转述对方自己的标注。

    `internTypeName` 是**岗位级**标注（live 见过 "日常实习"），`seasonType` 是**招聘季级**
    （1=春季校招 / 2=秋季校招 / 3=实习生招聘，由 findById 的 seasonName 对出来的）。
    岗位级优先，都没有才落回「校园招聘」。
    """
    intern = str(row.get("internTypeName") or "").strip()
    if intern:
        return intern
    if str(row.get("seasonType") or "").strip() == "3":
        return "实习"
    return "校园招聘"


def _summary_of(row: dict) -> Optional[str]:
    """summary 段序是**量出来的**，不是随手排的。

    `grad_class`（届别）只看 `clean_summary` 截断后的**前 400 字**，而顺丰的届别硬信号
    （「2027届本科及以上学历毕业生」）写在 `jobRequirement` 的第一句、`postDuty` 里一个字都没有。
    2026-09-18 拿全部 120 行实测：
        【岗位职责】在前 → 118/120 能抽到届别（postDuty 中位数 189 字，长的两行把它挤出 400）
        【任职要求】在前 → 120/120
    差 2 行不大，但届别是校招专区的筛选主键，漏一个就是让人白投一轮，故要求段前置。
    抬头两行（方向 / 用人单位）合计 ~25 字，不影响这个结论。
    """
    parts = []
    head = []
    kind = str(row.get("positionTypeName") or "").strip()
    org = str(row.get("orgSourceName") or "").strip()
    if kind:
        head.append(f"招聘方向：{kind}")
    if org:
        # ⚠️ orgSourceName（顺丰本部/顺丰航空/顺丰科技/顺丰分公司）只进 summary，**不写 company**。
        # 派生子公司 company 的前提是「派生出来的名字仍能被必投清单的 %顺丰% 命中」，
        # 这里虽然满足，但会把一家公司拆成四行统计、且对用户没有任何增量信息。
        head.append(f"用人单位：{org}")
    cities = [c.strip() for c in str(row.get("demandCity") or "").split(",") if c.strip()]
    if len(cities) > 1:
        head.append("工作城市：" + "、".join(cities))
    if head:
        parts.append(" · ".join(head))

    requirement = str(row.get("jobRequirement") or "").strip()
    duty = str(row.get("postDuty") or "").strip()
    other = str(row.get("otherRequirement") or "").strip()
    if requirement:
        parts.append(f"【任职要求】\n{requirement}")
    if duty:
        parts.append(f"【岗位职责】\n{duty}")
    if other:
        parts.append(f"【其他要求】\n{other}")
    return "\n".join(parts).strip() or None
