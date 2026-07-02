"""
通用 Lever 适配器（公开 postings API，无需鉴权）。

source_url = https://api.lever.co/v0/postings/{token}?mode=json
一套适配覆盖任意用 Lever 的公司 —— 新增公司只需加一行 sources 记录。

同 Greenhouse：服务「在华外企」覆盖，parse 只保留大中华区岗位。
jd_url 用 Lever 托管的 hostedUrl（稳定 per-job 链接）。
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class LeverAdapter(BaseAdapter):
    name = "lever"

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检，由 GET 暴露真实错误

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
        rows = data if isinstance(data, list) else []

        out: List[RawJob] = []
        for j in rows:
            title = (j.get("text") or "").strip()
            jd_url = (j.get("hostedUrl") or j.get("applyUrl") or "").strip()
            if not title or not jd_url:
                continue
            categories = j.get("categories") or {}
            location = categories.get("location")
            if not normalizer.location_in_source_regions(location, getattr(self, "regions", None)):
                continue  # 默认大中华区 + 不绑定海外的 remote;海外源按 regions 放行
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=categories.get("team") or categories.get("commitment"),
                summary=(j.get("descriptionPlain") or None),
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=_epoch_ms_to_date(j.get("createdAt")),
            ))
        return out


def _epoch_ms_to_date(ms) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
