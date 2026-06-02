"""
通用 Greenhouse 看板适配器（公开 boards-api，无需鉴权）。

source_url = https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
一套适配覆盖任意用 Greenhouse 的公司 —— 新增公司只需加一行 sources 记录。

定位：服务「在华外企」覆盖，因此 parse 只保留**大中华区岗位**（is_china_location），
避免把外企看板上的全球岗位灌进中国雷达。jd_url 用 Greenhouse 托管的 absolute_url（稳定 per-job 链接）。
"""
import json
from typing import List

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检（部分不支持 HEAD），由 GET 暴露真实错误

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        resp = httpx.get(source_url, headers=headers, timeout=self.timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("jobs", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        out: List[RawJob] = []
        for j in rows:
            title = (j.get("title") or "").strip()
            jd_url = (j.get("absolute_url") or "").strip()
            if not title or not jd_url:
                continue
            loc_obj = j.get("location")
            location = loc_obj.get("name") if isinstance(loc_obj, dict) else None
            if not normalizer.keep_for_china_radar(location):
                continue  # 大中华区 + 不绑定海外的 remote;排除 base 海外
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=None,
                summary=(j.get("content") or None),  # content=true 时为 HTML，clean_summary 会去标签
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(j.get("updated_at") or "")[:10] or None,
            ))
        return out
