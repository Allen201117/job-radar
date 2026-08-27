"""Avature Careers 门户通用适配器（SearchJobs SSR，纯 httpx）。

各租户的详情 URL 形态并不一致，故一律从搜索卡片 ``h3 a[href]`` 原样取链接；
新增 Avature 租户只需登记其带 facet 的 SearchJobs URL。
"""
import html as html_lib
import json
import re
import time
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all


def html_unescape(markup: str) -> str:
    """卡片正文先解实体、剥标签，再压缩空白；空卡返回空字符串。"""
    return HTMLParser(html_lib.unescape(markup or "")).text(separator=" ", strip=True)


def _results_total(html: str) -> Optional[int]:
    """优先取 SSR 卡片 ``data-total``，再回退页面展示/analytics 的岗位总数。"""
    tree = HTMLParser(html or "")
    for card in tree.css("article.article--result"):
        try:
            return int(card.attrs.get("data-total") or "")
        except ValueError:
            continue
    match = re.search(
        r"\d[\d,]*\s*-\s*\d[\d,]*\s+of\s+([\d,]+)(\+?)\s+results",
        re.sub(r"\s+", " ", html or ""),
    )
    if not match or match.group(2) == "+":
        # 中文租户页面不渲染英文页脚，但 SSR analytics 变量同样由服务端给出总数。
        embedded = re.search(r'numberResults\s*:\s*"(\d+)"', html or "")
        return int(embedded.group(1)) if embedded else None
    return int(match.group(1).replace(",", ""))


class AvatureAdapter(BaseAdapter):
    name = "avature"
    MAX_PAGES = 200
    # None = 从第一页实际卡片数推断，不能把某租户的页长带给另一个租户。
    PAGE_SIZE: Optional[int] = None
    company_name = ""
    DETAIL_ORIGIN = ""
    # Avature source_url 的地区 facet 是服务端权威过滤：空地点只表示雇主未填城市，仍可入库。
    # Siemens 覆写为 True：它靠 search=China 全文收窄，地点未知无法证明是中国岗，必须丢弃。
    DROP_UNKNOWN_LOCATION = False

    def _client(self, **kwargs):
        return httpx.Client(**kwargs)

    def _search_terms(self) -> List[str]:
        return [""]

    def _base_url(self, source_url: str) -> str:
        return source_url

    @staticmethod
    def _with_page_params(source_url: str, offset: int, term: str) -> str:
        """保留原始 facet，只覆盖 offset/search（source_url 的服务端收窄不可丢）。"""
        parts = urlsplit(source_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params["offset"] = str(offset)
        if term:
            params["search"] = term
        else:
            params.pop("search", None)
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(params), parts.fragment))

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        # 欧莱雅 Avature 对项目默认 Bot UA 连续 offset 会回 403；普通 httpx 浏览器 UA
        # 实测可稳定返回 SSR 卡片。这里仍是纯 HTTP 请求，不涉及浏览器自动化。
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
            "Accept": "text/html,application/json,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        pages: List[dict] = []
        totals: List[Optional[int]] = []
        completes: List[bool] = []

        with self._client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def get_page(url: str):
                # Avature CDN 会偶发对连续 offset 返回临时 403；重试后继续，仍失败交 paginate_all
                # 标 partial，绝不把短缺误报为抓全。
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

            for term in self._search_terms():
                base = self._base_url(source_url)
                first_url = self._with_page_params(base, 0, term)
                first = get_page(first_url)
                first_cards = self._parse_cards(first.text, getattr(first, "url", first_url))
                page_size = self.PAGE_SIZE or len(first_cards)
                if page_size <= 0:
                    raise RuntimeError("avature: 首页未解析到岗位卡，无法推断翻页页长")
                cached = {0: first}

                def fetch_page(page: int, term=term, base=base) -> PageResult:
                    response = cached.pop(page, None)
                    if response is None:
                        response = get_page(self._with_page_params(base, page * page_size, term))
                    page_url = str(getattr(response, "url", self._with_page_params(base, page * page_size, term)))
                    jobs = self._parse_cards(response.text, page_url)
                    if jobs:
                        # parse 阶段也必须知道该页 base URL：有相对 href 的租户才能绝对化为真详情链接。
                        pages.append({"url": page_url, "html": response.text})
                    return PageResult(items=[job.jd_url for job in jobs], total=_results_total(response.text))

                _, total, complete = paginate_all(
                    fetch_page, page_size=page_size, first_page=0,
                    max_pages=self.MAX_PAGES, delay_seconds=1.0,
                    label=f"avature:{urlsplit(base).netloc}:{term or 'all'}",
                )
                totals.append(total)
                completes.append(complete)

        if not pages:
            raise RuntimeError("avature: 搜索页未解析到任何岗位卡")
        if all(total is not None for total in totals):
            # 多个全文 search term 的结果可重叠；分母相加会虚高。max 是不重复计数的保守上界。
            self.reported_total = max(int(total) for total in totals)
        self.fetch_complete = bool(completes) and all(completes)
        return json.dumps({"_pages": pages}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            envelope = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            envelope = None
        if isinstance(envelope, dict) and "_pages" in envelope:
            merged = {}
            for page in envelope.get("_pages") or []:
                # 新信封保留每页 URL；兼容旧调用方传来的纯 HTML 字符串数组。
                page_html = page.get("html", "") if isinstance(page, dict) else page
                page_url = page.get("url") if isinstance(page, dict) else None
                for job in self._parse_cards(page_html, page_url):
                    merged.setdefault(job.jd_url, job)
            return self._in_regions(list(merged.values()))
        return self._in_regions(self._parse_cards(html, None))

    def _in_regions(self, jobs: List[RawJob]) -> List[RawJob]:
        """facet 源只丢「能确证在所需地区之外」的岗；关键词源（Siemens）地点存疑一律丢。

        DROP_UNKNOWN_LOCATION=False（facet 源）时后置过滤从「白名单」降为「只拦确证的外国岗」：
        source_url 的服务端 facet 已经保证了地区，后置过滤只是防漏网，不该反过来当准入门槛。
        normalizer 的国家词表按城市名识别，认不出的一律返回 None——而 None 既可能是没收录的中国
        地级市，也可能是没收录的外国城市。对 facet 源把 None 当「不在中国」就是丢真岗：
        2026-08-27 live 实测欧莱雅中国 facet 共 347 个岗，其中 43 个（12%）因 乌鲁木齐/金华/
        常德/呼和浩特/宜昌/镇江/西宁/南充 等城市识别不出国家被丢掉。这也与写库侧自相矛盾——
        normalizer.derive_job_scope 对识别不出的地点判 domestic。

        Siemens 反之必须保持 True：它靠 search=China 全文关键词收窄，正文提到 China 的德国岗
        同样命中，地点存疑无法自证是中国岗，「存疑即丢」是它当初刻意加的正确保护。

        代价（诚实记录）：facet 源若登记时漏了地区 facet，外国岗中识别不出国家的那部分会漏进来。
        故新增 Avature 源必须把服务端地区 facet 带在 source_url 里。
        """
        regions = getattr(self, "regions", None)
        kept = []
        for job in jobs:
            if normalizer.location_in_source_regions(job.location, regions):
                kept.append(job)
                continue
            if self.DROP_UNKNOWN_LOCATION:
                continue
            if normalizer.derive_country_code(job.location) is None:
                kept.append(job)   # 识别不出国家 = 证据不足，不是证据相反
        return kept

    def _parse_cards(self, html: str, page_url=None) -> List[RawJob]:
        jobs: List[RawJob] = []
        tree = HTMLParser(html)
        base_url = str(page_url or "")
        for card in tree.css("article.article--result"):
            title_el = card.css_first("h3 a[href]")
            if not title_el:
                continue
            title = title_el.text(strip=True)
            href = title_el.attrs.get("href", "")
            jd_url = urljoin(base_url or self.DETAIL_ORIGIN, href)
            if not (title and "/JobDetail/" in jd_url):
                continue
            locations = []
            for selector in (".list-item-jobCity", ".list-item-jobState", ".list-item-jobCountry"):
                el = card.css_first(selector)
                value = el.text(strip=True) if el else ""
                if value and value not in locations:
                    locations.append(value)
            # 部分 Avature 租户（如欧莱雅）把地点放在标题下方的通用 subtitle，
            # 而非 Siemens 的 list-item-job* 字段；第一个 span 是地点，后续是发布日期。
            if not locations:
                subtitle = card.css_first(".article__header__text__subtitle span")
                value = subtitle.text(strip=True) if subtitle else ""
                if value:
                    locations.append(value)
            family = card.css_first(".list-item-family")
            content = card.css_first(".article__content")
            summary = re.sub(r"\s+", " ", html_unescape(content.html if content else "")).strip()
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=", ".join(locations) or None,
                job_type=family.text(strip=True) if family else None,
                summary=summary or None,
                jd_url=jd_url,
            ))
        return jobs
