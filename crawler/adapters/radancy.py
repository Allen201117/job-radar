"""Radancy / TalentBrew 招聘门户适配器（纯 httpx）：站点地图 → 按地区粗筛 → 逐岗详情页。

欧莱雅 2026-10-05 前后从 Avature 迁到 TalentBrew，旧 Avature 地址一律 301 到官网首页。

🚫 **搜索页不能抓**：TalentBrew 站点的 robots.txt 一律 ``Disallow: /search-jobs``（欧莱雅还禁了
``/location/`` ``/category/`` ``/employment/``）。本 adapter 第一版走的就是搜索页，2026-10-07 上线首轮
被 run.py 的 robots 门挡下记 skipped。站点**允许**的是 robots 里自己声明的 sitemap.xml 和 ``/<lang>/job/``
详情页，所以 source_url 填站点地图（例 ``https://careers.loreal.com/en/sitemap.xml``）。

站点地图只有链接没有地点，链接形如 ``/en/job/<城市>/<标题>/<org>/<岗位 id>``，于是分两步：
  1. 粗筛（零请求）：链接里的城市能认出国家且在本源 regions 里 → 候选；城市认不出、但本源要 CN 且
     标题段含汉字 → 也是候选（「昌吉」「承德」这类不在词表里的中国城市靠它兜住）。
  2. 逐个打开候选的详情页，读 ``application/ld+json`` 的 JobPosting：标题 / 地点 / 正文都取这里，
     **地点必须过 regions 才收**——粗筛只决定开哪些页，不决定收哪些岗（台湾岗的标题也是汉字）。
  2026-10-07 全集对拍（1,694 个岗逐个开详情页取 addressCountry 作标准答案）：中国 326，粗筛候选 326，
  漏 0、多 0；每轮约 326 次详情请求，换来的是真标题和完整正文（不再是无正文的薄卡）。
  ⚠️ 已知盲区：regions 不含 CN 的源，城市认不出的岗一律不开（否则欧莱雅每轮要开 1,100+ 个页）。

站点地图不给分地区总数 → reported_total 记 None（诚实盲区）；有候选的详情没取到 / 候选撞上限时
fetch_complete=False。详情 404 = 岗位在两次请求之间下线，跳过，不算没抓全。
"""
import html as html_lib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import unquote, urlsplit

import httpx
from html_dom import HTMLParser

import geo
import normalizer
from .base import DEFAULT_LIST_CAP, BaseAdapter, RawJob, resolve_list_cap

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_CJK_RE = re.compile(r"[一-鿿]")


class _Gone(Exception):
    """详情页 404：岗位在读站点地图之后下线了。"""


def job_url_parts(url: str):
    """``/<lang>/job/<城市>/<标题>/<org>/<id>`` → (城市, 标题)，已 URL 解码；不是岗位链接返回 None。"""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    if len(segments) < 6 or segments[1] != "job":
        return None
    return unquote(segments[2]), unquote(segments[3])


def sitemap_job_urls(xml: str) -> List[str]:
    seen, urls = set(), []
    for loc in _LOC_RE.findall(xml or ""):
        url = html_lib.unescape(loc)
        if job_url_parts(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def is_candidate(url: str, regions) -> bool:
    """粗筛：只决定开不开详情页；收不收以详情页的地点为准。"""
    parts = job_url_parts(url)
    if not parts:
        return False
    city, title = parts
    wanted = normalizer.source_regions(regions)
    code = geo.derive_country_code(city.replace("-", " "))
    if code is not None:
        return code in wanted
    return "CN" in wanted and bool(_CJK_RE.search(title))


def parse_detail(html: str) -> Optional[dict]:
    """详情页 ld+json 的 JobPosting → {title, location, summary, posted_at, country_code}；没有返回 None。"""
    for block in _LD_RE.findall(html or ""):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not (isinstance(data, dict) and data.get("@type") == "JobPosting" and data.get("title")):
            continue
        places = data.get("jobLocation") or []
        if isinstance(places, dict):
            places = [places]
        locations, countries = [], []
        for place in places:
            address = (place or {}).get("address") or {}
            parts = []
            for key in ("addressLocality", "addressRegion", "addressCountry"):
                value = str(address.get(key) or "").strip()
                if value and value not in parts:
                    parts.append(value)
            if parts:
                locations.append(", ".join(parts))
            if address.get("addressCountry"):
                countries.append(str(address["addressCountry"]).strip())
        description = data.get("description") or ""
        summary = HTMLParser(html_lib.unescape(str(description))).text(separator=" ", strip=True)
        country_code = geo.derive_country_code(countries[0]) if len(set(countries)) == 1 else None
        return {
            "title": html_lib.unescape(str(data["title"])).strip(),
            "location": " / ".join(locations) or None,
            "summary": re.sub(r"\s+", " ", summary).strip() or None,
            "posted_at": data.get("datePosted") or None,
            "country_code": country_code,
        }
    return None


class RadancyAdapter(BaseAdapter):
    name = "radancy"
    DETAIL_WORKERS = 2

    def _client(self, **kwargs):
        return httpx.Client(**kwargs)

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        regions = getattr(self, "regions", None)
        headers = {"User-Agent": _UA, "Accept": "text/html,application/xml,*/*",
                   "Accept-Language": "en,zh-CN;q=0.8"}
        with self._client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def get(url: str):
                last = None
                for attempt in range(3):
                    response = client.get(url)
                    status = getattr(response, "status_code", 200)
                    if status == 404:
                        raise _Gone(url)
                    if status not in (403, 429) and status < 500:
                        response.raise_for_status()
                        return response
                    last = response
                    if attempt < 2:
                        time.sleep(1.0 * (attempt + 1))
                last.raise_for_status()

            urls = sitemap_job_urls(get(source_url).text)
            if not urls:
                raise RuntimeError("radancy: 站点地图里没有任何岗位链接（地址可能已失效）")
            candidates = [u for u in urls if is_candidate(u, regions)]
            cap = resolve_list_cap(DEFAULT_LIST_CAP)
            capped = len(candidates) > cap
            candidates = candidates[:cap]

            def detail(url: str):
                try:
                    return url, parse_detail(get(url).text), None
                except _Gone:
                    return url, None, "gone"
                except Exception as exc:  # noqa: BLE001 — 单岗失败不拖垮整源，记入没抓全
                    return url, None, f"{type(exc).__name__}"

            with ThreadPoolExecutor(self.DETAIL_WORKERS) as pool:
                results = list(pool.map(detail, candidates))

        jobs, failed = [], 0
        for url, info, error in results:
            if error == "gone":
                continue
            if error or info is None:
                failed += 1
                continue
            jobs.append({"jd_url": url, **info})
        if candidates and not jobs and failed:
            raise RuntimeError(f"radancy: {len(candidates)} 个候选岗的详情页一个都没取到")
        if failed:
            print(f"[radancy] {failed}/{len(candidates)} 个候选岗详情没取到，本轮记为没抓全")
        self.fetch_complete = not capped and failed == 0
        return json.dumps({"_jobs": jobs}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            envelope = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        regions = getattr(self, "regions", None)
        jobs = []
        for item in (envelope or {}).get("_jobs") or []:
            # 粗筛只决定开哪些页；台湾岗标题也是汉字，地点不在 regions 里的一律不收。
            if not normalizer.location_in_source_regions(item.get("location"), regions):
                continue
            jobs.append(RawJob(
                company="",   # 由 run.py 按 source 的公司名写入
                title=item["title"],
                location=item.get("location"),
                summary=item.get("summary"),
                posted_at=item.get("posted_at"),
                country_code=item.get("country_code"),
                jd_url=item["jd_url"],
            ))
        return jobs
