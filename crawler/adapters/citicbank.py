"""中信银行招聘官网（job.citicbank.com）自建门户适配器（纯 httpx、零鉴权）。

2026-09-23 live 核实：
  1. 列表接口 POST /recruitportal/portal/recruitQuery（JSON body），零鉴权。
     `recruitmentType` 01=社招 / 02=校招 / 03=其他（当日 0 条）；每页固定 15 条，
     返回体顶层 `pageCount` 实为**总条数**不是总页数（社招 751 = 51 页 × 15 余 1，已逐页翻到底对上）。
  2. 两个渠道的岗位 ID 互不重叠（1004/1004 唯一），一条源只抓一个渠道，渠道由 source_url 决定：
     URL 带 campus → 02，否则 01（这样 sources.board 生成列才能把校招那条判成 campus）。
  3. 逐岗详情 GET /static/positionDetail_{ID}_{type}.html 是服务端渲染的静态页，正文（岗位职责 +
     任职资格）直接在 HTML 里；不存在的 ID 返回 **HTTP 404**「系统错误，请联系管理员」——现成的撤岗信号。
  4. 岗位覆盖总行各部门 + 全部分行（行内 CONTENT 字段 = 招聘机构，如「济南分行」），
     全部归中信银行；机构名拼进标题，否则几十个分行的「客户经理类」在看板上无从区分。

⚠️ 必投缺口台账此前把中信银行的入口记成 careers.citics.com —— 那是**中信证券**（另一家公司），
   另一条「中信银行信用卡中心」wecruit 源的租户也已不存在（官网不存在 → 每轮 skipped）。
"""
import json
import re
from typing import List, Optional

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap
from .cn_portal_tls import make_transport


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class CiticbankAdapter(BaseAdapter):
    name = "citicbank"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )

    LIST_API = "https://job.citicbank.com/recruitportal/portal/recruitQuery"
    LIST_REFERER = "https://job.citicbank.com/CustStyle/zpmhys/clubRecruit.html"
    DETAIL_URL = "https://job.citicbank.com/static/positionDetail_{job_id}_{type_code}.html"
    PAGE_SIZE = 15          # 服务端固定 15 条/页（2026-09-23 live）
    MAX_PAGES = 200
    # 正文只在详情页。本机实测约 0.1s/次，1004 个岗全量补约 2 分钟 → 覆盖全源；
    # 快档 daily 由 CRAWL_DETAIL_CAP=0 跳过（resolve_detail_cap），只抓列表骨架。
    _DETAIL_CAP = 1200

    # 详情页正文从这几个小节标题之一开始，到分享弹层 / 投递确认弹层之前结束（站点模板固定文案）。
    _BODY_STARTS = ("岗位职责", "工作职责", "职位描述", "岗位描述", "职位职责")
    _BODY_ENDS = ("请扫描二维码", "您暂时还没有简历", "您即将投递")

    @staticmethod
    def _type_code(source_url: str) -> str:
        return "02" if re.search(r"campus", source_url or "", re.I) else "01"

    @classmethod
    def _detail_body(cls, html: str) -> str:
        tree = HTMLParser(html or "")
        for node in tree.css("script,style,noscript"):
            node.decompose()
        text = re.sub(r"\s+", " ", tree.body.text() if tree.body else "")
        starts = [i for i in (text.find(k) for k in cls._BODY_STARTS) if i >= 0]
        if not starts:
            return ""
        start = min(starts)
        ends = [i for i in (text.find(k, start) for k in cls._BODY_ENDS) if i > start]
        end = min(ends) if ends else len(text)
        return text[start:end].rstrip(" ×").strip()

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        type_code = self._type_code(source_url)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
            "Referer": self.LIST_REFERER,
            "Origin": "https://job.citicbank.com",
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers,
                          transport=make_transport()) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, json={
                    "RELEASENAME": "", "recruitmentType": type_code,
                    "workAddr": [], "deptCode": [], "page": page, "userId": None,
                })
                response.raise_for_status()
                payload = response.json() or {}
                if payload.get("IsSuc") is False:
                    raise RuntimeError("citicbank: recruitQuery IsSuc=false: %s" % payload.get("Msg"))
                table = payload.get("tableData") or {}
                rows = table.get("rows") if isinstance(table, dict) else None
                if not isinstance(rows, list):
                    raise RuntimeError("citicbank: recruitQuery tableData.rows is not a list")
                items = [r.get("itemMap") for r in rows if isinstance(r, dict) and isinstance(r.get("itemMap"), dict)]
                # pageCount 是总条数（见模块 docstring），不是总页数。
                return PageResult(items=items, total=_int_or_none(payload.get("pageCount")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="citicbank",
            )
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                job_id = str((row or {}).get("ID") or "").strip()
                if not job_id:
                    continue
                try:
                    response = client.get(self.DETAIL_URL.format(job_id=job_id, type_code=type_code))
                    response.raise_for_status()
                    row["_detail_body"] = self._detail_body(response.text)
                except httpx.HTTPError:
                    continue
        # 校招渠道在批次之间可以真的是 0 条（接口正常应答、total=0），那不是故障。
        if not rows and total != 0:
            raise RuntimeError("citicbank: recruitQuery returned no jobs (recruitmentType=%s)" % type_code)
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"type_code": type_code, "jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            data = json.loads(payload) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        type_code = str(data.get("type_code") or "01")
        jobs = []
        for row in data.get("jobs") or []:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("ID") or "").strip()
            post = _clean(row.get("POSTNAME") or row.get("RELEASENAME"))
            if not (job_id and post):
                continue
            org = _clean(row.get("CONTENT"))
            title = "%s（%s）" % (post, org) if org and org not in post else post
            jd_url = self.DETAIL_URL.format(job_id=job_id, type_code=type_code)
            jobs.append(RawJob(
                company="", title=title,
                location=_clean(row.get("WORKADDR")) or None,
                job_type="校招" if type_code == "02" else "社招",
                summary=_clean(row.get("_detail_body")) or None,
                jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("FBZWDATE")) or None,
            ))
        return jobs
