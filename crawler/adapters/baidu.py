import json
import re
from typing import List

import httpx

from .base import BaseAdapter, RawJob


class BaiduAdapter(BaseAdapter):
    """
    百度招聘 — talent.baidu.com

    百度招聘页面服务端渲染 `window.__INITIAL_DATA__`，列表项里的
    postId 与官方点击逻辑共同构成公开详情页 URL：
    /jobs/detail/{recruitType}/{postId}
    """

    name = "baidu"
    DEFAULT_URL = "https://talent.baidu.com/jobs/social-list"

    def fetch(self, source_url: str) -> str:
        """请求百度官方招聘列表页 HTML。"""
        url = source_url or self.DEFAULT_URL
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,en;q=0.9",
        }
        response = httpx.get(url, headers=headers, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text

    def parse(self, html: str) -> List[RawJob]:
        """解析返回内容。"""
        jobs = []

        # 尝试 JSON 解析
        try:
            data = json.loads(html)
            rows = (
                data.get("data", {}).get("list", [])
                or data.get("data", {}).get("records", [])
                or data.get("result", {}).get("items", [])
                or []
            )
            for row in rows:
                jobs.append(
                    RawJob(
                        company="百度",
                        title=row.get("title") or row.get("jobName") or row.get("name", ""),
                        location=row.get("location") or row.get("city") or row.get("workCity"),
                        job_type=row.get("jobType") or row.get("recruitType"),
                        summary=row.get("description") or row.get("jobDesc", ""),
                        jd_url=row.get("url") or row.get("jobUrl") or "",
                        posted_at=row.get("publishTime") or row.get("createTime"),
                    )
                )
            return jobs
        except (json.JSONDecodeError, TypeError):
            pass

        jobs.extend(self._parse_initial_data(html))

        return jobs

    def _parse_initial_data(self, html: str) -> List[RawJob]:
        match = re.search(
            r"window\.__INITIAL_DATA__\s*=(.*?);\s*window\.prefix",
            html,
            re.S,
        )
        if not match:
            return []

        raw = match.group(1).strip()
        raw = re.sub(r"(?<=[:\[,])\s*undefined\s*(?=[,}\]])", "null", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        list_data = data.get("listData") or {}
        recruit_type = list_data.get("recruitType") or "SOCIAL"
        rows = list_data.get("listDetailData") or []

        jobs: List[RawJob] = []
        for row in rows:
            post_id = row.get("postId")
            title = row.get("name")
            if not post_id or not title:
                continue

            row_recruit_type = row.get("recruitType") or recruit_type
            jd_url = f"https://talent.baidu.com/jobs/detail/{row_recruit_type}/{post_id}"
            jobs.append(
                RawJob(
                    company="百度",
                    title=title,
                    location=row.get("workPlace"),
                    job_type=row.get("postType") or row.get("projectType"),
                    summary=row.get("workContent") or row.get("serviceCondition"),
                    jd_url=jd_url,
                    apply_url=jd_url,
                    posted_at=row.get("updateDate") or row.get("publishDate"),
                )
            )
        return jobs
