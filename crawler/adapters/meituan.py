"""美团招聘公开岗位 API 适配器（零登录、零浏览器）。"""
import json
import time
import uuid
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MeituanAdapter(BaseAdapter):
    name = "meituan"
    company_name = "美团"

    API_URL = "https://zhaopin.meituan.com/api/official/job/getJobList"
    DETAIL_URL = (
        "https://zhaopin.meituan.com/web/position/detail"
        "?jobUnionId={job_id}&highlightType=social"
    )
    PAGE_SIZE = 50
    # 官网社招实测 ~2830 岗；旧上限 20×50=1000 封顶只抓到 ~35%。提到 80×50=4000
    # 覆盖全量（分页按 page_rows<PAGE_SIZE 自然停，不会真跑满 80 页）。
    MAX_PAGES = 80

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://zhaopin.meituan.com/web/position",
            "Origin": "https://zhaopin.meituan.com",
        }
        rows = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, self.MAX_PAGES + 1):
                payload = {
                    "page": {"pageNo": page_no, "pageSize": self.PAGE_SIZE},
                    "jobShareType": "1",
                    "keywords": "",
                    "cityList": [],
                    "department": [],
                    "jfJgList": [],
                    "jobType": [],
                    "typeCode": [],
                    "specialCode": [],
                    "u_query_id": uuid.uuid4().hex,
                    "r_query_id": f"{int(time.time() * 1000)}{page_no}",
                }
                response = client.post(self.API_URL, json=payload)
                response.raise_for_status()
                data = ((response.json() or {}).get("data") or {})
                if self.reported_total is None:
                    page = data.get("page") if isinstance(data.get("page"), dict) else {}
                    total = _int_or_none(page.get("totalCount"))
                    if total is None:
                        total = _int_or_none(data.get("total"))
                    if total is not None:
                        # Crawl coverage visibility: official reported total only, no pagination changes.
                        self.reported_total = total
                page_rows = data.get("list") or []
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < self.PAGE_SIZE:
                    break
        if not rows:
            raise RuntimeError("meituan: empty getJobList response")
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"data": {"list": rows}}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = ((json.loads(html) or {}).get("data") or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs = []
        for row in rows:
            job_id = str(row.get("jobUnionId") or "").strip()
            title = str(row.get("name") or "").strip()
            city_names = [
                str(city.get("name") or "").strip()
                for city in (row.get("cityList") or [])
                if isinstance(city, dict)
                and is_china_company_location(str(city.get("name") or ""))
            ]
            if not (job_id and title and city_names):
                continue
            duty = str(row.get("jobDuty") or row.get("desc") or "").strip()
            requirement = str(row.get("jobRequirement") or "").strip()
            summary = (
                duty + ("\n\n【任职要求】\n" + requirement if requirement else "")
            ).strip() or None
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location="、".join(dict.fromkeys(city_names)),
                job_type=(
                    str(row.get("jobFamilyGroup") or row.get("jobFamily") or "").strip()
                    or None
                ),
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=normalizer.pick_publish_date(row),
            ))
        return jobs
