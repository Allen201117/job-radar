"""交通银行人才招聘门户（job.bankcomm.com）适配器（纯 httpx，零浏览器、零登录）。

⚠️ 这家的列表点一下**像没反应** —— 因为详情是 `window.open("/#/social/recruitmentInfo/?positionId=…")`
打开的（前端 `openNewPageSocial`）。「点着没反应」不等于「没有详情页」，别再据此判它是公告制。
2026-09-05 已在真实浏览器里渲染核实详情页（职位描述+职位要求全文，无需登录）。

接口形状是这家最容易卡住的地方（照抄前端 `jumpRequest`）：
  POST /api/GTMS.GTMS-PORTAL.V-1.0/{op}.do，**form-urlencoded**，只有一个字段 `REQ_MESSAGE`，
  值是 JSON 字符串 `{"REQ_HEAD":{…}, "REQ_BODY":{"params":{业务参数}}}`。
  ⚠️ 业务参数必须再包一层 `params` —— 少这一层会拿到 HTTP 200 + ERROR_CODE=JUMPTESTBP9001
  「系统异常」，很容易被误读成「接口要登录/被拒了」。成败一律看 RSP_HEAD.TRAN_SUCCESS。

engageType：1=校园招聘 / 3=社会招聘（同一个 querySocietyRecruitInfo.do，靠这个字段分渠道）。
2026-09-05 实测校招 0 条 —— 与站点校招页自己写的「暂无职位数据」一致，不是我们抓漏了。
"""
import json
import re
from datetime import date
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap, resolve_page_cap
from .cn_portal_tls import make_transport


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"[ \t　]+", " ", str(value or "")).strip()


class BankcommAdapter(BaseAdapter):
    name = "bankcomm"

    API_BASE = "https://job.bankcomm.com/api/GTMS.GTMS-PORTAL.V-1.0/"
    REFERER = "https://job.bankcomm.com/"
    # hash 路由 → canonical 归一原样保留（规则 2）。engageType 决定 social / school 前缀。
    DETAIL_URL = "https://job.bankcomm.com/#/{section}/recruitmentInfo/?positionId={position_id}"
    PAGE_SIZE = 100
    _DETAIL_CAP = 300

    _CHANNELS = ((3, "社招", "social"), (1, "校招", "school"))

    def _call(self, client: httpx.Client, op: str, params: dict) -> dict:
        message = {
            "REQ_HEAD": {"TRAN_PROCESS": "", "TRAN_ID": "", "ACCESS_TOKEN": "", "REFRESH_TOKEN": ""},
            "REQ_BODY": {"unnessaryLogin": True, "params": params},
        }
        response = client.post(f"{self.API_BASE}{op}.do",
                               data={"REQ_MESSAGE": json.dumps(message, ensure_ascii=False)})
        response.raise_for_status()
        payload = response.json() or {}
        head = payload.get("RSP_HEAD") or {}
        if str(head.get("TRAN_SUCCESS")) != "1":
            raise RuntimeError(f"bankcomm: {op} TRAN_SUCCESS={head.get('TRAN_SUCCESS')} "
                               f"code={head.get('ERROR_CODE')} msg={head.get('ERROR_MESSAGE')}")
        return payload.get("RSP_BODY") or {}

    @staticmethod
    def _is_open(row: dict, today: str) -> bool:
        end = _clean(row.get("endDate"))
        return (not end) or end[:10] >= today

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.REFERER,
        }
        today = date.today().isoformat()
        rows: List[dict] = []
        total_sum = 0
        all_complete = True
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers,
                          transport=make_transport()) as client:
            for engage_type, job_type, section in self._CHANNELS:
                def fetch_page(page: int, et=engage_type) -> PageResult:
                    body = self._call(client, "querySocietyRecruitInfo", {
                        "businessPara": {"workPlace": "", "pubName": "", "positionId": "",
                                         "engageType": et},
                        "pagePara": {"pageNum": page, "pageSize": self.PAGE_SIZE},
                    })
                    results = body.get("results") or {}
                    return PageResult(items=results.get("policyList") or [],
                                      total=_int_or_none(results.get("total")))

                channel_rows, channel_total, complete = paginate_all(
                    fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                    max_pages=resolve_page_cap(self.PAGE_SIZE), label=f"bankcomm:{engage_type}",
                )
                total_sum += channel_total or 0
                all_complete = all_complete and complete
                for row in channel_rows:
                    if isinstance(row, dict):
                        row["_job_type"] = job_type
                        row["_section"] = section
                        rows.append(row)

            # ⚠️ 过期过滤必须在这里做、不能在上面边聚合边做：招聘窗口刚结束那几天所有岗都过期，
            # 那样 rows 会是空的 → 下面 `if not rows` 抛 RuntimeError → 源被记 failed 并触发告警，
            # 可接口其实工作得好好的。「没有在招岗」是正常状态，不是故障。
            open_rows = [r for r in rows if self._is_open(r, today)]
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in open_rows[:cap] if cap else []:
                position_id = row.get("positionId")
                if position_id in (None, ""):
                    continue
                try:
                    body = self._call(client, "queryPositionDetail", {"positionId": position_id})
                    detail = body.get("results")
                    if isinstance(detail, dict):
                        row["_detail"] = detail
                except (httpx.HTTPError, RuntimeError, json.JSONDecodeError):
                    continue
        if not rows:
            raise RuntimeError("bankcomm: querySocietyRecruitInfo returned no jobs")
        # 分母用「还能投的岗数」而不是接口自报总数：过期岗是我们主动丢的，
        # 拿含过期岗的总数当分母会让抓全率上永远挂着一个假缺口。
        self.reported_total = len(open_rows)
        self.fetch_complete = all_complete
        return json.dumps({"jobs": open_rows}, ensure_ascii=False)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        detail = row.get("_detail") or {}
        responsibility = _clean(detail.get("responsibility"))
        require = _clean(detail.get("require"))
        parts = []
        if responsibility:
            parts.append(f"【职位描述】\n{responsibility}")
        if require:
            parts.append(f"【职位要求】\n{require}")
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
            position_id = _clean(row.get("positionId"))
            title = _clean(row.get("pubName"))
            if not (position_id and title):
                continue
            jd_url = self.DETAIL_URL.format(
                section=_clean(row.get("_section")) or "social", position_id=position_id)
            jobs.append(RawJob(
                company="", title=title,
                # workPlace 形如「天津-辖区」/「江苏-无锡」；「辖区」不是地名，退回省市。
                location=_clean(row.get("workPlace")).replace("-辖区", "") or None,
                job_type=_clean(row.get("_job_type")) or None,
                summary=self._summary_of(row), jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("createTime"))[:10] or None,
                deadline=_clean(row.get("endDate"))[:10] or None,
            ))
        return jobs
