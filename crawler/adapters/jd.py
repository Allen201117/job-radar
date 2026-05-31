import json
import re
from datetime import datetime, timezone
from typing import List

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, RawJob


class JdAdapter(BaseAdapter):
    """
    京东招聘 — zhaopin.jd.com

    尝试京东社招 API + HTML 解析兜底。
    """

    name = "jd"
    LIST_PAGE_URL = "https://zhaopin.jd.com/web/job/job_info_list/3"
    API_URL = "https://zhaopin.jd.com/web/job/job_list"
    DETAIL_URL = "https://zhaopin.jd.com/web/job-info-detail"

    def fetch(self, source_url: str) -> str:
        """Fetch the public JD social-recruitment list API."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://zhaopin.jd.com",
            "Referer": self.LIST_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        data = {
            "pageIndex": "1",
            "pageSize": "15",
            "workCityJson": "[]",
            "jobTypeJson": "[]",
            "jobSearch": "",
            "depTypeJson": "[]",
        }
        resp = httpx.post(self.API_URL, headers=headers, data=data, timeout=self.timeout,
                          follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str) -> List[RawJob]:
        jobs = []

        # 尝试提取嵌入的 JSON 数据
        try:
            data = json.loads(html)
            rows = data if isinstance(data, list) else _find_job_list(data)
            jobs = [_format_jd_job(row) for row in rows]
            return [job for job in jobs if job.title and job.jd_url]
        except (json.JSONDecodeError, TypeError):
            pass

        for match in re.finditer(
            r'(?:window\.__INITIAL_STATE__|window\.__NUXT__|window\.__DATA__)\s*=\s*(\{.+?\});',
            html,
            re.DOTALL,
        ):
            try:
                data = json.loads(match.group(1))
                # 递归查找 job list
                rows = _find_job_list(data)
                jobs.extend(_format_jd_job(row) for row in rows)
                if jobs:
                    return [job for job in jobs if job.title and job.jd_url]
            except (json.JSONDecodeError, TypeError):
                pass

        # HTML 解析兜底
        try:
            tree = HTMLParser(html)
            for card in tree.css(".job-card, .job-item, .position-item, li, tr"):
                title_el = card.css_first(".job-title, .title, h3, a, td")
                loc_el = card.css_first(".location, .city, .addr, td:nth-child(3)")
                link_el = card.css_first("a[href]")

                title = title_el.text(strip=True) if title_el else ""
                location = loc_el.text(strip=True) if loc_el else None
                jd_url = ""
                if link_el:
                    href = link_el.attrs.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://zhaopin.jd.com" + href
                    jd_url = href

                if title and len(title) > 2:
                    jobs.append(
                        RawJob(
                            company="京东",
                            title=title,
                            location=location,
                            jd_url=jd_url,
                        )
                    )
        except Exception:
            pass

        return jobs


def _format_jd_job(row: dict) -> RawJob:
    requirement_id = str(row.get("requirementId") or row.get("requementId") or "").strip()
    jd_url = f"{JdAdapter.DETAIL_URL}?requementId={requirement_id}" if requirement_id else ""
    work_content = row.get("workContent") or row.get("description") or row.get("jobDesc") or ""
    qualification = row.get("qualification") or ""
    summary = "\n".join(part for part in [work_content, qualification] if part)

    return RawJob(
        company="京东",
        title=(
            row.get("positionNameOpen")
            or row.get("positionName")
            or row.get("title")
            or row.get("jobName")
            or row.get("name")
            or ""
        ),
        location=row.get("workCity") or row.get("location") or row.get("city") or row.get("workCityName"),
        job_type=row.get("jobType") or row.get("recruitType"),
        summary=summary or None,
        jd_url=jd_url,
        apply_url=jd_url,
        posted_at=_format_posted_at(row),
    )


def _format_posted_at(row: dict):
    if row.get("formatPublishTime"):
        return row.get("formatPublishTime")

    value = row.get("publishTime") or row.get("createTime")
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    return value


def _find_job_list(obj, depth=0):
    """递归查找 job list。"""
    if depth > 5:
        return []
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("positionNameOpen", "requirementId", "title", "jobName", "name")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _find_job_list(v, depth + 1)
            if result:
                return result
    if isinstance(obj, list):
        for item in obj:
            result = _find_job_list(item, depth + 1)
            if result:
                return result
    return []
