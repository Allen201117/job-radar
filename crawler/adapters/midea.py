"""美的集团公开招聘门户适配器（纯 httpx、零鉴权）。"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MideaAdapter(BaseAdapter):
    name = "midea"

    LIST_API = "https://recruit.midea.com/backend/rec/home/out/official/position/list"
    DETAIL_URL = (
        "https://recruit.midea.com/recruitOut/ihr/social/jobApplication"
        "?positionId={position_id}&recruitType=social"
    )
    PAGE_SIZE = 100
    MAX_PAGES = 100

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        parts = []
        duties = str(row.get("postDuties") or "").strip()
        qualification = str(row.get("qualification") or "").strip()
        if duties:
            parts.append(f"【岗位职责】\n{duties}")
        if qualification:
            parts.append(f"【任职要求】\n{qualification}")
        return "\n".join(parts) or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, data={
                    "pageSize": self.PAGE_SIZE,
                    "pageIndex": page,
                    "publicationName": "",
                })
                response.raise_for_status()
                payload = response.json() or {}
                rows = payload.get("data") or []
                if not isinstance(rows, list):
                    raise RuntimeError("midea: position/list data is not a list")
                return PageResult(items=rows, total=_int_or_none(payload.get("total")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="midea",
            )
        if not rows:
            raise RuntimeError("midea: position/list returned no jobs")
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
            position_id = str(row.get("positionId") or "").strip()
            title = str(row.get("demandPositionName") or "").strip()
            if not (position_id and title):
                continue
            jd_url = self.DETAIL_URL.format(position_id=position_id)
            low = str(row.get("minWorking") or "").strip()
            high = str(row.get("maxWorking") or "").strip()
            experience = f"{low}-{high}年" if low and high and low != high else (f"{low}年以上" if low else None)
            jobs.append(RawJob(
                company="", title=title,
                location=str(row.get("workingPlace") or "").strip() or None,
                job_type="社招", summary=self._summary_of(row), jd_url=jd_url,
                apply_url=jd_url, experience=experience,
                education=str(row.get("education") or "").strip() or None,
            ))
        return jobs
