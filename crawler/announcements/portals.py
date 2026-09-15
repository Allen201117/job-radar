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
# 暂缺：河北（整站 Vue SPA，需浏览器道或找 AJAX 接口，下一期）；辽宁/青海（eportal 异步，未定位数据源，勘察中）。
# 已接的三种非静态形态（均无需浏览器）：江西 script_json（内嵌 <script>var listData JSON）、
#   浙江 json_fragment（非公开 GET 接口返 data.html 片段）、江苏 html+CDATA 解包、天津 html。
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
    # ── 第三批（2026-09-15 recon live 验证）──
    # 天津：列表 static <a href>；⚠️ 每条公告标题几乎都叫「天津市部分事业单位公开招聘信息」，
    #   去重靠 source_url（本管道天然如此），别指望靠标题区分。detail 是 .html 不是 .shtml。
    Portal("tj_rsj", "天津市人力资源和社会保障局·事业单位公开招聘", "天津市",
           ("https://hrss.tj.gov.cn/ztzl/ztzl1/sydwgkzp/",), ("hrss.tj.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    # 江苏：列表 <li><a> 藏在 <record><![CDATA[…]]> 里（selectolax 不建 DOM）→ _unwrap_cdata 解包后走 html 路径。
    #   ⚠️ 该栏目混「招聘公告 + 拟聘用名单公示」，后者靠 classify EXCLUDE（公示/拟聘/名单）剔除，别放宽。
    Portal("js_hrss", "江苏省人力资源和社会保障厅·省属事业单位招聘", "江苏省",
           ("https://jshrss.jiangsu.gov.cn/col/col78506/index.html",), ("jshrss.jiangsu.gov.cn",),
           _p(r"art_\d+_\d+\.html")),
    # 浙江：⚠️ 唯一走「非公开 GET 接口」的省（list_format="json_fragment"）——列表页是空壳，数据由
    #   /api-gateway/... 这个 GET 返 {"data":{"html":"<li><a>片段"}}。curl 可得、无需浏览器，但更脆：
    #   ① query 参数（webId/tplSetId/tagId/pageId）是页面 JS 里硬编码的常量，官方换模板即失效
    #      （失效时 data.html 缺失 → parse_list 抛错记 list_errors，不静默）；② 只返最新 10 条、无法翻页回填历史。
    # tagId 的值「当前栏目列表」必须**预先 percent-encode**：它既是 GET query，又被复用为详情抓取的
    # Referer 请求头，而 HTTP 头只能是 latin-1，原文中文会 UnicodeEncodeError（实测 httpx 不会二次编码 %E5…）。
    Portal("zj_rlsbt", "浙江省人力资源和社会保障厅·事业单位招聘公告", "浙江省",
           ("https://rlsbt.zj.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
            "?parseType=bulidstatic&webId=2758&tplSetId=kUBgoFENJiaYxr31jYEph&pageType=column"
            "&tagId=%E5%BD%93%E5%89%8D%E6%A0%8F%E7%9B%AE%E5%88%97%E8%A1%A8&editType=null&pageId=1229743683",),
           ("rlsbt.zj.gov.cn",),
           _p(r"art_[0-9a-f]{32}\.html"), list_format="json_fragment"),
    # ── 第四批（2026-09-16 recon live 验证，gov.cn 干净专属栏目）──
    # 甘肃：主站 rst.gansu.gov.cn 全站真 WAF(412)，但官方子站 ks.rst.gansu.gov.cn（甘肃人事考试网，
    #   页脚版权=省人社厅，仍在 *.gov.cn 白名单内）无 WAF。考试栏目干净（实测 12/15 过门）。
    Portal("gs_ks", "甘肃省人力资源和社会保障厅·事业单位公开招聘（人事考试网）", "甘肃省",
           ("https://ks.rst.gansu.gov.cn/ncms/wzlb.shtml?mkbh=gwysydwks",), ("rst.gansu.gov.cn",),
           _p(r"article_[0-9a-f]{32}\.shtml")),
    # 四川：此前「列表 403」是误判——那是裸目录的标准 nginx 403，真实列表页是 zfxxgkpage.shtml（非 WAF）。
    #   招考录用栏目干净但窄（厅本级/直属，产出偏少正常）。
    Portal("sc_rst", "四川省人力资源和社会保障厅·招考录用", "四川省",
           ("https://rst.sc.gov.cn/rst/zkly/zfxxgkpage.shtml",), ("rst.sc.gov.cn",),
           _p(r"zkly/20\d{2}/\d+/\d+/[0-9a-f]{32}\.shtml")),
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

# ⏸️ 仍暂缺（2026-09-16 三批 research + live 逐个试过）——下一个 session 从这里接：
#   【待创始人拍板：非 gov.cn 归属红线】辽宁/青海——省厅 gov.cn 站无干净/更新的招聘子栏目，
#     能 curl 的干净源是「省人事考试中心」门户（辽宁 lnrsks.com、青海 qhpta.com，均 static）。
#     纳不纳入白名单是归属政策，需创始人定，别自作主张（同「国聘是第三方禁令唯一例外」先例）。
#   【待创始人拍板：综合栏目政策】黑龙江/宁夏/西藏——都是 gov.cn，但只有综合「通知公告」栏目、
#     无专属招聘子栏目，classify 标题门能保精度（噪音在 list 端就滤掉、不浪费 detail 抓取），
#     但接综合栏目 = 翻「综合栏目不接」红线，需创始人定。黑龙江还是 json_api（{"data":{"results":[…]}}，
#     需新增一种 list_format）；宁夏/西藏 是 static-a-href（默认 detail_pat 覆盖），产出极低（真招聘半年一次）。
#   【真难/未通】河北——整站 Vue SPA 且数据接口 /rsmhapi/ 要登录 token（Vuex session），匿名拿不到，
#     比普通 needs-browser 更难；备选 hbrc.com.cn 是 static 但混私企招聘（信噪比差，弃）。
#   （已接的非静态形态：江西 script_json / 浙江 json_fragment / 江苏 html+CDATA / 天津·甘肃·四川 html。）

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


_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _anchors_from(portal: Portal, list_url: str, html: str,
                  seen: set[str], out: list[ListItem]) -> None:
    tree = HTMLParser(html)
    for a in tree.css("a[href]"):
        title = a.text() or a.attributes.get("title") or ""  # 天津那类标题只在 title 属性里
        _accept(portal, list_url, title, a.attributes.get("href") or "", seen, out)


def _parse_anchors(portal: Portal, list_url: str, html: str,
                   seen: set[str], out: list[ListItem]) -> None:
    """从一段 HTML 按 <a href> 收候选（seen 去重）。

    先解析主文档（北京/广东/天津…的 <a> 直接在 DOM 里）；再把每个 <![CDATA[…]]> 块**单独当片段**解析——
    江苏把 <li><a> 塞进 <record><![CDATA[…]]>，selectolax 既不解析 CDATA 内容、把它并进整页又会丢锚点，
    只有把每块隔离出来单独解析才拿得到（实测同一页整页 0 / 逐块 60）。非 CDATA 页此循环是空操作。
    """
    _anchors_from(portal, list_url, html, seen, out)
    for block in _CDATA.findall(html):
        _anchors_from(portal, list_url, block, seen, out)


def parse_list(portal: Portal, list_url: str, html: str) -> list[ListItem]:
    """从列表页 HTML 抽出「可报名招聘公告」候选（已过归属门 + 内容过滤）。"""
    seen: set[str] = set()
    out: list[ListItem] = []
    if portal.list_format == "script_json":
        for title, href, pub in _iter_script_json_items(html):
            _accept(portal, list_url, title, href, seen, out, published_override=pub)
    elif portal.list_format == "json_fragment":
        # 浙江：列表由普通 GET AJAX 返回 {"data":{"html":"<li><a>…片段"}}，list_url 即该接口 URL。
        # data.html 缺失（接口参数失效）→ 抛错让 harvest 记 list_errors，不静默 0（非公开接口尤其要出声）。
        try:
            data = json.loads(html)
        except ValueError as exc:
            raise ValueError(f"json_fragment 列表：响应不是 JSON（{type(exc).__name__}）") from exc
        frag = (data.get("data") or {}).get("html") if isinstance(data, dict) else None
        if not frag:
            raise ValueError("json_fragment 列表：data.html 缺失（接口参数可能失效）")
        _parse_anchors(portal, list_url, frag, seen, out)
    else:  # html：整页 <a href>（含 CDATA 解包）
        _parse_anchors(portal, list_url, html, seen, out)
    return out
