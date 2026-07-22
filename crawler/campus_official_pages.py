"""官方校招页抓取工艺（快路② P3b）—— URL 解析 + httpx 抓取 + 日期信号预筛 + HTML→text。

诚实留白：SPA 空壳（腾讯 1.7KB / 百度 2.8KB 等）靠长度门直接淘汰、不喂 LLM；SSR 有日期
信号的（字节 campus 页 819KB）才进抽取。全程抓公开官方页，不吃搜索额度。
"""
import re

import httpx
from selectolax.parser import HTMLParser

from official_gate import is_official_grounding

_COMMON_CAMPUS_PATHS = ("/campus", "/campus.html", "")
_DATE_SIGNAL = re.compile(
    r"网申|投递(时间|截止)|报名(时间|截止)|截止(时间|日期)|\d{1,2}月\d{1,2}[日号]|20(2[6-9]|3\d)[年./\-]\d{1,2}")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")


def official_campus_urls(source_rows, official_hosts, cap=5):
    """候选官方校招页 URL（去重、封顶）。原始 source_url（落在官方 host 上的）优先，
    再补 host + 常见 campus 路径变体。"""
    urls, seen = [], set()

    def add(u):
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    for r in source_rows or []:
        su = (r or {}).get("source_url") or ""
        if su and is_official_grounding(su, official_hosts):
            add(su)
    for h in sorted(official_hosts or []):
        for p in _COMMON_CAMPUS_PATHS:
            add(f"https://{h}{p}")
    return urls[:max(0, int(cap or 0))]


def has_date_signal(html, min_len=4000):
    """廉价预筛：长度门滤 SPA 空壳 + 日期信号正则。二者皆满足才算有信号。"""
    if not html or len(html) < min_len:
        return False
    return bool(_DATE_SIGNAL.search(html))


def html_to_text(html, cap=6000):
    if not html:
        return ""
    try:
        text = HTMLParser(html).text(separator="\n")
    except Exception:
        text = html
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)[:cap]


def fetch_first_with_signal(urls, timeout=12):
    """顺序抓候选 URL，返回第一个有日期信号的 (url, text)；全不命中返回 (None, "")。
    永不抛（单公司抓取异常不能拖垮整批）。**单测不打真实网络。**
    注意：httpx 的 RemoteProtocolError（服务器半关连接）可能在 .get 或读 body(.text) 时抛，
    整段（含 resp.text）都要包在 try 里，否则会逃逸到编排层变成 crash。"""
    headers = {"User-Agent": _UA}
    for u in urls or []:
        try:
            resp = httpx.get(u, headers=headers, timeout=timeout, follow_redirects=True)
            if resp.status_code != 200:
                continue
            html = resp.text or ""
        except Exception:
            continue
        if has_date_signal(html):
            return u, html_to_text(html)
    return None, ""
