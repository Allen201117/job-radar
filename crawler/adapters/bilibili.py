"""哔哩哔哩招聘公开 API 适配器（匿名 CSRF 会话，零浏览器）。"""
import json
import time
from typing import List

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


class BilibiliAdapter(BaseAdapter):
    name = "bilibili"
    company_name = "哔哩哔哩"

    CSRF_URL = "https://jobs.bilibili.com/api/auth/v1/csrf/token"
    LIST_URL = "https://jobs.bilibili.com/api/srs/position/positionList"
    DETAIL_URL = "https://jobs.bilibili.com/social/positions/{job_id}"
    PAGE_SIZE = 50
    MAX_PAGES = 20

    def _base_headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-AppKey": "ops.ehr-api.auth",
            "X-UserType": "2",
            "X-Channel": "social",
            "Lunar-Id": f"lunar-{int(time.time() * 1000)}-job-radar",
        }

    def fetch(self, source_url: str) -> str:
        rows = []
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self._base_headers(),
        ) as client:
            csrf_response = client.get(self.CSRF_URL)
            csrf_response.raise_for_status()
            csrf = str((csrf_response.json() or {}).get("data") or "").strip()
            if not csrf:
                raise RuntimeError("bilibili: anonymous CSRF token unavailable")
            headers = {"X-CSRF": csrf}
            for page_no in range(1, self.MAX_PAGES + 1):
                payload = {
                    "pageSize": self.PAGE_SIZE,
                    "pageNum": page_no,
                    "positionName": "",
                    "postCode": [],
                    "postCodeList": [],
                    "workLocationList": [],
                    "workTypeList": ["3"],
                    "positionTypeList": ["3"],
                    "deptCodeList": [],
                    "recruitType": 0,
                    "practiceTypes": [],
                    "onlyHotRecruit": 0,
                }
                response = client.post(self.LIST_URL, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json() or {}
                if body.get("code") != 0:
                    raise RuntimeError(f"bilibili: list error {body.get('message')}")
                page_rows = (body.get("data") or {}).get("list") or []
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < self.PAGE_SIZE:
                    break
        if not rows:
            raise RuntimeError("bilibili: empty positionList response")
        return json.dumps({"data": {"list": rows}}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = ((json.loads(html) or {}).get("data") or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("positionName") or "").strip()
            location = str(row.get("workLocation") or "").strip()
            if not (job_id and title and is_china_company_location(location)):
                continue
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            pushed = str(row.get("pushTime") or "").strip()
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=(
                    str(row.get("postCodeName") or row.get("positionTypeName") or "").strip()
                    or None
                ),
                summary=str(row.get("positionDescription") or "").strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=pushed[:10] or None,
            ))
        return jobs
