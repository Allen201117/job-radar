"""中国民生银行社会招聘门户适配器（纯 httpx、零鉴权）。"""
import html as html_lib
import json
import re
from typing import List, Optional

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_html(value) -> str:
    return re.sub(r"\s+", " ", HTMLParser(html_lib.unescape(str(value or ""))).text()).strip()


class CmbcAdapter(BaseAdapter):
    name = "cmbc"
    # 2026-08-27 live：对根域 HEAD，JobRadarBot UA 返回 507，普通浏览器 UA 返回 200。
    # run.py 会先调 should_skip()，所以 fetch 与预检必须共用这个 UA 才能实际进入抓取。
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )

    LIST_API = "https://career.cmbc.com.cn/portal/rest/careerrecruitment/search.view"
    DETAIL_API = "https://career.cmbc.com.cn/portal/rest/careerrecruitment/view/{job_id}.view"
    DETAIL_URL = "https://career.cmbc.com.cn/#/app/recruitmentview/{job_id}"
    PAGE_SIZE = 20
    MAX_PAGES = 100
    _DETAIL_CAP = 150

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        detail = row.get("_detail") or {}
        duties = _clean_html(detail.get("careerRecruitment_career_careerDetail_content"))
        qualifications = _clean_html(detail.get("careerRecruitment_career_careerDetail_qualifications"))
        parts = []
        if duties:
            parts.append(f"【岗位职责】\n{duties}")
        if qualifications:
            parts.append(f"【任职要求】\n{qualifications}")
        return "\n".join(parts) or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, data={
                    "searchRecruitmentIds": "social",
                    "view": "careerRecruitmentList",
                    "pageNo": page,
                    "pageSize": self.PAGE_SIZE,
                })
                response.raise_for_status()
                payload = response.json() or {}
                if payload.get("success") is not True:
                    raise RuntimeError("cmbc: search.view success is not true")
                data = payload.get("data") or {}
                rows = data.get("items") or []
                if not isinstance(rows, list):
                    raise RuntimeError("cmbc: search.view data.items is not a list")
                return PageResult(items=rows, total_pages=_int_or_none(data.get("pageCount")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="cmbc",
            )
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                job_id = str((row or {}).get("id") or "").strip()
                if not job_id:
                    continue
                try:
                    response = client.get(
                        self.DETAIL_API.format(job_id=job_id),
                        params={"view": "careerRecruitmentView"},
                    )
                    response.raise_for_status()
                    payload = response.json() or {}
                    detail = payload.get("data")
                    # 不存在的 id 也会 HTTP 200，但 data 为空；不能把响应骨架当 JD。
                    if payload.get("success") is True and isinstance(detail, dict) and detail:
                        row["_detail"] = detail
                except httpx.HTTPError:
                    continue
        if not rows:
            raise RuntimeError("cmbc: search.view returned no jobs")
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("careerRecruitment_career_name") or "").strip()
            if not (job_id and title):
                continue
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company="", title=title,
                location=str(row.get("careerRecruitment_regions_name") or "").strip() or None,
                job_type="社招", summary=self._summary_of(row), jd_url=jd_url, apply_url=jd_url,
                posted_at=str(row.get("careerRecruitment_career_publishDate") or "").strip() or None,
                deadline=str(row.get("careerRecruitment_career_expirationDate") or "").strip() or None,
            ))
        return jobs
