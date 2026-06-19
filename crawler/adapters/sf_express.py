"""顺丰官方社会招聘公开接口适配器（零登录、零浏览器）。"""
import json
import time
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _page_numbers(total_pages: int, max_pages: int) -> List[int]:
    """Return one-based pages bounded by a defensive hard cap."""
    last_page = min(max(1, total_pages), max(1, max_pages))
    return list(range(1, last_page + 1))


class SfExpressAdapter(BaseAdapter):
    name = "sf_express"
    company_name = "顺丰"

    API_URL = "https://hr.sf-express.com/SearchJob.do"
    DETAIL_URL = "https://hr.sf-express.com/JobSearchById/{job_id},{position_type}"
    MAX_PAGES = 50
    PAGE_RETRIES = 4
    PAGE_RETRY_DELAY = 0.75

    def should_skip(self, source_url: str) -> Optional[str]:
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://hr.sf-express.com/jobMainHandler/main/9999",
            "Origin": "https://hr.sf-express.com",
        }

    @staticmethod
    def _payload(page_number: int) -> dict:
        return {
            "workAddress": "",
            "currentPage": page_number,
            "outName": "",
            "category": "",
            "identification": "",
        }

    def _fetch_page(
        self,
        client: httpx.Client,
        page_number: int,
        expected_rows: Optional[int] = None,
    ) -> dict:
        last_count = None
        for attempt in range(self.PAGE_RETRIES):
            response = client.post(self.API_URL, json=self._payload(page_number))
            response.raise_for_status()
            data = (response.json() or {}).get("JobSearchList") or {}
            rows = data.get("listObj")
            if isinstance(rows, list):
                last_count = len(rows)
                if expected_rows is None or last_count >= expected_rows:
                    return data
            if attempt + 1 < self.PAGE_RETRIES:
                time.sleep(
                    self.PAGE_RETRY_DELAY * (attempt + 1)
                    + (page_number % 3) * 0.1
                )
        raise RuntimeError(
            f"sf_express: invalid SearchJob page {page_number}; "
            f"expected {expected_rows}, got {last_count}"
        )

    def fetch(self, source_url: str) -> str:
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            first_page = self._fetch_page(client, 1)
            total_pages = int(first_page.get("totalPage") or 1)
            total_result = int(first_page.get("totalResult") or 0)
            page_size = int(first_page.get("showCount") or len(first_page.get("listObj") or []))
            pages = _page_numbers(total_pages, self.MAX_PAGES)
            rows = list(first_page.get("listObj") or [])

            remaining = pages[1:]
            for page_number in remaining:
                expected_rows = page_size
                if total_result:
                    expected_rows = min(
                        page_size,
                        max(0, total_result - (page_number - 1) * page_size),
                    )
                page_data = self._fetch_page(
                    client,
                    page_number,
                    expected_rows=expected_rows,
                )
                rows.extend(page_data.get("listObj") or [])

        rows_by_key = {}
        for row in rows:
            key = (
                str((row or {}).get("id") or "").strip(),
                str((row or {}).get("positionType") or "").strip(),
            )
            if all(key):
                rows_by_key[key] = row
        if not rows_by_key:
            raise RuntimeError("sf_express: empty SearchJob response")
        return json.dumps({"jobs": list(rows_by_key.values())}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            position_type = str(row.get("positionType") or "").strip()
            title = str(row.get("outName") or "").strip()
            location = str(row.get("workAddress") or "").strip()
            if not (
                job_id
                and position_type
                and title
                and is_china_company_location(location)
            ):
                continue

            duty = str(row.get("mainDuty") or "").strip()
            requirement = str(row.get("positionReq") or "").strip()
            summary = (
                duty + ("\n\n【岗位要求】\n" + requirement if requirement else "")
            ).strip() or None
            jd_url = self.DETAIL_URL.format(
                job_id=job_id,
                position_type=position_type,
            )
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type="社会招聘",
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                salary_text=(
                    str(row.get("salaryRangeTxt") or "").strip() or None
                ),
                posted_at=(
                    str(row.get("publishTime") or "")[:10] or None
                ),
                experience=(
                    str(row.get("workYearTxt") or "").strip() or None
                ),
                education=(
                    str(row.get("educationReqTxt") or "").strip() or None
                ),
            ))
        return jobs
