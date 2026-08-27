"""格力公开招聘门户适配器（纯 httpx、零鉴权）。"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class GreeAdapter(BaseAdapter):
    name = "gree"

    LIST_API = "https://zhaopin.greeyun.com/api/apply/jobs"
    DETAIL_URL = "https://zhaopin.greeyun.com/job?JobCode={job_code}&recruitType={property}"
    PAGE_SIZE = 50
    MAX_PAGES = 100
    _PROPERTIES = (1, 2)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        parts = []
        description = str(row.get("Description") or "").strip()
        qualifications = str(row.get("Qualifications") or "").strip()
        if description:
            parts.append(f"【岗位职责】\n{description}")
        if qualifications:
            parts.append(f"【任职要求】\n{qualifications}")
        return "\n".join(parts) or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}
        all_rows = []
        totals = []
        complete = True
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for property_value in self._PROPERTIES:
                def fetch_page(page: int, property_value=property_value) -> PageResult:
                    response = client.get(self.LIST_API, params={
                        "category": "", "pageNum": page,
                        "pageSize": self.PAGE_SIZE, "property": property_value,
                    })
                    response.raise_for_status()
                    payload = response.json() or {}
                    if payload.get("code") != 200:
                        raise RuntimeError(f"gree: jobs code={payload.get('code')}")
                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    if not isinstance(rows, list):
                        raise RuntimeError("gree: jobs data.list is not a list")
                    for row in rows:
                        if isinstance(row, dict):
                            row["_property"] = property_value
                    return PageResult(items=rows, total=_int_or_none(data.get("total")))

                rows, total, board_complete = paginate_all(
                    fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                    max_pages=self.MAX_PAGES, label=f"gree:{property_value}",
                )
                all_rows.extend(rows)
                totals.append(total)
                complete = complete and board_complete
        if not all_rows:
            raise RuntimeError("gree: jobs returned no jobs")
        self.reported_total = sum(t for t in totals if t is not None) if all(t is not None for t in totals) else None
        self.fetch_complete = complete
        return json.dumps({"jobs": all_rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_code = str(row.get("Code") or "").strip()
            title = str(row.get("Position") or "").strip()
            try:
                property_value = int(row.get("_property", row.get("property")))
            except (TypeError, ValueError):
                continue
            if not (job_code and title and property_value in self._PROPERTIES):
                continue
            category = str(row.get("Category") or "").strip()
            job_type = "社招" if property_value == 2 or "社会招聘" in category else "校招"
            if "实习" in title:
                job_type = None
            jd_url = self.DETAIL_URL.format(job_code=job_code, property=property_value)
            jobs.append(RawJob(
                company="", title=title,
                location=str(row.get("Location") or "").strip() or None,
                job_type=job_type, summary=self._summary_of(row), jd_url=jd_url,
                apply_url=jd_url,
                experience=str(row.get("Experience") or "").strip() or None,
                education=str(row.get("Education") or "").strip() or None,
                posted_at=str(row.get("PubTime") or "").strip() or None,
            ))
        return jobs
