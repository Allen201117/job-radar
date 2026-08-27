"""Gllue 企业招聘门户通用适配器（Next.js SSR，纯 httpx）。"""
import html as html_lib
import json
import re
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", HTMLParser(html_lib.unescape(markup or "")).text()).strip()


class GllueAdapter(BaseAdapter):
    name = "gllue"
    PAGE_SIZE = 10
    MAX_PAGES = 200
    # 龙湖当前 307 岗，详情约 0.5 秒/岗；重档全量富化约 2.5 分钟，换取必投公司不再有薄卡。
    # 快档 daily 通过 CRAWL_DETAIL_CAP=0 跳过，故不拖慢日常列表抓取。
    _DETAIL_CAP = 400

    @staticmethod
    def _page_url(source_url: str, page: int) -> str:
        parts = urlsplit(source_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/jobs",
                           urlencode(params), parts.fragment))

    @staticmethod
    def _reported_total(markup: str) -> Optional[int]:
        match = re.search(r"已为您推荐\s*</span>\s*<span[^>]*>\s*(\d+)\s*</span>\s*个职位", markup)
        return int(match.group(1)) if match else None

    @staticmethod
    def _list_rows(markup: str, page_url: str) -> List[dict]:
        """从 SSR 卡片取岗位链接和可见字段；链接来自卡片，不拼猜 slug。"""
        rows = []
        for match in re.finditer(r'<a\b[^>]*href="(\./jobs/[^"]+)"[^>]*>(.*?)</a>', markup, re.S):
            href, card = match.groups()
            title_match = re.search(r"<h3\b[^>]*>(.*?)</h3>", card, re.S)
            if not title_match:
                continue
            title = _text(title_match.group(1))
            location_match = re.search(
                r"lucide-map-pin.*?</svg>\s*<span[^>]*title=\"([^\"]+)\"", card, re.S,
            )
            if not (title and href):
                continue
            rows.append({
                "title": title,
                "location": html_lib.unescape(location_match.group(1)).strip() if location_match else None,
                "jd_url": urljoin(page_url, href),
            })
        return rows

    @staticmethod
    def _detail_summary(markup: str) -> Optional[str]:
        # Next.js SSR 页的内联 SVG 会让 HTMLParser 在少数页错误闭合树；正文容器有稳定 class，
        # 因此用窄正则直接取紧随「职位描述」标题的 div（内容是纯文本，实测无嵌套标签）。
        match = re.search(
            r"<h4\b[^>]*>\s*职位描述\s*</h4>\s*<div\b[^>]*"
            r"class=\"[^\"]*whitespace-pre-wrap[^\"]*\"[^>]*>(.*?)</div>",
            markup or "", re.S,
        )
        return _text(match.group(1)) or None if match else None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/json,*/*"}
        pages = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            first_url = self._page_url(source_url, 1)
            first = client.get(first_url)
            first.raise_for_status()
            cached = {1: first}

            def fetch_page(page: int) -> PageResult:
                response = cached.pop(page, None)
                if response is None:
                    response = client.get(self._page_url(source_url, page))
                    response.raise_for_status()
                rows = self._list_rows(response.text, str(response.url))
                if rows:
                    pages.extend(rows)
                return PageResult(items=rows, total=self._reported_total(response.text))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, delay_seconds=0.1,
                label=f"gllue:{urlsplit(source_url).netloc}",
            )
            self.reported_total = total
            self.fetch_complete = complete

            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                try:
                    detail = client.get(row["jd_url"])
                    if detail.status_code < 300:
                        row["summary"] = self._detail_summary(detail.text)
                except httpx.HTTPError:
                    continue
        if not rows:
            raise RuntimeError("gllue: 列表页未解析到岗位卡")
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            title = str((row or {}).get("title") or "").strip()
            url = str((row or {}).get("jd_url") or "").strip()
            location = (row or {}).get("location")
            if not (title and url.startswith("http") and "/jobs/" in url):
                continue
            jobs.append(RawJob(company="", title=title, location=location,
                               summary=(row or {}).get("summary") or None, jd_url=url))
        return jobs
