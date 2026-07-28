import json
import re
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from selectolax.parser import HTMLParser

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all


def _results_total(html: str) -> Optional[int]:
    """搜索页页脚的「1 - 6 of N results」里的 N。不带筛选时是 "999+"（截断展示）→ 返回 None。"""
    m = re.search(r"\d[\d,]*\s*-\s*\d[\d,]*\s+of\s+([\d,]+)(\+?)\s+results",
                  re.sub(r"\s+", " ", html or ""))
    if not m or m.group(2) == "+":
        return None
    return int(m.group(1).replace(",", ""))


class SiemensAdapter(BaseAdapter):
    """
    Siemens Careers — jobs.siemens.com

    尝试 Siemens careers API + HTML 解析。
    """

    name = "siemens"
    SEARCH_URL = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs"

    # Avature 门户（SearchJobs / RegisterAgent / AIRecommendations 是它的招牌路由）：
    # 翻页参数是 `?offset=N`，**每页恒定 6 条**——recordsPerPage/limit/pageSize/rpp/perPage
    # 全部试过，一律仍返 6 条，页长改不动（2026-07-28 live 实测）。
    PAGE_SIZE = 6
    # 不带筛选时站点自报 "999+ results"，实测 offset=2000 仍有货、3000 才空 → 全量 2000+ 岗。
    # 本源 regions=['CN'] 只要中国岗，用站内 search 关键词收窄（search=China 只剩 170 条 ≈ 29 页），
    # 免得为了几十个中国岗去翻 300+ 页全球岗。
    MAX_PAGES = 60
    # regions → 站内搜索词。命中的仍可能是"正文提到 China"的非中国岗，
    # 故 parse 末尾还有 location_in_source_regions 兜底（CLAUDE.md 后置过滤原则）。
    _REGION_TERMS = {
        "CN": "China", "HK": "Hong Kong", "US": "United States",
        "SG": "Singapore", "Remote": "Remote",
    }

    def _search_terms(self) -> List[str]:
        regions = normalizer.source_regions(getattr(self, "regions", None))
        terms = [self._REGION_TERMS[r] for r in sorted(regions) if r in self._REGION_TERMS]
        return terms or [""]   # 未知 regions → 不加筛选，退回全量枚举

    def fetch(self, source_url: str) -> str:
        """按 regions 关键词逐页翻到底，返回各页 HTML 的信封。

        旧实现只 GET 一次搜索页 → 恒定 6 条（首页），而站点有 2000+ 岗：
        2026-07-28 实测库里 481 个 active 里挑出的老岗 509645/510192 **仍是在招的**
        （详情页 200、JD 完整、Posted since 14-Jun），只是永远进不了这 6 条 → 永不刷新。
        """
        base = self.SEARCH_URL if "careers/search" in source_url.lower() else source_url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,*/*",
        }
        pages: List[str] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for term in self._search_terms():
                def fetch_page(page: int, term=term) -> PageResult:
                    params = {"offset": page * self.PAGE_SIZE}
                    if term:
                        params["search"] = term
                    resp = client.get(f"{base}?{urlencode(params)}")
                    resp.raise_for_status()
                    ids = set(re.findall(r"/externaljobs/JobDetail/(\d+)", resp.text))
                    if ids:
                        pages.append(resp.text)
                    return PageResult(items=sorted(ids), total=_results_total(resp.text))

                paginate_all(
                    fetch_page,
                    page_size=self.PAGE_SIZE,
                    first_page=0,          # offset 型：page_index 从 0 起
                    max_pages=self.MAX_PAGES,
                    delay_seconds=0.2,
                    label=f"siemens:{term or 'all'}",
                )
        if not pages:
            raise RuntimeError("siemens: 搜索页没解析到任何岗位卡")
        return json.dumps({"_pages": pages})

    def parse(self, html: str) -> List[RawJob]:
        """解析 fetch() 的多页信封，或单张搜索页 HTML。

        末尾统一过 location_in_source_regions：站内 search 关键词是全文匹配（正文提到 "China"
        的德国岗也会命中），不兜这一道，regions=['CN'] 的源会被全球岗灌满——2026-07-28 实测
        库里 484 个 Siemens active 岗有 426 个地点没解析出国家、默认落进 domestic（丹麦/印度/
        危地马拉岗混进国内看板）。这也是 CLAUDE.md 的「后置过滤是所有源通用的正确性兜底」。
        """
        try:
            envelope = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            envelope = None
        if isinstance(envelope, dict) and "_pages" in envelope:
            merged: dict = {}
            for page in envelope.get("_pages") or []:
                for job in self._parse_cards(page):
                    merged.setdefault(job.jd_url, job)   # 跨页/跨关键词按 jd_url 去重
            return self._in_regions(list(merged.values()))
        return self._in_regions(self._parse_legacy(html))

    def _in_regions(self, jobs: List[RawJob]) -> List[RawJob]:
        return [j for j in jobs
                if normalizer.location_in_source_regions(j.location, getattr(self, "regions", None))]

    def _parse_legacy(self, html: str) -> List[RawJob]:
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
        jobs.extend(self._parse_cards(html))
        return jobs

    def _parse_cards(self, html: str) -> List[RawJob]:
        """单张搜索页 HTML → 岗位卡。多页信封与单页兜底共用这一份。"""
        jobs: List[RawJob] = []
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
