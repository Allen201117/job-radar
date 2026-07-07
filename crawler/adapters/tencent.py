import json
import re
import time
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TencentAdapter(BaseAdapter):
    """
    腾讯招聘 — careers.tencent.com

    使用公开招聘 JSON API（careers.tencent.com/tencentcareer/api/post/Query），
    社招/校招/实习三板块按 attrId 分别分页；详情页优先使用 PostURL。
    """

    name = "tencent"
    API_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
    DETAIL_URL = "https://careers.tencent.com/jobdesc.html"
    PAGE_SIZE = 100
    PAGE_DELAY_SECONDS = 0.1
    BOARD_ATTRS = (("1", "社招"), ("2", "校招"), ("3", "实习"))

    def fetch(self, source_url: str) -> str:
        """拉取腾讯公开招聘列表 API（三板块按 Count 翻到底），返回统一 JSON 文本。"""
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": "https://careers.tencent.com/search.html",
        }
        posts = []
        totals = []
        board_complete = []
        for attr_id, _job_type in self.BOARD_ATTRS:
            board_posts = []
            total = None
            page = 1
            expected_pages = None
            while True:
                try:
                    resp = httpx.get(
                        self.API_URL,
                        params={
                            "keyword": getattr(self, "discovery_keyword", "") or "",
                            "pageIndex": str(page),
                            "pageSize": str(self.PAGE_SIZE),
                            "attrId": attr_id,
                            "language": "zh-cn",
                        },
                        headers=headers,
                        timeout=self.timeout,
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    data = ((resp.json() or {}).get("Data") or {})
                    if total is None:
                        total = _int_or_none(data.get("Count"))
                        if total is None:
                            total = _int_or_none(data.get("total"))
                        if total is None:
                            total = _int_or_none(data.get("count"))
                        if total is not None:
                            expected_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
                    page_posts = data.get("Posts") or []
                except Exception:
                    if page == 1:
                        raise  # 任一板块首页失败交给 run.py 记录为 failed
                    break  # 后续页尽力而为，保留已拿到的
                if not page_posts:
                    break
                for row in page_posts:
                    if isinstance(row, dict):
                        row["_attrId"] = attr_id
                board_posts.extend(page_posts)
                if total is not None and len(board_posts) >= total:
                    break
                if expected_pages is not None and page >= expected_pages:
                    break
                page += 1
                time.sleep(self.PAGE_DELAY_SECONDS)
            posts.extend(board_posts)
            if total is not None:
                totals.append(total)
            board_complete.append(total is not None and len(board_posts) >= total)
            time.sleep(self.PAGE_DELAY_SECONDS)
        if len(totals) == len(self.BOARD_ATTRS):
            self.reported_total = sum(totals)
        self.fetch_complete = bool(
            board_complete
            and len(board_complete) == len(self.BOARD_ATTRS)
            and all(board_complete)
        )
        return json.dumps({"Data": {"Posts": posts, "Count": self.reported_total}}, ensure_ascii=False)

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
    jd_url = (row.get("PostURL") or "").strip()
    if not jd_url and post_id:
        jd_url = f"{TencentAdapter.DETAIL_URL}?postId={post_id}"
    attr_id = str(row.get("_attrId") or row.get("attrId") or row.get("AttrId") or "").strip()
    return RawJob(
        company="腾讯",
        title=(row.get("RecruitPostName") or row.get("PostName") or "").strip(),
        location=row.get("LocationName") or row.get("CountryName"),
        job_type=_job_type_for_attr(attr_id) or row.get("CategoryName") or row.get("BGName"),
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


def _job_type_for_attr(attr_id: str) -> Optional[str]:
    return dict(TencentAdapter.BOARD_ATTRS).get(attr_id)
