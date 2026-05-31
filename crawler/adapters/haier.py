import json
import re
from typing import List

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, RawJob


class HaierAdapter(BaseAdapter):
    """
    海尔招聘 — maker.haier.net

    海尔招聘页面可能使用 JSONP 或 JS 渲染。
    尝试提取嵌入数据 + HTML 解析。
    """

    name = "haier"

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,*/*",
        }
        resp = httpx.get(source_url, headers=headers, timeout=self.timeout,
                         follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str) -> List[RawJob]:
        jobs = []

        # 尝试 JSON 嵌入数据
        for pattern in [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});',
            r'"jobList"\s*:\s*(\[.+?\])',
            r'"list"\s*:\s*(\[.+?\])',
        ]:
            for match in re.finditer(pattern, html, re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, dict):
                        rows = data.get("list") or data.get("records") or []
                    else:
                        rows = data
                    if isinstance(rows, list):
                        for row in rows:
                            jobs.append(
                                RawJob(
                                    company="海尔",
                                    title=row.get("title") or row.get("jobName") or row.get("name", ""),
                                    location=row.get("location") or row.get("city") or row.get("workCity"),
                                    job_type=row.get("jobType") or row.get("recruitType"),
                                    summary=row.get("description") or row.get("jobDesc", ""),
                                    jd_url=row.get("url") or row.get("jobUrl") or "",
                                    posted_at=row.get("publishTime") or row.get("createTime"),
                                )
                            )
                    if jobs:
                        return jobs
                except (json.JSONDecodeError, TypeError):
                    pass

        # HTML 解析
        try:
            tree = HTMLParser(html)
            for card in tree.css(
                ".job-card, .job-item, .position-item, .recruit-item, li, .list-item"
            ):
                title_el = card.css_first(
                    ".job-title, .title, h3, a, .job-name, .position-name"
                )
                loc_el = card.css_first(
                    ".location, .city, .addr, .job-location, .work-place"
                )
                link_el = card.css_first("a[href]")

                title = title_el.text(strip=True) if title_el else ""
                location = loc_el.text(strip=True) if loc_el else None
                jd_url = ""
                if link_el:
                    href = link_el.attrs.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://maker.haier.net" + href
                    jd_url = href

                if title and len(title) > 2:
                    jobs.append(
                        RawJob(
                            company="海尔",
                            title=title,
                            location=location,
                            jd_url=jd_url,
                        )
                    )
        except Exception:
            pass

        return jobs
