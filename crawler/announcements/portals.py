"""官方源白名单 + 列表页解析。

白名单是本模块唯一的**归属门**：只从声明的官方政府域名或获授权的人社厅下属官方机构域名抓，
source_url 的 host 必属该域名，→ 天然不会张冠李戴（企业爬取最头疼、这里免费解决的一点）。
加省份 = 往 PORTALS 加一条并核实。
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
    # 列表数据形态：html=常规 <a href>；script_json=内嵌 JSON；json_fragment=JSON 内的 HTML；json_api=结构化 JSON。
    list_format: str = "html"
    # 翻页：("index_{}.html", (1, 2, 3)) = 在 list_urls[0] 同目录下再抓这几页。
    # ⚠️ 页码基数**逐省实测**，不要按经验填：URL 以 `/` 结尾的站多是 index_1 才是第 2 页（0 基），
    #   以 `index.html` 结尾的站多是 index_2 才是第 2 页（1 基）。填错只会静默抓回第一页、白跑。
    page_pattern: str | None = None
    page_indexes: tuple[int, ...] = ()


# 各省人社厅「事业单位公开招聘公告」列表页（2026-09-15 逐省 live 验证的静态源）。
# ⚠️ 每省 detail URL 格式不同，detail_pat 必须逐省配，别假设统一格式。
# ⚠️ 归属门只放行 domains 里的官方政府域名或获授权的下属官方机构域名；host + detail_pat + 标题 INCLUDE/EXCLUDE 三重过滤。
# ⚠️ 综合栏目（四川/河南/广西）混着非招聘内容，靠 classify 的标题过滤兜底（同 CLAUDE.md「后置过滤」）。
# 暂缺 4 个省级行政区（2026-09-18 逐条数过，此前这里只写了「暂缺河北」，是错的）：
#   河北（整站 Vue SPA，无匿名可取数据）、海南、贵州、云南。加省前先读本文件顶部的 Portal 字段说明。
# 已接的非静态形态（均无需浏览器）：江西 script_json（内嵌 <script>var listData JSON）、
#   浙江 json_fragment（非公开 GET 接口返 data.html 片段）、黑龙江 json_api（结构化 GET JSON）、江苏 html+CDATA 解包、天津 html。
def _p(rx: str) -> re.Pattern:
    return re.compile(rx)


def all_list_urls(portal: Portal) -> list[str]:
    """列表页全集 = 配置的 list_urls + 翻页展开出来的更深几页。

    为什么要翻页（2026-09-18 实测）：各省人社厅的栏目一页只有 10~25 条，而**一页装不下当前
    还在报名的全部公告** —— 往后翻 2~4 页、端到端过完可报名门 + TTL 之后，仍净增 48 条真能展示的
    （湖南 26 / 北京 8 / 上海 8 / 重庆 4）。
    ⚠️ 别拿「翻出多少条候选」当收益：同一次实测翻出 337 条候选，其中 289 条是**已截止或超 45 天 TTL**
    的老公告（天津那 56 条同名汇总页全部超龄）。只数「真能展示」的。
    """
    urls = list(portal.list_urls)
    if portal.page_pattern and portal.page_indexes:
        base = portal.list_urls[0].rsplit("/", 1)[0] + "/"
        urls += [base + portal.page_pattern.format(i) for i in portal.page_indexes]
    return urls


# ⚠️⚠️ 只放**从 GitHub US runner 实测可达**的省。别拿本机 dry-run 当准入——本机走中国路由能连，
#   runner 在美国，很多省 gov 服务器对海外 IP geo-block / 拒连（make_transport 已 retry=2 仍失败，非 TLS）。
#   2026-09-15 连跑两轮 CI 均如此：可达 北京/广东/湖北/福建；不可达 山东/湖南/安徽/陕西/山西（见下方 🌏 块）。
#   ⇒ 加省前必须回读 crawl_runs 的 list_errors，CI 真跑通才 active（CLAUDE.md「接完源必须回读线上 crawl_runs」）。
PORTALS: tuple[Portal, ...] = (
    Portal("bj_rsj", "北京市人力资源和社会保障局·公开招聘", "北京市",
           ("https://rsj.beijing.gov.cn/xxgk/gkzp/",), ("rsj.beijing.gov.cn",),
           _p(r"t\d{8}_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(1, 2, 3)),
    Portal("gd_hrss", "广东省人力资源和社会保障厅·事业单位招聘", "广东省",
           ("https://hrss.gd.gov.cn/zwgk/sydwzp/zpgg/index.html",), ("hrss.gd.gov.cn",),
           _p(r"post_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(2, 3, 4)),
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
           _p(r"t\d{8}_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(2, 3, 4)),
    Portal("ah_hrss", "安徽省人力资源和社会保障厅·省直事业单位公开招聘", "安徽省",
           ("https://hrss.ah.gov.cn/zxzx/ztzl/ahssydwgkzp/index.html",), ("hrss.ah.gov.cn",),
           _p(r"ahssydwgkzp/\d+\.html")),
    Portal("sn_rst", "陕西省人力资源和社会保障厅·事业单位公开招聘", "陕西省",
           ("https://rst.shaanxi.gov.cn/sy/ztzl/rdzt/zkzl/sxssydwgkzp_22656/",),
           ("rst.shaanxi.gov.cn", "www.shaanxi.gov.cn"),
           _p(r"t\d{8}_\d+\.html"),
           # 陕西这个栏目只有 2 页（index_2 起 404，2026-09-18 实测）。
           page_pattern="index_{}.html", page_indexes=(1,)),
    Portal("sx_rst", "山西省人力资源和社会保障厅·事业单位公开招聘", "山西省",
           ("https://rst.shanxi.gov.cn/ztzl/zpxx/",), ("rst.shanxi.gov.cn",),
           _p(r"t\d{8}_\d+\.shtml")),
    # ── 第二批（2026-09-15 research live 验证，static 干净子栏目）──
    Portal("sh_rsj", "上海市人力资源和社会保障局·事业单位招聘公告", "上海市",
           ("https://rsj.sh.gov.cn/tzpgg_17408/index.html",), ("rsj.sh.gov.cn",),
           _p(r"t\d+_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(2, 3, 4)),
    Portal("jl_hrss", "吉林省人力资源和社会保障厅·省直事业单位公开招聘", "吉林省",
           ("https://hrss.jl.gov.cn/rsrc/sydwrsgl/gkzp/",), ("hrss.jl.gov.cn",),
           _p(r"t\d{8}_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(1, 2, 3)),
    Portal("nmg_rst", "内蒙古人力资源和社会保障厅·省属事业单位招聘", "内蒙古自治区",
           ("https://rst.nmg.gov.cn/zhuantizhuanlan/ssdwzp/",), ("rst.nmg.gov.cn",),
           _p(r"t\d{8}_\d+\.html")),
    Portal("cq_rlsbj", "重庆市人力资源和社会保障局·事业单位公开招聘2026", "重庆市",
           ("https://rlsbj.cq.gov.cn/zwxx_182/sydw/sydwgkzp2026/",), ("rlsbj.cq.gov.cn",),
           _p(r"t\d{8}_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(1, 2, 3)),
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
           _p(r"t\d{8}_\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(1, 2, 3)),
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
           _p(r"/\d{4}/\d{2}-\d{2}/\d+\.html"),
           page_pattern="index_{}.html", page_indexes=(1, 2, 3)),
    Portal("xj_rst", "新疆维吾尔自治区人力资源和社会保障厅·事业单位公开招聘", "新疆维吾尔自治区",
           ("https://rst.xinjiang.gov.cn/xjrst/c112746/list.shtml",), ("rst.xinjiang.gov.cn",),
           _p(r"c112746/\d{6}/[0-9a-f]{32}\.shtml"),
           page_pattern="list_{}.shtml", page_indexes=(2, 3, 4)),
    Portal("gx_rst", "广西人力资源和社会保障厅·考录招聘", "广西壮族自治区",
           ("http://rst.gxzf.gov.cn/zwgk/xxgk/rsxx/xxgkklzp/",), ("rst.gxzf.gov.cn",),
           _p(r"/t\d+\.shtml")),
    # ── 第五批（2026-09-16 创始人拍板：综合栏目放宽 + 非 gov.cn 官方下属机构入白名单）──
    Portal("hlj_hrss", "黑龙江省人力资源和社会保障厅·事业单位公开招聘（通知公告）", "黑龙江省",
           ("https://hrss.hlj.gov.cn/common/search/97292339af064f35a6fa6958746ab8ed"
            "?_isAgg=true&_isJson=true&_pageSize=50&_template=index&page=1",),
           ("hrss.hlj.gov.cn",),
           _p(r"c00_\d+\.shtml"), list_format="json_api"),
    Portal("nx_hrss", "宁夏回族自治区人力资源和社会保障厅·公示公告", "宁夏回族自治区",
           ("https://hrss.nx.gov.cn/gzdt/gsgg/",), ("hrss.nx.gov.cn",),
           _p(r"t20\d{6}_\d+\.html")),
    Portal("xz_hrss", "西藏自治区人力资源和社会保障厅·通知公告", "西藏自治区",
           ("https://hrss.xizang.gov.cn/xwzx/tzgg/",), ("hrss.xizang.gov.cn",),
           _p(r"t20\d{6}_\d+\.html")),
    # ⚠️ 辽宁/青海是非 gov.cn——省人事考试中心官网（人社厅下属官方机构，创始人已授权入白名单；仍拒中公/华图第三方）。
    Portal("ln_ks", "辽宁省人事考试中心·事业单位招聘公告", "辽宁省",
           ("https://www.lnrsks.com/html/sydw_zhaopingonggao/",), ("lnrsks.com",),
           _p(r"sydw_zhaopingonggao/\d+\.html")),
    # ⚠️ 青海仅 http 不支持 https（https 返回连接失败）。
    Portal("qh_pta", "青海省人事考试信息网·事业单位考试", "青海省",
           ("http://www.qhpta.com/ncms/sydwks.shtml",), ("qhpta.com",),
           _p(r"article_[0-9a-f]{32}\.shtml")),
)

# ⏸️ 仍暂缺（2026-09-16 live 逐个试过）——下一个 session 从这里接：
#   【真难/未通】河北——整站 Vue SPA 且数据接口 /rsmhapi/ 要登录 token（Vuex session），匿名拿不到，
#     比普通 needs-browser 更难；备选 hbrc.com.cn 是 static 但混私企招聘（信噪比差，弃）。
#   （已接的非静态形态：江西 script_json / 浙江 json_fragment / 黑龙江 json_api / 江苏 html+CDATA / 天津·甘肃·四川 html。）

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


def _canonical_scheme(portal: Portal, url: str) -> str:
    """详情链接的协议统一成该 portal 自己列表页的协议。

    ⚠️ 不能一律升 https —— 山东那个站就是 http 的。之所以要统一：同一篇公告的 http:// 和 https://
    是**两个不同的 source_url**，而 source_url 是唯一键 → 同一条公告在库里存两行、页面上出现两张
    一模一样的卡（2026-09-18 实测湖北有 2 组）。站内链接混用两种协议很常见，靠 portal 自报的协议归一。
    """
    want = portal.list_urls[0].split("://", 1)[0]
    other = "http" if want == "https" else "https"
    if url.startswith(other + "://") and urlparse(url).netloc == urlparse(portal.list_urls[0]).netloc:
        return want + "://" + url.split("://", 1)[1]
    return url


def _accept(portal: Portal, list_url: str, title: str, href: str,
            seen: set[str], out: list[ListItem], published_override: date | None = None) -> None:
    """把一条 (标题, 链接) 过三重门（归属 / detail_pat / 内容），通过则收进 out。html 与 script_json 两路共用。"""
    title = _clean_title(title)
    if not href or len(title) < 8:
        return
    full = _canonical_scheme(portal, urljoin(list_url, href))
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
    elif portal.list_format == "json_api":
        try:
            data = json.loads(html)
        except ValueError as exc:
            raise ValueError(f"json_api 列表：响应不是 JSON（{type(exc).__name__}）") from exc
        results = (data.get("data") or {}).get("results") if isinstance(data, dict) else None
        if results is None:
            raise ValueError("json_api 列表：data.results 缺失（接口变了）")
        for it in results:
            m = _SCRIPT_JSON_PUBDATE.match((it.get("publishedTimeStr") or "").strip())
            pub = None
            if m:
                try:
                    pub = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pub = None
            _accept(portal, list_url, it.get("title") or "", it.get("url") or "", seen, out,
                    published_override=pub)
    else:  # html：整页 <a href>（含 CDATA 解包）
        _parse_anchors(portal, list_url, html, seen, out)
    return out
