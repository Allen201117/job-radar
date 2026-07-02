"""
Microsoft careers 适配器（Phenom pcsx 公开 search API，httpx 可直连，无需浏览器）。

MS careers 前端 jobs.careers.microsoft.com 由 Akamai 前置（httpx 直连返回空 body），
但其真实岗位接口在 apply.careers.microsoft.com/api/pcsx/search —— **该 host 无 Akamai，httpx 直连返回 JSON**。
pcsx 的 location 是**文本匹配**，单次只回少量（"China" 仅 16、各城市 8-11），故按「大中华区城市/地区」
列表逐个查 + 按 id 并集去重，覆盖在华全量。parse 再用 is_china_location 兜底（排除同名海外城市）。
jd_url = https://jobs.careers.microsoft.com/global/en/job/{displayJobId}（MS 公开逐岗页，已 live 验证 200）。
"""
import json
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob

_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_API = "https://apply.careers.microsoft.com/api/pcsx/search"
# 大中华区地点关键词（含主要研发城市）；pcsx location 文本匹配，逐个查后按 id 并集。
_CN_LOCS = ("China", "Hong Kong", "Shanghai", "Beijing", "Suzhou", "Shenzhen", "Guangzhou",
            "Chengdu", "Wuhan", "Xi'an", "Dalian", "Hangzhou", "Nanjing", "Tianjin")
_OVERSEAS_LOCS = {
    "US": ("United States", "Redmond", "Seattle", "New York", "San Francisco", "Austin", "Atlanta"),
    "SG": ("Singapore",),
    "Remote": ("Remote",),
}
_JD = "https://jobs.careers.microsoft.com/global/en/job/{id}"


def _locations_for_regions(regions):
    regions = normalizer.source_regions(regions)
    if regions == {"CN"}:
        return _CN_LOCS
    out = []
    if "CN" in regions:
        out.extend(_CN_LOCS)
    for region in sorted(regions):
        out.extend(_OVERSEAS_LOCS.get(region, ()))
    return tuple(dict.fromkeys(out)) or _CN_LOCS


class MicrosoftAdapter(BaseAdapter):
    name = "microsoft"
    max_pages = 10  # 每地点 num=20 → 最多 200/地点（count 通常很小，<20 即停）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}
        collected: dict = {}  # id -> position（按 id 并集去重）
        for loc in _locations_for_regions(getattr(self, "regions", None)):
            for page in range(self.max_pages):
                params = {"domain": "microsoft.com", "query": "", "location": loc,
                          "start": page * 20, "num": 20}
                try:
                    r = httpx.get(_API, params=params, headers=headers, timeout=self.timeout)
                    r.raise_for_status()
                    data = r.json().get("data", {}) or {}
                except Exception:
                    break
                positions = data.get("positions", []) or []
                if not positions:
                    break
                for p in positions:
                    pid = str(p.get("id") or p.get("displayJobId") or "").strip()
                    if pid and pid not in collected:
                        collected[pid] = p
                if len(positions) < 20:
                    break
        return json.dumps({"positions": list(collected.values())}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        out: List[RawJob] = []
        seen = set()
        for p in (data.get("positions", []) if isinstance(data, dict) else []):
            if not isinstance(p, dict):
                continue
            title = (p.get("name") or "").strip()
            jid = str(p.get("displayJobId") or p.get("id") or "").strip()
            if not title or not jid:
                continue
            locs = p.get("locations")
            loc = locs[0] if isinstance(locs, list) and locs and isinstance(locs[0], str) else None
            # pcsx location 是文本匹配，可能串入同名城市 → 按 source.regions 严格兜底
            if not normalizer.location_in_source_regions(loc, getattr(self, "regions", None)):
                continue
            jd = _JD.format(id=jid)
            if jd in seen:
                continue
            seen.add(jd)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=loc,
                job_type=None,
                summary=None,
                jd_url=jd,
                apply_url=jd,
                posted_at=None,
            ))
        return out
