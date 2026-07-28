import json
import re
from urllib.parse import urlencode

import httpx
from typing import List

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all


class AppleAdapter(BaseAdapter):
    """Apple Jobs — public search page hydration data."""

    name = "apple"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )
    SEARCH_URL = "https://jobs.apple.com/en-us/search"
    SEARCH_LOCATION = "united-states-USA"  # 子类置空 = 不限地点（全球混合，再按需过滤）
    CHINA_ONLY = False                      # 子类置 True = parse 后只保留在华/remote 岗

    PAGE_SIZE = 20        # Apple 搜索页每页固定 20 条（实测）
    MAX_PAGES = 400       # 安全上限：全量 ~6000 岗 ÷ 20 ≈ 303 页，留余量

    def fetch(self, source_url: str) -> str:
        """翻全 Apple 公开搜索页，返回 JSON 岗位数组。

        旧实现只发 3 个写死的关键词（software / machine learning / data）各取首页，
        每轮固定只拿到 60 条，而库里已有 1041 条 active —— 岗位绝大多数永远刷不到
        （2026-07-28 实测 apple 源 3 天刷新率仅 11%，是全库最差之一）。
        现改为**空关键词枚举 + 逐页翻到底**：`?search=` 不带词即返回全部岗位，
        hydration 里 `totalRecords` 给出分母（实测限美国 4636 / 全球 6047），
        `?page=N` 逐页 20 条且页间零重叠 —— 三点都已 live 验证。
        关键词枚举天然带偏且互相重叠，改成全量枚举后覆盖面和可核对性都更好。
        """
        params = {"search": ""}
        if self.SEARCH_LOCATION:
            params["location"] = self.SEARCH_LOCATION

        def fetch_page(page: int) -> PageResult:
            url = f"{self.SEARCH_URL}?{urlencode({**params, 'page': page})}"
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
            search = self._extract_search_node(resp.text)
            rows = search.get("searchResults")
            total = search.get("totalRecords")
            return PageResult(
                items=rows if isinstance(rows, list) else [],
                total=total if isinstance(total, int) else None,
            )

        rows, total, complete = paginate_all(
            fetch_page,
            page_size=self.PAGE_SIZE,
            first_page=1,
            max_pages=self.MAX_PAGES,
            delay_seconds=0.15,   # 礼貌爬取：几百页别把对方打毛
            label=f"apple:{self.name}",
        )
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps(rows)

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
        if self.CHINA_ONLY:
            jobs = [
                j for j in jobs
                if normalizer.location_in_source_regions(j.location, getattr(self, "regions", None))
            ]
        return jobs

    @staticmethod
    def _extract_search_node(html: str) -> dict:
        """抽 hydration 里的 search 节点（含 searchResults 与 totalRecords）。抽不到返回 {}。"""
        match = re.search(
            r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("([\s\S]*?)"\);</script>',
            html or "",
        )
        if not match:
            return {}

        try:
            hydration_text = json.loads(f'"{match.group(1)}"')
            hydration = json.loads(hydration_text)
        except json.JSONDecodeError:
            return {}

        node = (hydration.get("loaderData") or {}).get("search")
        return node if isinstance(node, dict) else {}

    @classmethod
    def _extract_hydration_rows(cls, html: str) -> List[dict]:
        """parse() 直接吃原始搜索页 HTML 时的兜底取行（fetch 走 _extract_search_node）。"""
        rows = cls._extract_search_node(html).get("searchResults")
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
        return slug or "job"


class AppleChinaAdapter(AppleAdapter):
    """Apple 在华岗位：不固定 location（全球混合搜索）→ parse 后只保留在华/remote 岗。

    Apple 的 location code 不公开稳定，因此不猜 code；改为按通用关键词全局搜索，再用
    keep_for_china_radar 裁到在华/不绑定海外的 remote 岗。jd_url 仍是 Apple 官方 details 页。
    """

    name = "apple_cn"
    SEARCH_LOCATION = ""     # 不限地点
    CHINA_ONLY = True        # 只保留在华/remote
