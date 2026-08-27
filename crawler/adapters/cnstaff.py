"""聘客 cnstaff 企业招聘门户通用适配器（公开 joblist API，纯 httpx）。"""
import html as html_lib
import json
import re
from typing import List
from urllib.parse import urlsplit

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, RawJob


def _clean_html(value) -> str:
    return re.sub(r"\s+", " ", HTMLParser(html_lib.unescape(str(value or ""))).text()).strip()


class CnstaffAdapter(BaseAdapter):
    name = "cnstaff"

    @staticmethod
    def _host_and_tenant(source_url: str) -> tuple[str, str]:
        host = urlsplit(source_url).netloc.lower().split(":")[0]
        tenant = host.split(".")[0] if host.endswith(".cnstaff.com") else ""
        if not tenant:
            raise ValueError("cnstaff: source_url 必须是 {tenant}.cnstaff.com")
        return host, tenant

    @staticmethod
    def _jobs_from_payload(data) -> List[dict]:
        """所有招聘类型 × 职类取并集；``全部`` 分类是截断视图，不能单独使用。"""
        jobs = {}
        for group in data or []:
            job_type = str((group or {}).get("system_job_type_cn") or "").strip()
            for category in (group or {}).get("son") or []:
                for row in (category or {}).get("son") or []:
                    job_id = str((row or {}).get("job_id") or "").strip()
                    if job_id and job_id not in jobs:
                        jobs[job_id] = {"row": row, "job_type": job_type}
        return list(jobs.values())

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        host, tenant = self._host_and_tenant(source_url)
        api = f"https://{host}/api/{tenant}/joblist.json"
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}
        response = httpx.post(api, data={"jt": "0"}, headers=headers,
                              timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        payload = response.json() or {}
        if str(payload.get("errno")) != "200":
            raise RuntimeError(f"cnstaff: joblist errno={payload.get('errno')}")
        jobs = self._jobs_from_payload(payload.get("data"))
        self.reported_total = len(jobs)  # 无分页，分类并集就是接口可见全集。
        self.fetch_complete = True
        return json.dumps({"host": host, "jobs": jobs}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            data = json.loads(payload) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        host = str(data.get("host") or "").strip().lower()
        jobs = data.get("jobs")
        # 允许单测直接喂官方原始 payload，仍按全分类并集处理。
        if jobs is None:
            jobs = self._jobs_from_payload(data.get("data"))
        if not host:
            host = "tenant.cnstaff.com"  # 原始 payload 无 source host；只用于不可点击的单测输入。
        out = []
        for item in jobs or []:
            row = (item or {}).get("row") or {}
            job_id = str(row.get("job_id") or "").strip()
            title = str(row.get("job_name") or "").strip()
            if not (job_id and title):
                continue
            group_type = str((item or {}).get("job_type") or "").strip()
            job_type = "社招" if group_type == "社会招聘" else "校招" if group_type == "校园招聘" else None
            posted_at = str(row.get("job_published_at") or "").strip().split(" ")[0] or None
            out.append(RawJob(
                company="", title=title,
                location=str(row.get("job_address_name") or "").strip() or None,
                job_type=job_type, summary=_clean_html(row.get("job_desc")) or None,
                jd_url=f"https://{host}/recruitment/job/detail/id/{job_id}/",
                posted_at=posted_at,
            ))
        return out
