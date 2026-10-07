"""Radancy / TalentBrew 招聘门户通用适配器（SSR 搜索页，纯 httpx）。

欧莱雅 2026-10-05 前后从 Avature 迁到 TalentBrew：旧 Avature 地址 301 到首页，
``avature`` 适配器报「首页未解析到岗位卡」。TalentBrew 的搜索页本身就是 SSR：
``<section id="search-results" data-total-results data-total-pages data-records-per-page>``
+ ``li.search-results-list__item > a.search-results-list__job-link[href=/en/job/...]``，
翻页就是同一路径加 ``?p=N``。

source_url 必须是站点自己渲染的「按地区」搜索页（如中国国家级 location 路径
``/en/search-jobs/China/3456/2/1814991/35/105/50/2``），服务端已按地区收窄；
适配器只额外拦「能确证在所需地区之外」的岗（同 avature facet 源的口径）。
"""
import json
import time
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from html_dom import HTMLParser

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def _int_attr(node, name: str) -> Optional[int]:
    try:
        return int(node.attrs.get(name) or "")
    except (TypeError, ValueError):
        return None


def _results_meta(html: str):
    """(总岗位数, 总页数, 每页条数)；页面没有 search-results 容器时全为 None。"""
    section = HTMLParser(html or "").css_first("section#search-results")
    if section is None:
        return None, None, None
    total = _int_attr(section, "data-total-job-results")
    if total is None:
        total = _int_attr(section, "data-total-results")
    return total, _int_attr(section, "data-total-pages"), _int_attr(section, "data-records-per-page")


class RadancyAdapter(BaseAdapter):
    name = "radancy"
    MAX_PAGES = 200

    def _client(self, **kwargs):
        return httpx.Client(**kwargs)

    @staticmethod
    def _page_url(source_url: str, page: int) -> str:
        parts = urlsplit(source_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params["p"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(params), parts.fragment))

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": _UA, "Accept": "text/html,*/*", "Accept-Language": "en,zh-CN;q=0.8"}
        pages: List[dict] = []

        with self._client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def get_page(url: str):
                last = None
                for attempt in range(3):
                    response = client.get(url)
                    status = getattr(response, "status_code", 200)
                    if status not in (403, 429) and status < 500:
                        response.raise_for_status()
                        return response
                    last = response
                    if attempt < 2:
                        time.sleep(1.0 * (attempt + 1))
                last.raise_for_status()

            first_url = self._page_url(source_url, 1)
            first = get_page(first_url)
            first_jobs = self._parse_cards(first.text, str(getattr(first, "url", first_url)))
            if not first_jobs:
                # 旧地址被 301 到首页时就会走到这里：必须记 failed，不许安静返 0 条。
                raise RuntimeError("radancy: 搜索页未解析到岗位卡（地址可能已失效或被重定向到首页）")
            _, _, per_page = _results_meta(first.text)
            page_size = per_page or len(first_jobs)
            cached = {1: first}

            def fetch_page(page: int) -> PageResult:
                response = cached.pop(page, None)
                url = self._page_url(source_url, page)
                if response is None:
                    response = get_page(url)
                page_url = str(getattr(response, "url", url))
                jobs = self._parse_cards(response.text, page_url)
                if jobs:
                    pages.append({"url": page_url, "html": response.text})
                total, total_pages, _ = _results_meta(response.text)
                return PageResult(items=[j.jd_url for j in jobs], total=total, total_pages=total_pages)

            _, total, complete = paginate_all(
                fetch_page, page_size=page_size, first_page=1,
                max_pages=self.MAX_PAGES, delay_seconds=0.5,
                label=f"radancy:{urlsplit(source_url).netloc}",
            )

        self.reported_total = total
        self.fetch_complete = bool(complete)
        return json.dumps({"_pages": pages}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            envelope = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            envelope = None
        if isinstance(envelope, dict) and "_pages" in envelope:
            merged = {}
            for page in envelope.get("_pages") or []:
                for job in self._parse_cards(page.get("html", ""), page.get("url")):
                    merged.setdefault(job.jd_url, job)
            return self._in_regions(list(merged.values()))
        return self._in_regions(self._parse_cards(html, None))

    def _in_regions(self, jobs: List[RawJob]) -> List[RawJob]:
        """只丢「能确证在所需地区之外」的岗；识别不出国家 = 证据不足，保留（服务端地区过滤是权威）。"""
        regions = getattr(self, "regions", None)
        kept = []
        for job in jobs:
            if (normalizer.location_in_source_regions(job.location, regions)
                    or normalizer.derive_country_code(job.location) is None):
                kept.append(job)
        return kept

    @staticmethod
    def _parse_cards(html: str, page_url=None) -> List[RawJob]:
        jobs: List[RawJob] = []
        base = str(page_url or "")
        for link in HTMLParser(html or "").css("a.search-results-list__job-link[href]"):
            href = link.attrs.get("href", "")
            if "/job/" not in href:
                continue
            title_el = link.css_first(".search-results-list__job-title")
            loc_el = link.css_first(".job-location")
            title = (title_el.text(strip=True) if title_el else "")
            if not title:
                continue
            jobs.append(RawJob(
                company="",   # 由 run.py 按 source 的公司名写入
                title=title,
                location=(loc_el.text(strip=True) if loc_el else "") or None,
                jd_url=urljoin(base or "https://localhost/", href),
            ))
        return jobs
