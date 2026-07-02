"""
Google careers 适配器（Tier-2 无头浏览器 DOM 抓取）。

Google careers 结果页（www.google.com/about/careers/applications/jobs/results）无公开 JSON 接口、
岗位卡服务端渲染进 DOM（XHR/api 抓不到）。用真实无头浏览器加载**按 China 过滤**的公开结果页 →
读岗位卡 a[href*='jobs/results/'] + 卡内 h3 标题 + 卡文本里的地点 → RawJob。低频翻页（?page=N）。
不破解、只读公开渲染页。Google 不拦无头浏览器（实测页面正常渲染）。
jd_url = https://www.google.com/about/careers/applications/{href去掉query}。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlencode

import normalizer
from .base import BaseAdapter, RawJob

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_APP_BASE = "https://www.google.com/about/careers/applications/"
_RESULTS = _APP_BASE + "jobs/results/?location=China&page={pg}"
_OVERSEAS_LOCATIONS = {
    "US": ("United States",),
    "SG": ("Singapore",),
    "Remote": ("Remote",),
}
# 读每张岗位卡：链接 href + 卡内标题(h3/h2) + 卡整段文本(含 "place | 城市, China")。
_EXTRACT_JS = (
    "els=>els.map(e=>{const li=e.closest('li')||e.parentElement;"
    "const h=li&&li.querySelector('h3,h2');"
    "return {href:e.getAttribute('href'),"
    "title:(h?h.innerText:'').trim(),"
    "text:(li?li.innerText:'').replace(/\\s+/g,' ').trim()}})"
)


def _locations_for_regions(regions):
    regions = normalizer.source_regions(regions)
    if regions == {"CN"}:
        return ("China",)
    out = []
    if "CN" in regions:
        out.append("China")
    for region in sorted(regions):
        out.extend(_OVERSEAS_LOCATIONS.get(region, ()))
    return tuple(dict.fromkeys(out)) or ("China",)


def _results_url(location: str, page: int) -> str:
    if location == "China":
        return _RESULTS.format(pg=page)
    return _APP_BASE + "jobs/results/?" + urlencode({"location": location, "page": page})


class GoogleAdapter(BaseAdapter):
    name = "google"
    max_pages = 10  # ~20/页 → 最多约 200 在华岗（打通足够，空页/重复页即停）

    def should_skip(self, source_url: str):
        return None  # SPA/DOM 渲染，无 HEAD 预检意义

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        cards: List[dict] = []
        seen_pages = set()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA, locale="en-US",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            for loc in _locations_for_regions(getattr(self, "regions", None)):
                for pg in range(1, self.max_pages + 1):
                    try:
                        # 不用 networkidle：google.com 遥测/分析让网络永不空闲，会每页耗满超时。
                        # 改 domcontentloaded + 等岗位卡出现（SSR 渲染），快且稳。
                        page.goto(_results_url(loc, pg), wait_until="domcontentloaded", timeout=30000)
                        try:
                            page.wait_for_selector("a[href*='jobs/results/']", timeout=8000)
                        except Exception:
                            pass
                        page.wait_for_timeout(800)
                        rows = page.eval_on_selector_all("a[href*='jobs/results/']", _EXTRACT_JS)
                    except Exception:
                        break
                    if not rows:
                        break
                    # 翻过末页后 Google 会回放同一页 → hrefs 重复就停
                    key = (loc, tuple(r.get("href") for r in rows))
                    if key in seen_pages:
                        break
                    seen_pages.add(key)
                    cards.extend(rows)
            browser.close()

        if not cards:
            raise RuntimeError("google: 未抓到岗位卡（反爬或页面改版）")
        return json.dumps({"cards": cards}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        out: List[RawJob] = []
        seen = set()
        for c in (data.get("cards", []) if isinstance(data, dict) else []):
            if not isinstance(c, dict):
                continue
            href = (c.get("href") or "").strip()
            title = (c.get("title") or "").strip()
            text = c.get("text") or ""
            if not href or not title:
                continue
            # 地点：卡文本 "... place | 城市, China | ..." → 取 place 后那段；否则用整段判华
            loc = None
            m = re.search(r"place\s*\|?\s*([^|]+?)(?:\s*\||$)", text)
            if m:
                loc = m.group(1).strip()
            if not normalizer.location_in_source_regions(loc or text, getattr(self, "regions", None)):
                continue
            jid = href.split("?")[0].lstrip("/")  # jobs/results/{id-slug}
            jd_url = _APP_BASE + jid
            if jd_url in seen:
                continue
            seen.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=loc,
                job_type=None,
                summary=None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,
            ))
        return out
