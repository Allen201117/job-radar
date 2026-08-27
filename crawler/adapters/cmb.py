"""招商银行社会招聘门户适配器（纯 httpx、零鉴权）。"""
import json
import re
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_html(value) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


class CmbAdapter(BaseAdapter):
    name = "cmb"

    LIST_API = "https://career.cmbchina.com/api/socialRecruitmentWebsite/job/getList"
    DETAIL_API = "https://career.cmbchina.com/api/socialRecruitmentWebsite/job/getDetail"
    DETAIL_URL = "https://career.cmbchina.com/positionDetail/social?publishId={publish_id}"
    PAGE_SIZE = 100
    MAX_PAGES = 100
    _DETAIL_CAP = 200

    @staticmethod
    def _summary_of(detail: dict) -> Optional[str]:
        parts = []
        responsibility = _clean_html(detail.get("jobResponsibility"))
        requirement = _clean_html(detail.get("jobRequirement"))
        if responsibility:
            parts.append(f"【岗位职责】\n{responsibility}")
        if requirement:
            parts.append(f"【任职要求】\n{requirement}")
        return "\n".join(parts) or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, json={
                    "jobTypeIdList": [], "orgIdList": [],
                    "pageIndex": page, "pageSize": self.PAGE_SIZE,
                })
                response.raise_for_status()
                payload = response.json() or {}
                if payload.get("returnCode") != "SUC0000":
                    raise RuntimeError(f"cmb: getList returnCode={payload.get('returnCode')}")
                body = payload.get("body") or {}
                rows = body.get("data") or []
                if not isinstance(rows, list):
                    raise RuntimeError("cmb: getList body.data is not a list")
                return PageResult(items=rows, total=_int_or_none(body.get("total")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="cmb",
            )
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                publish_id = str((row or {}).get("publishGID") or "").strip()
                if not publish_id:
                    continue
                try:
                    response = client.get(self.DETAIL_API, params={"publishId": publish_id})
                    response.raise_for_status()
                    detail_payload = response.json() or {}
                    if detail_payload.get("returnCode") == "SUC0000" and isinstance(detail_payload.get("body"), dict):
                        row["_detail"] = detail_payload["body"]
                except httpx.HTTPError:
                    continue
        if not rows:
            raise RuntimeError("cmb: getList returned no jobs")
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
            publish_id = str(row.get("publishGID") or "").strip()
            title = str(row.get("jobDisplay") or "").strip()
            if not (publish_id and title):
                continue
            jd_url = self.DETAIL_URL.format(publish_id=publish_id)
            jobs.append(RawJob(
                company="", title=title,
                location=str(row.get("locationName") or "").strip() or None,
                job_type="社招", summary=self._summary_of(row.get("_detail") or {}),
                jd_url=jd_url, apply_url=jd_url,
                deadline=str(row.get("expiredOn") or "").strip() or None,
            ))
        return jobs
