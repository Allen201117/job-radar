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


def _parse_list_rows(page_html: str):
    """列表页 → (服务端占了几个 startrow 位置, 岗位行 [{title, href, location}])。

    CSB 有两套列表模板，同一个 adapter 两套都认：
    - 表格版：tr.data-row / a.jobTitle-link / span.jobLocation（ZF / Adidas / DSV 等绝大多数租户）
    - 卡片版：li.job-tile / a.jobTitle-link / 「…-desktop-section-location-value」
      ⚠️ 2026-09-23 实测 Ferrari 已切到卡片版：页面照常 200、13 个岗都在，表格版选择器一行都匹配不到
      → 0 岗照样记 success，连续 37 轮「报成功却零产出」。同一张卡里桌面/平板/手机三份重复标记，取第一份。
    只在一行表格都没有时才按卡片版解析，表格版租户的行为一字不变。"""
    tree = HTMLParser(page_html)
    items = []
    raw_rows = tree.css("tr.data-row")
    if raw_rows:
        for row in raw_rows:
            a = row.css_first("a.jobTitle-link") or row.css_first("a[href*='/job/']")
            if not a:
                continue
            href = (a.attrs.get("href") or "").strip()
            title = a.text(strip=True)
            loc = row.css_first("span.jobLocation")
            location = loc.text(strip=True) if loc else None
            if title and href:
                items.append({"title": title, "href": href, "location": location})
        return len(raw_rows), items
    tiles = tree.css("li.job-tile")
    for tile in tiles:
        a = tile.css_first("a.jobTitle-link") or tile.css_first("a[href*='/job/']")
        if not a:
            continue
        href = (a.attrs.get("href") or tile.attributes.get("data-url") or "").strip()
        title = a.text(strip=True)
        loc = tile.css_first("[id$='-desktop-section-location-value']") \
            or tile.css_first(".section-field.location div")
        location = loc.text(strip=True) if loc else None
        if title and href:
            items.append({"title": title, "href": href, "location": location or None})
    return len(tiles), items


class SuccessFactorsAdapter(BaseAdapter):
    name = "successfactors"
    # 5000 岗安全上限。⚠️ 不能按 `_PAGE_SIZE(=25)` 反推页数：多个租户（如 DSV）SSR 表格
    # 实测**每次响应只回 10 行**，与文档声称/常见的 25/页不符（live 2026-09-19 逐页验证，
    # startrow=0/10/20…每步 10 行、行行不重复；旧代码按 startrow=page*25 请求，等于每次
    # 只吃到自己请求窗口的前 10 行、白白跳过后 15 行，DSV 2063 岗常年只收 600 左右）。
    # 故改为按**实际收到的行数**累进 startrow（见 fetch 内的 offset 状态），
    # 这个安全上限按「真实最小页大小 10」换算：500 次请求覆盖 5000 岗。
    max_pages = 500

    def should_skip(self, source_url: str):
        return None  # SSR 公开页，GET 暴露真实错误即可

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        headers = {"User-Agent": self.user_agent, "Accept": "text/html"}
        # ⚠️ 不能用 `page * _PAGE_SIZE` 算 startrow：不同租户实际每页行数不一致（DSV 实测 10，
        # 不是请求参数暗示的 25），startrow 必须紧跟着「上一页真实收到几行」累进，否则会像
        # 固定步长 25 那样把每页多出的行悄悄跳过。用可变闭包状态代替 paginate_all 的 page 序号。
        offset_state = {"next": 0}

        def fetch_page(_page: int) -> PageResult:
            startrow = offset_state["next"]
            r = httpx.get(f"{origin}/search/",
                          params={"q": "", "sortColumn": "referencedate", "sortDirection": "desc",
                                  "startrow": startrow},
                          headers=headers, timeout=self.timeout, follow_redirects=True)
            r.raise_for_status()
            m = _TOTAL_RE.search(r.text)
            total = int(m.group(1)) if m else None
            raw_count, items = _parse_list_rows(r.text)
            # 下一次请求的 startrow = 这次**原始行数**（不是过滤后的 items 数——个别装饰行没有
            # a 标签会被 items 滤掉，但它们仍占了服务端的一个 startrow 位置，用 items 数累进
            # 会导致下次请求起点往回缩、重复抓到同一批行）。一行都没收到时退回 _PAGE_SIZE 兜底防死循环。
            offset_state["next"] = startrow + (raw_count or _PAGE_SIZE)
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
