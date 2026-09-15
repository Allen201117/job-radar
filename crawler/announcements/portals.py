"""官方源白名单 + 列表页解析。

白名单是本模块唯一的**归属门**：只从声明的官方 gov 域名抓，source_url 的 host 必属该域名，
→ 天然不会张冠李戴（企业爬取最头疼、这里免费解决的一点）。加省份 = 往 PORTALS 加一条并核实。
"""
from __future__ import annotations

import json
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
    # 列表数据形态："html"=常规 <a href>；"script_json"=数据在 <script>var listData JSON 里（江西）。
    list_format: str = "html"


# 各省人社厅「事业单位公开招聘公告」列表页（2026-09-15 逐省 live 验证的静态源）。
# ⚠️ 每省 detail URL 格式不同，detail_pat 必须逐省配，别假设统一格式。
# ⚠️ 归属门只放行 domains 里的官方 gov 域名；host + detail_pat + 标题 INCLUDE/EXCLUDE 三重过滤。
# ⚠️ 综合栏目（四川/河南/广西）混着非招聘内容，靠 classify 的标题过滤兜底（同 CLAUDE.md「后置过滤」）。
# 暂缺：浙江/河北（JS 渲染，需浏览器道，下一期）；辽宁（仅第三方人事考试网，无 gov.cn 源，跳过）。
# 江西已接（jx_rst，list_format="script_json" 从 <script>var listData 抽 JSON，无需浏览器）。
def _p(rx: str) -> re.Pattern:
    return re.compile(rx)


# ⚠️⚠️ 只放**从 GitHub US runner 实测可达**的省。别拿本机 dry-run 当准入——本机走中国路由能连，
#   runner 在美国，很多省 gov 服务器对海外 IP geo-block / 拒连（make_transport 已 retry=2 仍失败，非 TLS）。
#   2026-09-15 连跑两轮 CI 均如此：可达 北京/广东/湖北/福建；不可达 山东/湖南/安徽/陕西/山西（见下方 🌏 块）。
#   ⇒ 加省前必须回读 crawl_runs 的 list_errors，CI 真跑通才 active（CLAUDE.md「接完源必须回读线上 crawl_runs」）。
PORTALS: tuple[Portal, ...] = (
    Portal("bj_rsj", "北京市人力资源和社会保障局·公开招聘", "北京市",
           ("https://rsj.beijing.gov.cn/xxgk/gkzp/",), ("rsj.beijing.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    Portal("gd_hrss", "广东省人力资源和社会保障厅·事业单位招聘", "广东省",
           ("https://hrss.gd.gov.cn/zwgk/sydwzp/zpgg/index.html",), ("hrss.gd.gov.cn",),
           _p(r"post_\d+\.html")),
    Portal("hb_rst", "湖北省人力资源和社会保障厅·省直事业单位招聘公告", "湖北省",
           ("https://rst.hubei.gov.cn/bmdt/ztzl/ywzl/hbsszsydwgkzp/zpgg/",), ("rst.hubei.gov.cn",),
           _p(r"t\d{8}_\d+\.shtml")),
    Portal("fj_rst", "福建省人力资源和社会保障厅·事业单位人才招聘", "福建省",
           ("https://rst.fujian.gov.cn/zw/ztzl/zxzt/sydwrczp/",), ("rst.fujian.gov.cn",),
           _p(r"t\d{8}_\d+\.htm")),
)

# 🌏 大陆 runner 才跑的省（--include-geo-blocked 才带；创始人 Mac 的 launchd 每天跑）。两类：
#   ① CI US runner geo-block、本机中国路由能连（山东/湖南/安徽/陕西/山西，2026-09-15 两轮 CI 实证）；
#   ② 第二批新增、没测过 CI 可达性（默认丢这里让 Mac 跑，够用；将来要上 GitHub baseline 再逐个测 CI）。
#   有中国/香港自托管 runner 后可把稳定的搬回上面 PORTALS（[[job-radar-backend-review]] 待定成本项）。
#   ⚠️ 综合/公示-heavy 的省（贵州/云南/新疆/广西/河南）靠标题 INCLUDE/EXCLUDE 过滤兜底，产出偏少是正常。
_GEO_BLOCKED_FROM_CI: tuple[Portal, ...] = (
    Portal("sd_hrss", "山东省人力资源和社会保障厅·事业单位公开招聘", "山东省",
           ("http://hrss.shandong.gov.cn/channels/ch00232/",), ("hrss.shandong.gov.cn",),
           _p(r"articles/ch\d+/\d+/[0-9a-f-]+\.shtml")),
    Portal("hn_rst", "湖南省人力资源和社会保障厅·事业单位招聘", "湖南省",
           ("https://rst.hunan.gov.cn/rst/xxgk/zpzl/sydwzp/index.html",), ("rst.hunan.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    Portal("ah_hrss", "安徽省人力资源和社会保障厅·省直事业单位公开招聘", "安徽省",
           ("https://hrss.ah.gov.cn/zxzx/ztzl/ahssydwgkzp/index.html",), ("hrss.ah.gov.cn",),
           _p(r"ahssydwgkzp/\d+\.html")),
    Portal("sn_rst", "陕西省人力资源和社会保障厅·事业单位公开招聘", "陕西省",
           ("https://rst.shaanxi.gov.cn/sy/ztzl/rdzt/zkzl/sxssydwgkzp_22656/",),
           ("rst.shaanxi.gov.cn", "www.shaanxi.gov.cn"),
           _p(r"t\d{8}_\d+\.html")),
    Portal("sx_rst", "山西省人力资源和社会保障厅·事业单位公开招聘", "山西省",
           ("https://rst.shanxi.gov.cn/ztzl/zpxx/",), ("rst.shanxi.gov.cn",),
           _p(r"t\d{8}_\d+\.shtml")),
    # ── 第二批（2026-09-15 research live 验证，static 干净子栏目）──
    Portal("sh_rsj", "上海市人力资源和社会保障局·事业单位招聘公告", "上海市",
           ("https://rsj.sh.gov.cn/tzpgg_17408/index.html",), ("rsj.sh.gov.cn",),
           _p(r"t\d+_\d+\.html")),
    Portal("jl_hrss", "吉林省人力资源和社会保障厅·省直事业单位公开招聘", "吉林省",
           ("https://hrss.jl.gov.cn/rsrc/sydwrsgl/gkzp/",), ("hrss.jl.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    Portal("nmg_rst", "内蒙古人力资源和社会保障厅·省属事业单位招聘", "内蒙古自治区",
           ("https://rst.nmg.gov.cn/zhuantizhuanlan/ssdwzp/",), ("rst.nmg.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    Portal("cq_rlsbj", "重庆市人力资源和社会保障局·事业单位公开招聘2026", "重庆市",
           ("https://rlsbj.cq.gov.cn/zwxx_182/sydw/sydwgkzp2026/",), ("rlsbj.cq.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    # 江西：列表页 JS 渲染，但公告数据就在 <script>var listData = {articleList:[...]}> JSON 里
    #   （每条含 title + pubDate + urls.pc），curl 一次即得，list_format="script_json" 抽 JSON，无需浏览器。
    Portal("jx_rst", "江西省人力资源和社会保障厅·事业单位公开招聘", "江西省",
           ("https://rst.jiangxi.gov.cn/jxsrlzyhshbzt/col/col85519/index.html",),
           ("rst.jiangxi.gov.cn",),
           _p(r"content_\d+\.html"), list_format="script_json"),
    # 下面几个偏窄（厅本级 / 更新慢），靠标题过滤兜底，产出偏少正常（研究已标注）。
    Portal("henan_hrss", "河南省人力资源和社会保障厅·招考录用", "河南省",
           ("https://hrss.henan.gov.cn/zwgk/xxgk/yfygkdqtxx/zkly/",), ("hrss.henan.gov.cn",),
           _p(r"/\d{4}/\d{2}-\d{2}/\d+\.html")),
    Portal("xj_rst", "新疆维吾尔自治区人力资源和社会保障厅·事业单位公开招聘", "新疆维吾尔自治区",
           ("https://rst.xinjiang.gov.cn/xjrst/c112746/list.shtml",), ("rst.xinjiang.gov.cn",),
           _p(r"c112746/\d{6}/[0-9a-f]{32}\.shtml")),
    Portal("gx_rst", "广西人力资源和社会保障厅·考录招聘", "广西壮族自治区",
           ("http://rst.gxzf.gov.cn/zwgk/xxgk/rsxx/xxgkklzp/",), ("rst.gxzf.gov.cn",),
           _p(r"/t\d+\.shtml")),
)

# ⏸️ 仍暂缺（2026-09-15 两批 research + dry-run 逐个 live 试过）——下一个 session 从这里接：
#   【JS 渲染，需浏览器道或找其 AJAX 接口】江苏(col78506 列表 JS，detail 静态需 Referer)、浙江
#     (已找到内部接口 /api-gateway/jpaas-publish-server/... pageId=1229743683，但非公开约定别硬依赖)、
#     河北(整站 Vue SPA)、辽宁/青海(eportal 组件异步渲染，未定位数据源)、
#     天津(sydwgkzp 列表 JS，detail 静态)。
#     （江西已接：list_format="script_json"，列表数据在 <script>var listData JSON 里，无需浏览器。）
#   【WAF 拦列表页】四川(rst.sc.gov.cn 列表 403)、甘肃(rst.gansu.gov.cn 全站 412)——detail 能开、列表抓不了。
#   【只有综合栏目/信噪比差，本轮 dry-run 丢掉】云南(NewsLsit classid=602 过滤后 0)、贵州(残留是部委通知/
#     方案非公告)、黑龙江/宁夏/西藏(只有「通知公告」综合栏目，无事业单位招聘专栏)。

# 含 geo-blocked 省，便于 --portal 单独测/在大陆 runner 上按 key 取；默认 run 仍只跑 PORTALS。
PORTALS_BY_KEY: dict[str, Portal] = {p.key: p for p in (*PORTALS, *_GEO_BLOCKED_FROM_CI)}

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


# 列表项文字常尾随一个发布日期（山东「…公告2026-09-11」）或多余空白 → 清掉再当标题。
_TRAILING_DATE = re.compile(r"\s*20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s*$")


def _clean_title(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = _TRAILING_DATE.sub("", t).strip()
    return t[:200]


def _accept(portal: Portal, list_url: str, title: str, href: str,
            seen: set[str], out: list[ListItem], published_override: date | None = None) -> None:
    """把一条 (标题, 链接) 过三重门（归属 / detail_pat / 内容），通过则收进 out。html 与 script_json 两路共用。"""
    title = _clean_title(title)
    if not href or len(title) < 8:
        return
    full = urljoin(list_url, href)
    if not host_in_whitelist(portal, full):
        return
    if not portal.detail_pat.search(full):
        return
    if not is_recruitment_announcement(title):
        return
    if full in seen:
        return
    seen.add(full)
    out.append(ListItem(title=title, url=full,
                        published_at=published_override or published_from_url(full)))


def _match_delimited(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    """从 text[start]（须是 open_ch）起做配对扫描，尊重 JSON 字符串字面量里的括号，返回含首尾配对的子串。"""
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_json_array(text: str, key: str) -> str | None:
    """从 `key: [ ... ]`（JS 对象里的键，可能未加引号）抠出 JSON 数组文本；尊重字符串字面量里的方括号。"""
    idx = text.find(key)
    if idx < 0:
        return None
    b = text.find("[", idx)
    if b < 0:
        return None
    return _match_delimited(text, b, "[", "]")


# script_json 详情页正文键：带冒号 + 引号，避开页面 markup 里的 id="content" 那类裸 "content"。
_CONTENT_KEY = re.compile(r'"content"\s*:\s*"')


def _extract_script_json_content(html: str) -> str | None:
    """script_json 详情页正文 HTML：正文在 content:{"content":"<html>"} 这个 JSON 字符串里（江西也是 JS 渲染）。"""
    m = _CONTENT_KEY.search(html)
    if not m:
        return None
    b = html.rfind("{", 0, m.start())  # 该 JSON 对象的起始花括号
    if b < 0:
        return None
    obj = _match_delimited(html, b, "{", "}")
    if not obj:
        return None
    try:
        data = json.loads(obj)
    except ValueError:
        return None
    return data.get("content") if isinstance(data, dict) else None


def detail_text(portal: Portal, html: str) -> str:
    """详情页正文纯文本（供截止日 / 受众抽取）。

    script_json 源的详情页同样 JS 渲染 → 从 content:{"content":"<html>"} 里挖正文再去标签；
    抽不到正文返回空串（让上游走 published+TTL 兜底，不假装有截止日）。静态源取可见正文。
    """
    if portal.list_format == "script_json":
        body = _extract_script_json_content(html)
        if not body:
            return ""
        return re.sub(r"\s+", " ", HTMLParser(body).text(separator=" ")).strip()
    tree = HTMLParser(html)
    for node in tree.css("script, style"):
        node.decompose()
    node = tree.body or tree
    return node.text(separator=" ")


_SCRIPT_JSON_PUBDATE = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")


def _iter_script_json_items(html: str):
    """江西：列表数据在 <script>var listData = {articleList:[...]}> 里。yield (title, pc_href, published_at)。

    找不到 articleList 时抛错（页面形态变了）——让 harvest 记 list_errors，不静默返回 0（工程化底线）。
    """
    raw = _extract_json_array(html, "articleList")
    if raw is None:
        raise ValueError("script_json 列表：未找到 articleList 数组（页面形态可能变了）")
    for it in json.loads(raw):
        title = it.get("title") or it.get("showTitle") or ""
        try:
            urls = json.loads(it.get("urls") or "{}")  # urls 是**字符串化**的 JSON
        except (ValueError, TypeError):
            urls = {}
        href = urls.get("pc") if isinstance(urls, dict) else ""
        pub = None
        m = _SCRIPT_JSON_PUBDATE.match((it.get("pubDate") or "").strip())
        if m:
            try:
                pub = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pub = None
        yield title, href or "", pub


def parse_list(portal: Portal, list_url: str, html: str) -> list[ListItem]:
    """从列表页 HTML 抽出「可报名招聘公告」候选（已过归属门 + 内容过滤）。"""
    seen: set[str] = set()
    out: list[ListItem] = []
    if portal.list_format == "script_json":
        for title, href, pub in _iter_script_json_items(html):
            _accept(portal, list_url, title, href, seen, out, published_override=pub)
    else:
        tree = HTMLParser(html)
        for a in tree.css("a[href]"):
            _accept(portal, list_url, a.text() or "", a.attributes.get("href") or "", seen, out)
    return out
