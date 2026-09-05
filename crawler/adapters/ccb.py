"""中国建设银行招聘门户（job3.ccb.com）适配器（纯 httpx，零浏览器、零登录）。

⚠️ 这家也曾被误判成「公告制、没有逐岗详情页」。真相：`job_list.html` 就是逐岗列表，
每条点开是 `job_detail.html?planId=…&planPost=…&planType=…&orgId=…&secondOrgId=…`，
2026-09-05 已在真实浏览器里渲染核实（岗位职责+岗位要求全文都在，无需登录）。

三个坑（都 live 实测过）：
  1. **详情接口要先「热身」一次会话**：直接打 NHR107 会返回 SUCCESS=false /「请重新登录」，
     哪怕先 GET 过详情页也一样。先请求一次 `TXCODE=100119`（站点自己在每个页面都会打）
     拿到 JSESSIONID 之后，同一个 client 再打 NHR107 就通了。这不是用户登录态。
  2. **详情 URL 少一个参数就打不开**：前端 `getRequireParam('planId,planPost,orgId,secondOrgId')`
     缺任一个就 alert「缺少必要参数」并 history.go(-1)。所以 jd_url 必须是五参数全的那种，
     只带 planId/planPost/planType 的三参数形态是打不开的。
  3. **响应不是合法 JSON**：正文字段里带真实换行/制表符（前端有个 repairJSON 正则在兜），
     本适配器用 `_repair_json` 复刻同一套修补，别直接 json.loads。

  4. **本项目的 Bot UA 会拿到 HTTP 200 + 空 body**（不是 403、不是 HTML 错误页，就是零字节），
     而对根页面 HEAD 又是 200 —— `BaseAdapter.should_skip` 拦不住，结果是「静默抓到 0 条」。
     所以必须覆写 `user_agent`；并且空 body 一律当失败抛，不许安静返 0 条。

planType：XY=校园招聘 / SH=社会招聘 / SX=实习生招聘（站点 PlanTypeData 原值）。
planStatus：1=立即报名 / 2=报名结束 —— 2 的不入库。
"""
import json
import re
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap, resolve_page_cap
from .cn_portal_tls import make_transport


_BASE = "https://job3.ccb.com/tran/WCCMainPlatV5"
_COMMON = {"CCB_IBSVersion": "V5", "isAjaxRequest": "true", "SERVLET_NAME": "WCCMainPlatV5"}

# 复刻前端 job_public.js 的 repairJSON：把 "key":"value" 里 value 内部的裸换行/制表/引号转义掉。
_JSON_FIELD_RE = re.compile(r'("\w+")(\s*:\s*")((?:[^"]|"(?!\s*(?:,\s*"|})))+)(")')


def _repair_json(text: str) -> dict:
    text = text.strip()
    if not text:
        # 见模块 docstring 坑 4：空 body 是「被 UA 挡了」，不是「没有岗位」。
        raise RuntimeError("ccb: empty response body (是不是 UA 被挡了？)")

    def fix(match):
        value = (match.group(3).replace("\\", "\\\\").replace("\r\n", "\\n")
                 .replace("\n", "\\n").replace("\r", "\\n").replace("\t", "\\t")
                 .replace('"', '\\"'))
        return match.group(1) + match.group(2).replace(" ", "") + value + match.group(4)
    return json.loads(_JSON_FIELD_RE.sub(fix, text))


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"[ \t\u3000]+", " ", str(value or "")).strip()


class CcbAdapter(BaseAdapter):
    name = "ccb"
    # 见模块 docstring 坑 4：默认的 JobRadarBot UA 会换来 HTTP 200 + 空 body。
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )

    WARMUP_TXCODE = "100119"
    LIST_TXCODE = "NHR104"      # url_map["职务信息列表"]
    DETAIL_TXCODE = "NHR107"    # url_map["招聘岗位详情"]
    DETAIL_URL = ("https://job3.ccb.com/cn/job/job_detail.html"
                  "?planId={planId}&planPost={planPost}&planType={planType}"
                  "&orgId={orgId}&secondOrgId={secondOrgId}")
    PAGE_SIZE = 200
    _DETAIL_CAP = 400

    _CHANNELS = (("XY", "校招"), ("SH", "社招"), ("SX", "实习"))

    def _get(self, client: httpx.Client, txcode: str, **params) -> httpx.Response:
        response = client.get(_BASE, params={**_COMMON, "TXCODE": txcode, **params})
        response.raise_for_status()
        return response

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://job3.ccb.com/cn/job/job_list.html",
        }
        rows: List[dict] = []
        total_sum = 0
        all_complete = True
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers,
                          transport=make_transport()) as client:
            self._get(client, self.WARMUP_TXCODE)   # 见模块 docstring 坑 1：不热身详情接口必失败

            for plan_type, job_type in self._CHANNELS:
                def fetch_page(page: int, pt=plan_type) -> PageResult:
                    response = self._get(client, self.LIST_TXCODE, planType=pt,
                                         PAGE_JUMP=page, REC_IN_PAGE=self.PAGE_SIZE)
                    payload = _repair_json(response.text)
                    if payload.get("SUCCESS") == "false":
                        raise RuntimeError(f"ccb: NHR104 planType={pt} SUCCESS=false "
                                           f"{payload.get('ERRORMSG')}")
                    return PageResult(items=payload.get("planPostList") or [],
                                      total=_int_or_none(payload.get("TOTAL_REC")))

                channel_rows, channel_total, complete = paginate_all(
                    fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                    max_pages=resolve_page_cap(self.PAGE_SIZE), label=f"ccb:{plan_type}",
                )
                total_sum += channel_total or 0
                all_complete = all_complete and complete
                for row in channel_rows:
                    if isinstance(row, dict) and str(row.get("planStatus") or "") != "2":
                        row["_job_type"] = job_type
                        rows.append(row)

            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                try:
                    response = self._get(
                        client, self.DETAIL_TXCODE,
                        planId=_clean(row.get("planId")), planPost=_clean(row.get("planPost")),
                        planType=_clean(row.get("planType")),
                        # 详情接口的 orgId 传的是**二级机构 id**（前端 job_detail.js 就是这么传的）
                        orgId=_clean(row.get("secondOrgId")),
                    )
                    detail = _repair_json(response.text)
                    if detail.get("SUCCESS") != "false":
                        row["_detail"] = detail
                except (httpx.HTTPError, json.JSONDecodeError):
                    continue
        if not rows:
            raise RuntimeError("ccb: NHR104 returned no jobs")
        self.reported_total = total_sum or None
        self.fetch_complete = all_complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        detail = row.get("_detail") or {}
        duties = _clean(detail.get("postDesc"))
        requirement = _clean(detail.get("PostRequest"))
        parts = []
        if duties:
            parts.append(f"【岗位职责】\n{duties}")
        if requirement:
            parts.append(f"【岗位要求】\n{requirement}")
        return "\n".join(parts) or None

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            plan_id = _clean(row.get("planId"))
            plan_post = _clean(row.get("planPost"))
            title = _clean(row.get("planPostName"))
            if not (plan_id and plan_post and title):
                continue
            jd_url = self.DETAIL_URL.format(
                planId=plan_id, planPost=plan_post, planType=_clean(row.get("planType")),
                orgId=_clean(row.get("orgId")), secondOrgId=_clean(row.get("secondOrgId")))
            jobs.append(RawJob(
                company="", title=title,
                location=_clean(row.get("workPlace")) or None,
                job_type=_clean(row.get("_job_type")) or None,
                summary=self._summary_of(row), jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("postDate"))[:10] or None,
                deadline=_clean(row.get("endDate"))[:10] or None,
            ))
        return jobs
