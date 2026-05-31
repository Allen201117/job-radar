import json
import re
from typing import List

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, RawJob


class SiemensAdapter(BaseAdapter):
    """
    Siemens Careers — jobs.siemens.com

    尝试 Siemens careers API + HTML 解析。
    """

    name = "siemens"
    SEARCH_URL = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs"

    def fetch(self, source_url: str) -> str:
        url = self.SEARCH_URL if "careers/search" in source_url.lower() else source_url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,*/*",
        }
        resp = httpx.get(url, headers=headers, timeout=self.timeout,
                         follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str) -> List[RawJob]:
        jobs = []

        # Siemens 可能使用 embedded JSON data
        for pattern in [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});',
            r'"jobs"\s*:\s*(\[.+?\])',
            r'"searchResults"\s*:\s*(\[.+?\])',
        ]:
            for match in re.finditer(pattern, html, re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                    rows = data if isinstance(data, list) else data.get("jobs") or data.get("results") or []
                    if isinstance(rows, list):
                        for row in rows:
                            jobs.append(
                                RawJob(
                                    company="Siemens",
                                    title=row.get("title") or row.get("jobTitle") or row.get("name", ""),
                                    location=row.get("location") or row.get("city") or row.get("region"),
                                    job_type=row.get("jobType") or row.get("contractType"),
                                    summary=row.get("description") or row.get("teaser", ""),
                                    jd_url=row.get("url") or row.get("applyUrl") or "",
                                    salary_text=None,
                                    posted_at=row.get("postedDate") or row.get("publishDate"),
                                )
                            )
                    if jobs:
                        return jobs
                except (json.JSONDecodeError, TypeError):
                    pass

        # HTML 解析兜底
        try:
            tree = HTMLParser(html)
            for card in tree.css("article.article--result"):
                title_el = card.css_first("h3 a[href], a.link[href]")
                if not title_el:
                    continue

                title = title_el.text(strip=True)
                href = title_el.attrs.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://jobs.siemens.com" + href
                if "/JobDetail/" not in href:
                    continue

                location_parts = []
                for selector in (
                    ".list-item-jobCity",
                    ".list-item-jobState",
                    ".list-item-jobCountry",
                ):
                    value_el = card.css_first(selector)
                    value = value_el.text(strip=True) if value_el else ""
                    if value and value not in location_parts:
                        location_parts.append(value)

                family_el = card.css_first(".list-item-family")
                jobs.append(
                    RawJob(
                        company="Siemens",
                        title=title,
                        location=", ".join(location_parts) or None,
                        job_type=family_el.text(strip=True) if family_el else None,
                        jd_url=href,
                    )
                )

            if jobs:
                return jobs

            for card in tree.css(
                ".job-card, .job-result, .search-result-item, .job-listing, li"
            ):
                title_el = card.css_first(
                    ".job-title, .title, h3, a, .job-title-link"
                )
                loc_el = card.css_first(
                    ".job-location, .location, .city, .job-info-location"
                )
                link_el = card.css_first("a[href]")

                title = title_el.text(strip=True) if title_el else ""
                location = loc_el.text(strip=True) if loc_el else None
                jd_url = ""
                if link_el:
                    href = link_el.attrs.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://jobs.siemens.com" + href
                    jd_url = href

                if title and len(title) > 2:
                    jobs.append(
                        RawJob(
                            company="Siemens",
                            title=title,
                            location=location,
                            jd_url=jd_url,
                        )
                    )
        except Exception:
            pass

        return jobs
