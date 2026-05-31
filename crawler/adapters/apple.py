import json
import re
from urllib.parse import urlencode

import httpx
from typing import List

from .base import BaseAdapter, RawJob


class AppleAdapter(BaseAdapter):
    """Apple Jobs — public search page hydration data."""

    name = "apple"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )
    SEARCH_URL = "https://jobs.apple.com/en-us/search"

    def fetch(self, source_url: str) -> str:
        """Fetch Apple's public search pages and return a JSON job array."""
        queries = ["software", "machine learning", "data", "product", "engineering"]
        all_jobs = []

        for query in queries[:3]:
            url = f"{self.SEARCH_URL}?{urlencode({'search': query, 'location': 'united-states-USA'})}"
            resp = httpx.get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            results = self._extract_hydration_rows(resp.text)
            all_jobs.extend(results[:50])

        return json.dumps(all_jobs)

    def parse(self, html: str) -> List[RawJob]:
        """Parse either fetch()'s JSON array or a raw public search page."""
        try:
            rows = json.loads(html)
        except json.JSONDecodeError:
            rows = self._extract_hydration_rows(html)

        jobs = []
        for row in rows:
            title = row.get("postingTitle", "")
            slug = row.get("transformedPostingTitle") or self._slugify(title)
            team_code = (
                f"?team={row['team']['teamCode']}"
                if row.get("team", {}).get("teamCode")
                else ""
            )
            job_id = row.get("id") or row.get("reqId")
            if not job_id or not title:
                continue
            jd_url = (
                f"https://jobs.apple.com/en-us/details/{job_id}/{slug}{team_code}"
            )

            location = None
            if row.get("locations"):
                location = ", ".join(
                    loc.get("name", "") for loc in row["locations"] if loc.get("name")
                )

            summary = row.get("jobSummary", "")

            jobs.append(
                RawJob(
                    company="Apple",
                    title=title,
                    location=location,
                    job_type="社招" if row.get("type") == "REQ" else None,
                    summary=summary[:250] if summary else None,
                    jd_url=jd_url,
                    apply_url=jd_url,
                    salary_text=None,
                    posted_at=row.get("postDateInGMT") or row.get("postingDate"),
                )
            )
        return jobs

    @staticmethod
    def _extract_hydration_rows(html: str) -> List[dict]:
        match = re.search(
            r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("([\s\S]*?)"\);</script>',
            html or "",
        )
        if not match:
            return []

        try:
            hydration_text = json.loads(f'"{match.group(1)}"')
            hydration = json.loads(hydration_text)
        except json.JSONDecodeError:
            return []

        rows = (
            hydration.get("loaderData", {})
            .get("search", {})
            .get("searchResults", [])
        )
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        return slug or "job"
