import json
import re
from typing import List

import httpx

from .base import BaseAdapter, RawJob


class TencentAdapter(BaseAdapter):
    """
    腾讯招聘 — careers.tencent.com

    使用公开社招 JSON API（careers.tencent.com/tencentcareer/api/post/Query），
    详情页为 jobdesc.html?postId=...，postId 来自接口的 PostId 字段。
    """

    name = "tencent"
    API_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
    DETAIL_URL = "https://careers.tencent.com/jobdesc.html"
    PAGE_SIZE = 20
    MAX_PAGES = 3

    def fetch(self, source_url: str) -> str:
        """拉取腾讯公开社招列表 API（多页合并），返回统一 JSON 文本。"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": "https://careers.tencent.com/search.html",
        }
        posts = []
        for page in range(1, self.MAX_PAGES + 1):
            try:
                resp = httpx.get(
                    self.API_URL,
                    params={
                        "pageIndex": str(page),
                        "pageSize": str(self.PAGE_SIZE),
                        "language": "zh-cn",
                        "keyword": "",
                    },
                    headers=headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                page_posts = ((resp.json() or {}).get("Data") or {}).get("Posts") or []
            except Exception:
                if page == 1:
                    raise  # 首页失败交给 run.py 记录为 failed
                break  # 后续页尽力而为，保留已拿到的
            if not page_posts:
                break
            posts.extend(page_posts)
        return json.dumps({"Data": {"Posts": posts}}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = ((data or {}).get("Data") or {}).get("Posts") or []
        if not rows and isinstance(data, list):
            rows = data
        jobs = [_format_tencent_job(row) for row in rows]
        return [job for job in jobs if job.title and job.jd_url]


def _format_tencent_job(row: dict) -> RawJob:
    post_id = str(row.get("PostId") or "").strip()
    jd_url = f"{TencentAdapter.DETAIL_URL}?postId={post_id}" if post_id else ""
    return RawJob(
        company="腾讯",
        title=(row.get("RecruitPostName") or row.get("PostName") or "").strip(),
        location=row.get("LocationName") or row.get("CountryName"),
        job_type=row.get("CategoryName") or row.get("BGName"),
        summary=(row.get("Responsibility") or None),
        jd_url=jd_url,
        apply_url=jd_url,
        posted_at=_format_posted_at(row),
    )


def _format_posted_at(row: dict):
    """腾讯 LastUpdateTime 多为 '2026年05月30日'，统一成 ISO 日期；无法识别则 None。"""
    value = str(row.get("LastUpdateTime") or "")
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None
