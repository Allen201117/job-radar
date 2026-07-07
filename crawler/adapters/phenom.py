"""
Phenom People 通用适配器（公开 /api/jobs，无需鉴权）。

source_url = https://{host}/api/jobs   （host 形如 careers.amd.com；公司 careers 站跑在 Phenom 平台上）
大量外企巨头的「自建门户」其实是 Phenom（AMD / L'Oréal / 多家 Fortune 500），
workday/oracle/greenhouse/eightfold 都抓不到。一套适配覆盖任意 Phenom 租户——新增公司只加一行 sources。
服务「在华外企」：?location=China / Hong Kong 服务端收窄到在华，parse 再用 is_china_location 兜底。
jd_url = https://{host}/jobs/{slug}（Phenom 托管的公开逐岗页，已 live 验证含岗位标题；
注意 data.apply_url 多指向 icims 等登录页，违反 jd_url 质量门，不可用）。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import BaseAdapter, RawJob


def _job_summary(d: dict) -> Optional[str]:
    """从 Phenom /api/jobs 列表项的 data 直接组装 JD 正文（已 live 验证含完整 description ~4k 字
    + responsibilities + qualifications）。无需逐岗 detail（Phenom 逐岗页是 SPA 壳、httpx 拿不到正文），
    列表自带正文即够 ≥60 字门。HTML 由 run.py 的 normalizer.clean_summary 统一清洗+截断。"""
    parts = [d.get("description"), d.get("responsibilities"), d.get("qualifications")]
    text = "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return text or None


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Phenom 站点常由 Akamai/CDN 前置，用常见浏览器 UA 更稳。
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class PhenomAdapter(BaseAdapter):
    name = "phenom"
    max_pages = 20                              # 100/页 → 单地点最多 2000 岗
    china_locations = ("China", "Hong Kong")    # 服务端按地点收窄到大中华区
    overseas_locations = {
        "US": ("United States",),
        "SG": ("Singapore",),
        "Remote": ("Remote",),
    }

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        p = urlparse(source_url)
        host = f"{p.scheme}://{p.netloc}"
        api = source_url.split("?")[0]
        headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}
        collected: List[dict] = []
        seen = set()
        locations = self._locations_for_regions()
        location_totals: List[int] = []
        for loc in locations:
            loc_total: Optional[int] = None
            for page in range(self.max_pages):
                params = {"location": loc, "limit": 100, "offset": page * 100}
                r = httpx.get(api, params=params, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                body = r.json()
                if loc_total is None:
                    loc_total = _int_or_none(body.get("totalCount"))
                    if loc_total is None:
                        loc_total = _int_or_none(body.get("count"))
                jobs = body.get("jobs", []) or []
                if not jobs:
                    break
                for j in jobs:
                    data = j.get("data", {}) if isinstance(j, dict) else {}
                    slug = str(data.get("slug") or data.get("req_id") or "").strip()
                    if slug and slug not in seen:
                        seen.add(slug)
                        collected.append(data)
                total = loc_total or 0
                if len(jobs) < 100 or (page + 1) * 100 >= total:
                    break
            if loc_total is not None:
                location_totals.append(loc_total)
        if len(location_totals) == len(locations):
            self.reported_total = sum(location_totals)
        self.fetch_complete = (
            self.reported_total is not None and len(collected) >= self.reported_total
        )
        return json.dumps({"_host": host, "jobs": collected}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        host = data.get("_host", "")
        out: List[RawJob] = []
        seen_urls = set()
        for d in data.get("jobs", []):
            if not isinstance(d, dict):
                continue
            title = (d.get("title") or "").strip()
            slug = str(d.get("slug") or d.get("req_id") or "").strip()
            if not title or not slug:
                continue
            loc = ", ".join(x for x in (d.get("city"), d.get("state"), d.get("country")) if x) \
                or (d.get("location_name") or None)
            # 服务端已按地点收窄，这里按 regions 兜底（排除 location 模糊召回的串入岗）
            if not normalizer.location_in_source_regions(loc, getattr(self, "regions", None)):
                continue
            jd_url = f"{host}/jobs/{slug}"
            if jd_url in seen_urls:
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=loc,
                job_type=None,  # 由 normalizer 从标题抽取社招/校招/实习
                summary=_job_summary(d),  # 列表自带完整 JD 正文 → 直接入库，治 0% 覆盖薄卡
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(d.get("posted_date") or None),
            ))
        return out

    def _locations_for_regions(self):
        regions = normalizer.source_regions(getattr(self, "regions", None))
        if regions == {"CN"}:
            return self.china_locations
        out = []
        if "CN" in regions:
            out.extend(self.china_locations)
        for region in sorted(regions):
            out.extend(self.overseas_locations.get(region, ()))
        return tuple(dict.fromkeys(out)) or self.china_locations
