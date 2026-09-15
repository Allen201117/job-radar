"""官方源白名单 + 列表页解析。

白名单是本模块唯一的**归属门**：只从声明的官方 gov 域名抓，source_url 的 host 必属该域名，
→ 天然不会张冠李戴（企业爬取最头疼、这里免费解决的一点）。加省份 = 往 PORTALS 加一条并核实。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .classify import is_recruitment_announcement


@dataclass(frozen=True)
class Portal:
    key: str                       # 白名单键，如 'gd_hrss'
    name: str                      # 展示名
    region: str                    # 省/市
    list_urls: tuple[str, ...]     # 招聘公告列表页（可多页/多子栏目）
    domains: tuple[str, ...]       # 官方域名白名单（source_url host 必须命中其一）
    # 详情页 URL 特征（用于从列表页里挑出公告详情链接）
    detail_pat: re.Pattern = field(default_factory=lambda: re.compile(r"(post_\d+\.html|/t20\d{6}_\d+\.html)"))


# MVP：只登记 Phase 0 实测通过的两省静态源。扩省在这里加行。
PORTALS: tuple[Portal, ...] = (
    Portal(
        key="bj_rsj",
        name="北京市人力资源和社会保障局·公开招聘",
        region="北京市",
        list_urls=("https://rsj.beijing.gov.cn/xxgk/gkzp/",),
        domains=("rsj.beijing.gov.cn",),
    ),
    Portal(
        key="gd_hrss",
        name="广东省人力资源和社会保障厅·事业单位招聘",
        region="广东省",
        list_urls=("https://hrss.gd.gov.cn/zwgk/sydwzp/zpgg/index.html",),
        domains=("hrss.gd.gov.cn",),
    ),
)

PORTALS_BY_KEY: dict[str, Portal] = {p.key: p for p in PORTALS}

# URL 里自带的发布日期：北京 t20260914_xxx（8 位，前缀是 t，不是 _//）；退化到 /202609/ 目录段（月精度）。
_URL_DATE_8 = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_URL_DATE_6 = re.compile(r"/(20\d{2})(\d{2})/")


def host_in_whitelist(portal: Portal, url: str) -> bool:
    """source_url 的 host 是否属于该 portal 的官方域名白名单（归属门）。"""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in portal.domains)


def published_from_url(url: str) -> date | None:
    """从 URL 里的日期段推断发布日期（北京自带；广东无则返 None）。"""
    m = _URL_DATE_8.search(url)
    if not m:
        m = _URL_DATE_6.search(url)
        if not m:
            return None
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@dataclass(frozen=True)
class ListItem:
    title: str
    url: str
    published_at: date | None


def parse_list(portal: Portal, list_url: str, html: str) -> list[ListItem]:
    """从列表页 HTML 抽出「可报名招聘公告」候选（已过归属门 + 内容过滤）。"""
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[ListItem] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        title = (a.text() or "").strip()
        if not href or len(title) < 8:
            continue
        full = urljoin(list_url, href)
        if not host_in_whitelist(portal, full):
            continue
        if not portal.detail_pat.search(full):
            continue
        if not is_recruitment_announcement(title):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(ListItem(title=title[:200], url=full, published_at=published_from_url(full)))
    return out
