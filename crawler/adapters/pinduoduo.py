"""拼多多校园招聘公开 API 适配器（零登录、零浏览器）。"""
import json
from datetime import datetime, timezone
from typing import List

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _date_from_millis(value):
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _has_more_pages(total, collected: int) -> bool:
    try:
        return collected < int(total)
    except (TypeError, ValueError):
        return True


class PinduoduoAdapter(BaseAdapter):
    name = "pinduoduo"
    company_name = "拼多多"

    LIST_URL = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/list"
    DETAIL_URL = (
        "https://careers.pddglobalhr.com/campus/grad/detail?positionId={job_id}"
    )
    PAGE_SIZE = 50
    MAX_PAGES = 20

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://careers.pddglobalhr.com/campus/grad",
            "Origin": "https://careers.pddglobalhr.com",
        }
        rows = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, self.MAX_PAGES + 1):
                response = client.post(
                    self.LIST_URL,
                    json={"page": page_no, "pageSize": self.PAGE_SIZE, "t": None},
                )
                response.raise_for_status()
                body = response.json() or {}
                if not body.get("success"):
                    raise RuntimeError(
                        f"pinduoduo: list error {body.get('errorCode')} {body.get('errorMsg')}"
                    )
                result = body.get("result") or {}
                page_rows = result.get("list") or []
                if not page_rows:
                    break
                rows.extend(page_rows)
                if not _has_more_pages(result.get("total"), len(rows)):
                    break
        if not rows:
            raise RuntimeError("pinduoduo: empty position list")
        return json.dumps({"result": {"list": rows}}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = ((json.loads(html) or {}).get("result") or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("name") or "").strip()
            location = str(
                row.get("workLocationName") or row.get("workLocation") or ""
            ).strip()
            if not (job_id and title and is_china_company_location(location)):
                continue
            duty = str(row.get("jobDuty") or "").strip()
            requirement = str(
                row.get("serveRequirement") or row.get("serviceRequirement") or ""
            ).strip()
            summary = (
                duty + ("\n\n【任职要求】\n" + requirement if requirement else "")
            ).strip() or None
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=str(row.get("jobName") or "").strip() or None,
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=_date_from_millis(row.get("releaseTime")),
            ))
        return jobs
