"""
通用 SAP SuccessFactors「Career Site Builder」适配器（SSR HTML，纯 httpx 零浏览器）。

欧洲/亚洲系跨国大厂（Ferrari / Adidas / ZF / DHL / Kuehne+Nagel / Vestas…）大量用 SF CSB 托管
careers 站（jobs.{company}.com / careers.{company}.com），结构高度统一（2026-07-16 live 验证 ZF/Ferrari/Adidas）：
- 列表：GET {origin}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow={n}
  → SSR 表格 tr.data-row，a.jobTitle-link（标题+相对详情链接）、span.jobLocation（地点文本）；
  总数在 "Results 1 – 25 of <b>N</b>"（25/页翻到底）。
- 详情：{origin}/job/{slug}/{id}/ SSR，多数租户正文在 class 含 jobdescription 的 span
  （个别租户如 ZF 详情不内嵌正文 → 该租户岗位入库为薄卡，不算 healthy，诚实呈现）。
- ⚠️ 详情页 HTML 会让 selectolax 解析成空 DOM（live 踩坑：ZF/Ferrari 详情 div 数=0）→
  详情统一用正则抽取；列表页 selectolax 正常。

source_url 填该公司 SF 站任意页（用 origin），如 https://jobs.ferrari.com/search/。
"""
import html as html_lib
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap

_PAGE_SIZE = 25
_TOTAL_RE = re.compile(r"of\s*<b>\s*(\d+)\s*</b>")
_JD_SPAN_RE = re.compile(
    r'<span[^>]*class="[^"]*jobdescription[^"]*"[^>]*>(.*?)</span>\s*(?:</div|<div|<footer|<span[^>]*class="[^"]*job)',
    re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


class SuccessFactorsAdapter(BaseAdapter):
    name = "successfactors"
    max_pages = 200  # 25/页 → 5000 岗安全上限

    def should_skip(self, source_url: str):
        return None  # SSR 公开页，GET 暴露真实错误即可

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        headers = {"User-Agent": self.user_agent, "Accept": "text/html"}

        def fetch_page(page: int) -> PageResult:
            r = httpx.get(f"{origin}/search/",
                          params={"q": "", "sortColumn": "referencedate", "sortDirection": "desc",
                                  "startrow": page * _PAGE_SIZE},
                          headers=headers, timeout=self.timeout, follow_redirects=True)
            r.raise_for_status()
            m = _TOTAL_RE.search(r.text)
            total = int(m.group(1)) if m else None
            items = []
            tree = HTMLParser(r.text)
            for row in tree.css("tr.data-row"):
                a = row.css_first("a.jobTitle-link") or row.css_first("a[href*='/job/']")
                if not a:
                    continue
                href = (a.attrs.get("href") or "").strip()
                title = a.text(strip=True)
                loc = row.css_first("span.jobLocation")
                location = loc.text(strip=True) if loc else None
                if title and href:
                    items.append({"title": title, "href": href, "location": location})
            return PageResult(items=items, total=total)

        rows, total, complete = paginate_all(
            fetch_page, page_size=_PAGE_SIZE, first_page=0,
            max_pages=self.max_pages, label=f"successfactors:{origin}")
        self.reported_total = total
        self.fetch_complete = complete
        # 同 jd_url 只保留首个（列表偶有多语言重复行）
        seen, deduped = set(), []
        for row in rows:
            key = row["href"]
            if key in seen:
                continue
            seen.add(key)
            row["url"] = key if key.startswith("http") else origin + key
            deduped.append(row)
        self._enrich_descriptions(deduped, headers)
        return json.dumps({"jobs": deduped}, ensure_ascii=False)

    _DETAIL_CAP = 200  # 逐岗 detail 补正文上限（SSR 单页 ~70KB，防夜间全量被拖垮）

    def _enrich_descriptions(self, rows: List[dict], headers: dict):
        """仅对将保留的岗（regions 过滤后）抓详情正则抽 jobdescription；失败/无正文静默（薄卡入库）。"""
        n = 0
        for row in rows:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            if not normalizer.location_in_source_regions(row.get("location"), getattr(self, "regions", None)):
                continue
            try:
                r = httpx.get(row["url"], headers=headers, timeout=self.timeout, follow_redirects=True)
                if r.status_code >= 300:
                    continue
                m = _JD_SPAN_RE.search(r.text)
                if m:
                    body = _strip_tags(m.group(1))
                    if body:
                        row["_jd"] = body
                n += 1
            except Exception:
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        out: List[RawJob] = []
        for row in (data.get("jobs") if isinstance(data, dict) else None) or []:
            if not isinstance(row, dict):
                continue
            title = (row.get("title") or "").strip()
            url = (row.get("url") or "").strip()
            if not title or not url:
                continue
            location = (row.get("location") or "").strip() or None
            if not normalizer.location_in_source_regions(location, getattr(self, "regions", None)):
                continue
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=None,
                summary=row.get("_jd"),
                jd_url=url,
                apply_url=url,
                posted_at=None,  # 列表无稳定日期列；不猜
            ))
        return out
