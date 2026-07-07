"""vivo 社会招聘公开 API 适配器（零登录、零浏览器）。"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class VivoAdapter(BaseAdapter):
    name = "vivo"
    company_name = "vivo"

    LIST_URL = "https://hr.vivo.com/api/social/webSite/portal/page"
    DETAIL_URL = (
        "https://hr.vivo.com/job-detail?_irjc={category_id}"
        "&_irjid={job_id}&_collect=false"
    )
    PAGE_SIZE = 100
    MAX_PAGES = 20

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://hr.vivo.com/jobs",
            "Origin": "https://hr.vivo.com",
        }
        rows = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, self.MAX_PAGES + 1):
                payload = {
                    "city_code_list": [],
                    "company_id": 1,
                    "group_id": 1,
                    "user_id": None,
                    "job_category_id_list": [],
                    "keyword": "",
                    "max_results": self.PAGE_SIZE,
                    "page": page_no,
                    "yoe_list": [],
                    "loading": page_no == 1,
                }
                response = client.post(self.LIST_URL, json=payload)
                response.raise_for_status()
                body = response.json() or {}
                if body.get("code") != 0:
                    raise RuntimeError(f"vivo: list error {body.get('message')}")
                if self.reported_total is None:
                    total = _int_or_none(body.get("total"))
                    if total is None:
                        total = _int_or_none(body.get("totalCount"))
                    if total is None:
                        total = _int_or_none(body.get("count"))
                    data_for_total = body.get("data")
                    if total is None and isinstance(data_for_total, dict):
                        total = _int_or_none(data_for_total.get("total"))
                        if total is None:
                            total = _int_or_none(data_for_total.get("count"))
                    if total is not None:
                        self.reported_total = total
                page_rows = body.get("data") or []
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < self.PAGE_SIZE:
                    break
        if not rows:
            raise RuntimeError("vivo: empty portal/page response")
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"data": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("data") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            job_id = str(row.get("job_id") or "").strip()
            category_id = str(row.get("job_category_id") or "").strip()
            title = str(row.get("job_title") or "").strip()
            code = str(row.get("job_code") or "").strip()
            locations = [
                str(item.get("city") or "").strip()
                for item in (row.get("job_location_list") or [])
                if isinstance(item, dict)
                and is_china_company_location(str(item.get("city") or ""))
            ]
            if not (job_id and category_id and title and locations):
                continue
            jd_url = self.DETAIL_URL.format(category_id=category_id, job_id=job_id)
            display_title = f"{title}（{code}）" if code else title
            jobs.append(RawJob(
                company=self.company_name,
                title=display_title,
                location="、".join(dict.fromkeys(locations)),
                job_type=str(row.get("job_category") or "").strip() or None,
                summary=str(row.get("job_desc") or "").strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
                experience=(
                    f"{row.get('yoe_min')}年以上"
                    if isinstance(row.get("yoe_min"), (int, float))
                    and row.get("yoe_min") >= 0
                    else None
                ),
                education=str(row.get("degree_range_name") or "").strip() or None,
            ))
        return jobs
