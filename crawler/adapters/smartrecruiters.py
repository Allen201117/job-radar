"""
通用 SmartRecruiters 适配器（公开 Posting API，无需鉴权）。

source_url = https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100
一套适配覆盖任意用 SmartRecruiters 的公司 —— 大量在华跨国企业（外企100强常见）用此 ATS。
新增公司只需加一行 sources 记录（slug = 公司在 SmartRecruiters 的 identifier）。

同 Greenhouse/Lever：服务「在华外企」覆盖，parse 只保留大中华区岗位（keep_for_china_radar）。
jd_url 用 jobs.smartrecruiters.com 托管的稳定 per-job 链接：{identifier}/{postingId}。
"""
import json
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class SmartRecruitersAdapter(BaseAdapter):
    name = "smartrecruiters"

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检，由 GET 暴露真实错误

    def fetch(self, source_url: str) -> str:
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        resp = httpx.get(source_url, headers=headers, timeout=self.timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("content", []) if isinstance(data, dict) else []

        out: List[RawJob] = []
        for j in rows:
            if not isinstance(j, dict):
                continue
            title = (j.get("name") or "").strip()
            posting_id = str(j.get("id") or j.get("uuid") or "").strip()
            identifier = ((j.get("company") or {}).get("identifier") or "").strip()
            if not title or not posting_id or not identifier:
                continue
            jd_url = f"https://jobs.smartrecruiters.com/{identifier}/{posting_id}"
            location = _location_str(j.get("location"))
            if not normalizer.keep_for_china_radar(location):
                continue
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=(j.get("typeOfEmployment") or {}).get("label") if isinstance(j.get("typeOfEmployment"), dict) else None,
                summary=None,  # 列表接口无正文；normalizer 不强制 summary
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(j.get("releasedDate") or "")[:10] or None,
            ))
        return out


def _location_str(loc) -> Optional[str]:
    if not isinstance(loc, dict):
        return None
    if loc.get("remote") is True:
        # 远程岗位地点串带上国家，便于 keep_for_china_radar 判定是否绑定海外
        country = loc.get("country") or ""
        return f"Remote {country}".strip()
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    joined = ", ".join(p for p in parts if p)
    return joined or None
