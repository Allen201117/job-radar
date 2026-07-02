"""
通用 Ashby 看板适配器（公开 posting-api，无需鉴权）。

source_url = https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
一套适配覆盖任意用 Ashby 的公司 —— 新增公司只需加一行 sources 记录（slug = 看板标识）。

同 Greenhouse/Lever：服务「在华外企」覆盖，parse 只保留大中华区岗位（keep_for_china_radar）。
jd_url 用 Ashby 返回的 jobUrl（jobs.ashbyhq.com 托管的稳定 per-job 链接）。
"""
import json
from typing import List

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class AshbyAdapter(BaseAdapter):
    name = "ashby"

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
        rows = data.get("jobs", []) if isinstance(data, dict) else []

        out: List[RawJob] = []
        for j in rows:
            if not isinstance(j, dict):
                continue
            if j.get("isListed") is False:
                continue
            title = (j.get("title") or "").strip()
            jd_url = (j.get("jobUrl") or j.get("applyUrl") or "").strip()
            if not title or not jd_url:
                continue
            location = j.get("location") or _address_location(j.get("address"))
            if not normalizer.location_in_source_regions(location, getattr(self, "regions", None)):
                continue
            job_type = j.get("employmentType") or j.get("department") or j.get("team")
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=job_type,
                summary=(j.get("descriptionPlain") or j.get("descriptionHtml") or None),
                jd_url=jd_url,
                apply_url=(j.get("applyUrl") or jd_url),
                posted_at=(j.get("publishedAt") or "")[:10] or None,
            ))
        return out


def _address_location(address):
    """Ashby 部分岗位 location 为空，回退用结构化 address 拼地点串。"""
    if not isinstance(address, dict):
        return None
    postal = address.get("postalAddress")
    if not isinstance(postal, dict):
        return None
    parts = [postal.get("addressLocality"), postal.get("addressRegion"), postal.get("addressCountry")]
    joined = ", ".join(p for p in parts if p)
    return joined or None
