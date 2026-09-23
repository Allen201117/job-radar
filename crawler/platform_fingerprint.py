"""招聘入口平台指纹。只做公开页面 GET，不绕验证码或登录态。"""
import re
import unicodedata
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

import httpx


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_HOST_RULES = (
    ("mokahr.com", "moka", "moka"),
    ("zhiye.com", "beisen", "beisen"),
    ("italent.cn", "beisen", "beisen"),
    ("hotjob.cn", "hotjob", "hotjob"),
    ("dayee.com", "dayee", None),
    ("myworkdayjobs.com", "workday", "workday"),
    ("successfactors", "successfactors", "successfactors"),
    ("sapsf", "successfactors", "successfactors"),
    ("eightfold.ai", "eightfold", "eightfold"),
    ("oraclecloud.com", "oracle", "oracle"),
    ("avature.net", "avature", None),
    ("taleo.net", "taleo", None),
    ("greenhouse.io", "greenhouse", "greenhouse"),
    ("lever.co", "lever", "lever"),
    ("ashbyhq.com", "ashby", "ashby"),
    ("smartrecruiters.com", "smartrecruiters", "smartrecruiters"),
    ("feishu.cn", "feishu", "feishu"),
    ("iguopin.com", "iguopin", "iguopin"),
)
_INTERFACE_RULES = (
    ("/api/v1/search/job/posts", "feishu", "feishu"),
    ("/wday/cxs/", "workday", "workday"),
    ("/posting-api/job-board/", "ashby", "ashby"),
    ("boards-api.greenhouse.io/v1/boards/", "greenhouse", "greenhouse"),
    ("api.lever.co/v0/postings/", "lever", "lever"),
    ("/wecruit/positioninfo/listposition/", "hotjob", "hotjob"),
    ("/web/json/position/list", "wt", "wt"),
)
_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.I)


def _safe_urlparse(raw):
    """解析**从网页内容里抠出来的** URL；解析不了返回 None，调用方跳过这一条。

    _URL_RE 刻意放得很宽，抠出来的东西不全是合法 URL：JS 里的 `"https://[" + host + "]"`
    会让 urlparse 抛「Invalid IPv6 URL」，中文正文里的「http://www.x.com，或巨潮资讯网：…」
    会抛「netloc … contains invalid characters under NFKC normalization」。
    旧写法不接这个 ValueError → 整个 fingerprint() 抛出 → gap_funnel 把**整家公司**记成异常、
    次日重试 → 同一个页面天天炸（2026-09-14~22 施耐德、联邦快递、荣盛石化隔天一次，一次都没判出结论）。
    一条坏字符串只该丢掉它自己，不该拖垮整页的平台判定。
    """
    try:
        parsed = urlparse(str(raw or ""))
        parsed.hostname  # noqa: B018 —— 部分畸形 netloc 要到取 hostname 才暴露
    except ValueError:
        return None
    return parsed


def _safe_urljoin(base, raw):
    """同 _safe_urlparse：页面里的 href/src 拼不成合法 URL 就返回 None。"""
    try:
        joined = urljoin(base, str(raw or "").strip())
    except ValueError:
        return None
    return joined if _safe_urlparse(joined) is not None else None
_HOSTLIKE_RE = re.compile(
    r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![a-z0-9-])", re.I
)
_JOB_SHAPE_RE = re.compile(
    r"(job[-_ ]?(?:detail|description|title|list)|position[-_ ]?(?:detail|list|id)|职位详情|岗位详情)",
    re.I,
)
_CAREERS_SIGNAL_RE = re.compile(
    r"(招聘|社会招聘|校园招聘|职位|岗位|人才|加入我们|工作机会|"
    r"\bcareers?\b|\bjobs?\b|\brecruit(?:ment|ing)?\b|\btalent\b)",
    re.I,
)
_COMPANY_SUFFIXES = tuple(sorted((
    "有限责任公司", "股份有限公司", "集团股份", "集团公司", "控股集团",
    "有限公司", "股份", "集团", "公司", "有限", "控股", "科技", "传媒",
    "影业", "银行", "兄弟",
    "corporation", "company", "holdings", "holding", "limited", "group",
    "corp", "ltd", "inc",
), key=len, reverse=True))
_SCRIPT_STYLE_RE = re.compile(
    r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>",
    re.I | re.S,
)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>", re.S)


def _host_detection(host, path=""):
    host = (host or "").lower().rstrip(".")
    path = (path or "").lower()
    for token, platform, adapter in _HOST_RULES:
        matches = (
            host == token or host.endswith("." + token)
            if "." in token
            else token in host.split(".")
        )
        if matches:
            if platform == "hotjob" and "/wt/" in path:
                return ("wt", "wt")
            return (platform, adapter)
    return None


_WT_PORTAL_RE = re.compile(r"/wt/([A-Za-z0-9_-]+)/web/index\b", re.I)


def detect_platform(final_url, html):
    """纯函数：最终 host → HTML 第三方 host → 接口路径特征。"""
    parsed = _safe_urlparse(final_url) or urlparse("")
    direct = _host_detection(parsed.hostname, parsed.path)
    if direct:
        # `{brand}.hotjob.cn` 根路径同时托管两代产品：新版 wecruit（/{SU…}/pb/…）与老版
        # WinTalent（/wt/{brand}/web/index）。落在根路径、页面却只链到 /wt/ 门户的，
        # 是 wt 租户（富士康 foxconn.hotjob.cn 即此形态，2026-09-18 live）——按 host 判成
        # hotjob 会让下游拿 wecruit 的 suite/config 去探一个不存在的租户。
        if direct[0] == "hotjob" and "/pb/" not in (parsed.path or "").lower() \
                and _WT_PORTAL_RE.search(str(html or "")):
            return ("wt", "wt")
        return direct

    text = str(html or "")
    for candidate in _URL_RE.findall(text):
        embedded = _safe_urlparse(candidate.rstrip(");,"))
        if embedded is None:
            continue
        detected = _host_detection(embedded.hostname, embedded.path)
        if detected:
            return detected
    lower = text.lower()
    # 某些 bundle 只留 host 字符串、不带 scheme；仍按域名边界匹配。
    for host in _HOSTLIKE_RE.findall(lower):
        detected = _host_detection(host)
        if detected:
            return detected
    combined = (str(final_url or "") + "\n" + text).lower()
    for token, platform, adapter in _INTERFACE_RULES:
        if token in combined:
            return (platform, adapter)
    return ("unknown", None)


# ── 「对方是不是真的拒了我们」的唯一判据 ──────────────────────────────────────
# ⚠️ 只认三种证据：状态码 / WAF 与验证码厂商写进页面的基础设施标记 / **可见文本**里的拦截文案。
# 绝不对整段 HTML 做裸子串匹配——2026-09-05 拿 105 个线上健康页面实测过旧判据的假阳性：
#   · `akamai` + `denied`：greenhouse 的 hasbro job board（HTTP 200 的正常岗位 JSON）被判反爬，
#     只因岗位正文提到 Akamai、条款里出现 denied。1/105。
#   · `验证码` / `captcha`：**41/105（39%）** 命中——北森 / Moka 门户的登录框本来就带短信验证码。
#     所以「页面里出现验证码字样」永远不能单独作为反爬判据，只有厂商基础设施标记才算数。
#   · `请开启JavaScript`：那是**所有** SPA 的 <noscript> 兜底文案，是「这页要 JS」不是「对方拒了我们」，
#     该走 unknown_spa 交给浏览器道，已删除。
# 为什么较真：把我们自己的判断失误说成对方的行为，会把排查引向完全错误的方向——
# 21 家必投公司被标 anti_bot（去研究怎么绕反爬），逐个核查后全部只是漏斗停在
# 「公司官网的招聘介绍页」上，那种页面本来就没有岗位数据。同类见 CLAUDE.md
# 「接口返 0 / 403 不能证明对方没开」。
_BLOCK_STATUS = (403, 412, 503)
_CHALLENGE_INFRA_RE = re.compile(
    r"(cf-chl-|/cdn-cgi/challenge-platform/|cloudflare challenge|"
    r"_incapsula_resource|incapsula incident|distil_r_captcha|"
    r"captcha-delivery\.com|geetest\.com|c\.dun\.163\.com|aliyun[a-z]*captcha)",
    re.I,
)
# 拦截页的可见文案。**只在「这一页不像招聘页」时才作数**：招聘页里出现这些词
# 多半来自岗位正文或登录框，不是拦截。
_BLOCK_TEXT_RE = re.compile(
    r"(access denied|permission to access|unusual traffic|"
    r"访问被拒绝|拒绝访问|请求被拒绝|访问受限|人机验证|滑动验证)",
    re.I,
)


def _visible_text(html, limit=12000):
    """去掉 script/style 与标签后的可见文本（判据只看人能看见的部分）。"""
    visible = _SCRIPT_STYLE_RE.sub(" ", str(html or ""))
    return unescape(_TAG_RE.sub(" ", visible))[:limit]


def detect_block_signal(status_code, html):
    """纯函数：这一页是不是**真的被对方拒了**。是 → 'anti_bot'；否 → None。

    浏览器道（adapters/playwright_base）与 httpx 道（detect_page_state）共用这一份判据，
    避免两边各写各的、对同一页给出不同结论。
    """
    text = str(html or "")
    if status_code in _BLOCK_STATUS:
        return "anti_bot"
    if _CHALLENGE_INFRA_RE.search(text):
        return "anti_bot"
    if _looks_like_recruiting_page(text):
        return None
    title_match = _TITLE_RE.search(text)
    title = unescape(_TAG_RE.sub(" ", title_match.group(1))) if title_match else ""
    if _BLOCK_TEXT_RE.search(title) or _BLOCK_TEXT_RE.search(_visible_text(text, 4000)):
        return "anti_bot"
    return None


def detect_page_state(status_code, html):
    """纯函数：识别反爬、登录墙、公告/PDF 与未知 SPA 特殊态。"""
    text = str(html or "")
    lower = text.lower()
    blocked = detect_block_signal(status_code, text)
    if blocked:
        return blocked
    has_password = bool(re.search(r"<input[^>]+type=[\"']?password", text, re.I))
    has_login = bool(re.search(r"(登录|sign[ -]?in|log[ -]?in)", text, re.I))
    if has_password and has_login and not _JOB_SHAPE_RE.search(text):
        return "login_wall"
    pdf_links = re.findall(r"href=[\"'][^\"']+\.pdf(?:[?#][^\"']*)?[\"']", text, re.I)
    notice = bool(re.search(r"(招聘公告|公告附件|下载附件|notice)", text, re.I))
    if pdf_links and notice and not _JOB_SHAPE_RE.search(text):
        return "no_stable_jd"
    if (
        re.search(r"<div[^>]+id=[\"']app[\"']", text, re.I)
        or "__nuxt__" in lower
        or "__next_data__" in lower
    ):
        return "unknown_spa"
    return None


# ── 「再跳一跳」：公司官网的招聘栏目页 ≠ 岗位所在地 ────────────────────────────
# 2026-09-04 台账实证：no_stable_jd 52 家里 51 家判成 unknown_spa，而其中 5 家**当天被人工
# 接通了**——把漏斗看到的入口和真正有岗的地方并排放，形态完全一致：
#     掌阅科技    zhangyue.com/careers            → 岗位在 jobs.zhangyue.com（302 到飞书租户）
#     壳牌        shell.com.cn/zh_cn/careers      → 岗位在 jobs.shell.com（302 到 Workday）
#     同花顺      job.10jqka.com.cn/              → 岗位在 campus.10jqka.com.cn
# 漏斗停在「招聘介绍页」上等岗位数据，可那种页面**本来就没有岗位数据**，于是浏览器道回报
# anti_bot_blocked / 未拿到逐岗 URL（巴斯夫、壳牌各因此空撞 30 次）。这个标签是误导：
# 不是被反爬，是站错了页。
#
# ⚠️ 只做**自家招聘子域**这一跳，刻意不做「页面里的 ATS 链接」：
# detect_platform 已经会扫 HTML 里的第三方 ATS 域名（连不带 scheme 的裸 host 都认），
# 那条路早就通了，再写一遍是自欺的死代码。这里补的是它覆盖不到的那半 ——
# 子域名本身不是已知 ATS（jobs.zhangyue.com / jobs.shell.com 都不是），
# **价值全在「跟过去让它的 302 把我们带到 ATS」**，落地后 final_url 才认得出来。
#
# 🚫 2026-09-05 实网复盘：这一跳**对存量缺口基本没有产出，别再往这个方向加戏**。
# 逐个真探（httpx + 无头渲染各跑一遍）当时 46 家 no_stable_jd 的结果：
#   · httpx 原始 HTML：45 家抽出 0 个候选；唯一有候选的编程猫跳过去仍是 unknown_spa。
#   · 渲染之后再抽：**0 家**能跳到真 adapter（渲染只多救出同花顺一个候选域名）。
#   · 立项时举的 4 个例子全部失败，且是**两种它治不了的形态**：
#       巴斯夫/壳牌 = 岗位在**别的主域**（basf.jobs → successfactors、myworkdayjobs.com），
#                     被下面「同主域」这条规则按设计丢掉；
#       掌阅/同花顺 = 入口页是 SPA 空壳（原始 HTML 1.2~4.2 KB、外链 0~1 个），链接压根不在里面。
#   · 试过「同品牌跨顶级域」（basf.com → basf.jobs）的原型：50 家里只多救 1 家，而那家已人工接通。
# 真正卡住这批的不是「找不到岗位页」，是**浏览器道拿不到逐岗 URL**（19 家「未拦截到任何岗位
# 接口 JSON」+ 24 家「未拿到真实逐岗 URL」）。要提产出请去修 P2 与各 adapter，不是加 hop。
# 保留本函数：它对「链接确实在原始 HTML 里」的形态仍然正确，且已有单测钉住行为。
_CAREERS_SUBDOMAIN_RE = re.compile(
    r"^(?:job|jobs|career|careers|hr|campus|zhaopin|recruit|recruitment|talent|join)[a-z0-9-]*$",
    re.I,
)


def _registrable(host):
    """够用的主域近似：取末两段（.com.cn 这类取末三段）。只用于判「是不是自家子域」。"""
    parts = [p for p in str(host or "").lower().split(".") if p]
    if len(parts) < 2:
        return ""
    if len(parts) >= 3 and parts[-2] in {"com", "net", "org", "gov", "edu"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def find_careers_subdomain_hops(html, final_url, limit=3):
    """入口页 → 同主域下的招聘专用子域候选（去重保序）。抽不出返回 []。"""
    base_host = (urlparse(final_url or "").hostname or "").lower()
    base_root = _registrable(base_host)
    if not base_root:
        return []
    hops, seen = [], set()
    for raw in _URL_RE.findall(str(html or "")):
        parsed = _safe_urlparse(raw)
        host = ((parsed.hostname if parsed else "") or "").lower()
        if not host or host == base_host or _registrable(host) != base_root:
            continue
        if not _CAREERS_SUBDOMAIN_RE.match(host.split(".")[0]):
            continue
        url = "https://%s/" % host
        if url not in seen and len(hops) < limit:
            seen.add(url)
            hops.append(url)
    return hops


# ── 首屏 JS 包里的 ATS 租户地址 ────────────────────────────────────────────────
# 2026-09-18 实测：一批「自建招聘站」其实只是套了壳的 ATS 租户，租户地址不在 HTML 里、
# 在首屏 JS 包里（React/Vue 把「投递」按钮的目标写死在 bundle 里）：
#   talent.deepseek.com → app.mokahr.com/social-recruitment/high-flyer/…
#   www.zhangyue.com/careers → q7w8vltyes.jobs.feishu.cn/zhangyue
#   www.imdada.cn → app.mokahr.com/campus_apply/imdada/7841（租户页已下线，探活门会拦）
# HTML 扫描对它们全部判 unknown_spa → 漏斗记 adapter_source_url_unroutable，人去研究「怎么接
# 自建站」，而它们本来就有 adapter。这里补的是「再读几个 JS 包」这一跳，只在 HTML 认不出
# 平台、且页面像招聘页时做；找到的租户地址仍要**重新走一遍 fingerprint**（身份门 + 路由门
# 一个不跳），这里只负责把候选送到门前。
_SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*\bsrc=["']([^"']+)["']""", re.I)
_SCRIPT_BUNDLE_LIMIT = 5
_SCRIPT_BUNDLE_MAX_BYTES = 3 * 1024 * 1024


def find_script_bundle_urls(html, final_url, limit=_SCRIPT_BUNDLE_LIMIT):
    """入口页里**同一主域**下的 <script src>（绝对化、去重、保序）。
    只收自家域名：第三方 SDK（统计 / 客服 / 验证码）里的 ATS 域名是别家的，读了只会张冠李戴。"""
    base_root = _registrable(urlparse(final_url or "").hostname or "")
    if not base_root:
        return []
    out, seen = [], set()
    for raw in _SCRIPT_SRC_RE.findall(str(html or "")):
        url = _safe_urljoin(final_url, raw)
        if url is None:
            continue
        host = (urlparse(url).hostname or "").lower()
        if not host or _registrable(host) != base_root:
            continue
        if url not in seen and len(out) < limit:
            seen.add(url)
            out.append(url)
    return out


def find_ats_tenant_urls(text, limit=3):
    """从一段 JS/HTML 文本里抽「能路由到已有 adapter」的 ATS 租户地址（去 #fragment、去重、
    每个平台只留最短的一条——bundle 里同一租户会以 …#/job/{id} 形态出现几十次）。"""
    best = {}
    for raw in _URL_RE.findall(str(text or "")):
        url = raw.split("#", 1)[0].rstrip(");,'\"")
        parsed = _safe_urlparse(url)
        if parsed is None:
            continue
        platform, adapter = _host_detection(parsed.hostname, parsed.path)  or ("unknown", None)
        if not adapter:
            continue
        if platform == "moka" and not re.search(r"/(?:social-recruitment|campus-recruitment|campus_apply)/[^/]+/\d+$", parsed.path):
            continue   # moka 只认带 orgId 的租户页；sentry/静态资源等 mokahr.com 噪音一律丢
        # 飞书租户在 bundle 里常同时出现「历史专场 /2024」与「常设门户 /{path}/position」，
        # 优先带 /position 的；其余平台取最短（同一租户会以 …#/job/{id} 形态出现几十次）。
        rank = (0 if platform == "feishu" and "/position" in parsed.path else 1, len(url))
        current = best.get(platform)
        if current is None or rank < current[0]:
            best[platform] = (rank, url)
    return [url for _rank, url in best.values()][:limit]


def _looks_like_recruiting_page(html):
    """自建招聘页信号：有岗位列表形态，或可见文本里招聘词足够密集。"""
    source = str(html or "")
    if _JOB_SHAPE_RE.search(source):
        return True
    visible = _SCRIPT_STYLE_RE.sub(" ", source)
    visible = unescape(_TAG_RE.sub(" ", visible))[:12000]
    return len(_CAREERS_SIGNAL_RE.findall(visible)) >= 2


def _compact(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _spaced(value):
    """NFKC + casefold，非字母数字一律变成单个空格——保住词边界（_compact 会把它抹掉）。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)


def _latin_word_match(variant, spaced_text):
    """纯拉丁/数字的公司名必须按**词边界**出现（2026-09-23）。

    _compact 抹掉了空格，旧写法对它做子串匹配：「abb」命中 AbbVie / Abbott、「oppo」命中
    opportunities、「ups」命中 groups、「3m」命中 3mm。必投清单里 OPPO / vivo / SHEIN / TCL /
    ABB / 3M / DHL / UPS 八家全是纯英文名——ABB 的入口因此被记成了 careers.abbvie.com。
    字母之间允许夹分隔符（「Tesla China」对 teslachina），但两端必须不是字母数字；
    CJK 字符不算字母数字，所以「ABB中国」「TCL科技」照样命中。宁可漏判，不可认错公司。
    """
    if not variant:
        return False
    pattern = r"(?<![a-z0-9])" + r"\s?".join(re.escape(ch) for ch in variant) + r"(?![a-z0-9])"
    return re.search(pattern, spaced_text) is not None


def _company_variants(company):
    full = _compact(company)
    if not full:
        return []
    core = full
    changed = True
    while changed:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            compact_suffix = _compact(suffix)
            if core.endswith(compact_suffix) and len(core) > len(compact_suffix):
                core = core[:-len(compact_suffix)]
                changed = True
                break
    variants = [("full", full)]
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", core))
    latin_count = len(re.findall(r"[a-z0-9]", core))
    if core != full and (cjk_count >= 2 or (cjk_count == 0 and latin_count >= 3)):
        variants.append(("core", core))
    return variants


def _host_company_related(final_url, company):
    host = (urlparse(str(final_url or "")).hostname or "").lower()
    latin_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", str(company or "").casefold())
        if len(token) >= 3
    ]
    compact_host = host.replace("-", "").replace(".", "")
    return any(token in compact_host for token in latin_tokens)


def verify_page_identity(company, final_url, html):
    """纯函数：页面标题/正文前 3000 字必须出现公司全名或安全核心词。"""
    if not str(company or "").strip():
        return (True, "company_not_provided")
    source = str(html or "")
    title_match = _TITLE_RE.search(source)
    title = unescape(_TAG_RE.sub(" ", title_match.group(1))) if title_match else ""
    visible = _SCRIPT_STYLE_RE.sub(" ", source)
    visible = unescape(_TAG_RE.sub(" ", visible))[:3000]
    title_compact = _compact(title)
    body_compact = _compact(visible)
    spaced = _spaced(title) + " " + _spaced(visible)
    host_related = _host_company_related(final_url, company)
    for kind, variant in _company_variants(company):
        if not variant:
            continue
        if _CJK_RE.search(variant):
            matched = variant in title_compact or variant in body_compact
        else:
            matched = _latin_word_match(variant, spaced)
        if matched:
            reason = "page_company_match:%s" % kind
            if host_related:
                reason += "+host_related"
            return (True, reason)
    return (False, "page_company_not_found")


def _adapter_api_url(platform, candidate):
    parsed = _safe_urlparse(candidate)
    if parsed is None:
        return None
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if platform == "greenhouse":
        if host == "boards-api.greenhouse.io" and "/v1/boards/" in parsed.path:
            return candidate
        if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and parts:
            return "https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % parts[0]
    if platform == "lever":
        if host == "api.lever.co" and parsed.path.startswith("/v0/postings/"):
            return candidate
        if host == "jobs.lever.co" and parts:
            return "https://api.lever.co/v0/postings/%s?mode=json" % parts[0]
    if platform == "ashby":
        if host == "api.ashbyhq.com" and "/posting-api/job-board/" in parsed.path:
            return candidate
        if host == "jobs.ashbyhq.com" and parts:
            return (
                "https://api.ashbyhq.com/posting-api/job-board/%s"
                "?includeCompensation=true" % parts[0]
            )
    if platform == "smartrecruiters":
        if host == "api.smartrecruiters.com" and "/v1/companies/" in parsed.path:
            return candidate
        if host == "jobs.smartrecruiters.com" and parts:
            return (
                "https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100"
                % parts[0]
            )
    if platform == "workday":
        if "/wday/cxs/" in parsed.path and parsed.path.rstrip("/").endswith("/jobs"):
            return candidate
        match = re.match(r"^([^.]+)\.wd\d+\.myworkdayjobs\.com$", host, re.I)
        if match and len(parts) >= 2:
            site_index = 1 if re.match(r"^[a-z]{2}-[A-Z]{2}$", parts[0]) else 0
            if site_index < len(parts):
                site = parts[site_index]
                return "https://%s/wday/cxs/%s/%s/jobs" % (
                    host, match.group(1), site
                )
    if platform == "oracle":
        if "/hcmrestapi/resources/" in parsed.path.lower():
            query = parsed.query or ""
            if "siteNumber=" in query:
                return candidate
        try:
            site_index = [part.lower() for part in parts].index("sites") + 1
        except ValueError:
            site_index = len(parts)
        if site_index < len(parts):
            site = parts[site_index]
            return (
                "https://%s/hcmRestApi/resources/latest/"
                "recruitingCEJobRequisitions?finder=findReqs;siteNumber=%s"
                % (host, site)
            )
    if platform == "eightfold":
        query = parse_qs(parsed.query or "")
        domain = (query.get("domain") or [""])[0]
        if domain:
            return "https://%s/api/apply/v2/jobs?domain=%s" % (host, domain)
    if platform == "hotjob":
        portal = re.match(
            r"^/([^/]+)/pb/(social|school|interns)\.html$",
            parsed.path,
            re.I,
        )
        if portal:
            return candidate
        # 租户首页 `/{SU…}/pb/index.html`（或裸 `/pb/`）：官网「加入我们」常直接 302 到这里
        # （宇通 join.yutong.com、财通 www.ctsec.com/careers 都是），页面本身不带任何板块。
        # 它与 social.html 是同一个租户、同一个 suite key，只差板块后缀 —— 2026-09-18 之前
        # 这里返回 None → 漏斗记 adapter_source_url_unroutable，财通 208 岗 / 卓越 661 岗
        # 就这么被挡在门外。校招板块由 gap_funnel.campus_source_url 按同一套规则换算。
        landing = re.match(r"^/([^/]+)/pb/?(?:index\.html)?$", parsed.path, re.I)
        if landing:
            return "https://%s/%s/pb/social.html" % (host, landing.group(1))
        endpoint = re.search(
            r"/wecruit/positionInfo/listPosition/([^/?#]+)",
            parsed.path,
            re.I,
        )
        if endpoint:
            return "https://%s/%s/pb/social.html" % (host, endpoint.group(1))
    if platform == "iguopin":
        query = parse_qs(parsed.query or "")
        if parsed.path.rstrip("/") == "/job" and (query.get("company") or [""])[0].strip():
            return candidate
    return None


def resolve_source_url(platform, final_url, html):
    """把公开职位页归一成现有 adapter 真正消费的列表/API URL。"""
    if platform == "hotjob":
        final_api = _adapter_api_url(platform, final_url)
        if final_api:
            return final_api
    # final_url 必须排在最前：它是我们**实际访问到、且过了身份核验**的页面，最可信。
    # 排在 HTML 扫出来的 URL 后面会被同域垃圾抢先——实测万泰生物的 moka 源地址被判成
    # sentry-fe.mokahr.com/api/107/store/（前端错误监控 SDK 的上报地址，host 恰好含 mokahr.com），
    # P2 拿它去抓自然 0 个岗。页面里的第三方 SDK/CDN/静态资源域名普遍带主域，这类污染是常态。
    candidates = [final_url]
    candidates.extend(
        url.rstrip(");,") for url in _URL_RE.findall(str(html or ""))
    )
    for candidate in candidates:
        api_url = _adapter_api_url(platform, candidate)
        if api_url:
            return api_url
    if platform == "hotjob":
        relative = re.search(
            r"/wecruit/positionInfo/listPosition/([A-Za-z0-9_-]+)",
            str(html or ""),
            re.I,
        )
        parsed_final = urlparse(str(final_url or ""))
        if relative and parsed_final.hostname:
            return "https://%s/%s/pb/social.html" % (
                parsed_final.hostname,
                relative.group(1),
            )
    if platform in ("oracle", "eightfold", "iguopin", "hotjob"):
        return None
    for candidate in candidates:
        if detect_platform(candidate, "")[0] == platform:
            return candidate
    return final_url


def _ats_urls_in_script_bundles(cli, html, final_url, timeout):
    """拉最多 _SCRIPT_BUNDLE_LIMIT 个自家 JS 包，返回其中的 ATS 租户地址（去重保序）。
    任何一个包拉不下来就跳过它；这一步只可能把 unknown 变成已知，不会反过来。"""
    found, seen = [], set()
    for script_url in find_script_bundle_urls(html, final_url):
        try:
            resp = cli.get(script_url, timeout=timeout)
        except Exception:  # noqa: BLE001
            continue
        text = getattr(resp, "text", "") or ""
        if int(getattr(resp, "status_code", 0) or 0) != 200 or len(text) > _SCRIPT_BUNDLE_MAX_BYTES:
            continue
        for tenant_url in find_ats_tenant_urls(text):
            if tenant_url not in seen:
                seen.add(tenant_url)
                found.append(tenant_url)
    return found


def fingerprint(url, *, company=None, client=None, timeout=15, _hop_depth=0):
    """GET 招聘入口并返回平台、adapter、可探活 URL 与判定证据。失败重试一次。

    认不出平台时会**再跳一跳**（深度 1）：公司官网的招聘栏目页常常只是介绍页，
    真正的岗位板常在另一个域（自家 job*/campus* 子域）。适用范围与实测产出见
    find_careers_subdomain_hops 上方的注释——**它对存量缺口产出接近 0，别再加戏**。
    """
    own_client = client is None
    cli = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.8"},
    )
    response = None
    last_error = None
    try:
        for _attempt in range(2):
            try:
                response = cli.get(url, timeout=timeout)
                break
            except Exception as exc:
                last_error = exc
        if response is None:
            return {
                "platform": "unknown",
                "adapter": None,
                "source_url": None,
                "reason": "fetch_failed:%s" % (
                    type(last_error).__name__ if last_error else "unknown"
                ),
                "http_status": None,
                "identity_ok": False,
                "identity_reason": "fetch_failed",
            }

        final_url = str(getattr(response, "url", None) or url)
        html = getattr(response, "text", "") or ""
        status = int(getattr(response, "status_code", 0) or 0)
        identity_ok, identity_reason = verify_page_identity(
            company, final_url, html
        )
        special = detect_page_state(status, html)
        platform, adapter = detect_platform(final_url, html)
        if (
            special is None
            and identity_ok
            and platform == "unknown"
            and _looks_like_recruiting_page(html)
        ):
            special = "unknown_spa"
        # 认不出平台 → 先别急着判 unknown_spa/anti_bot，**从这一页找去岗位板的下一跳**。
        # 只在深度 0 做，且只接受「跳过去真认出了 ATS」的结果；跳不到就按原路返回，
        # 不改变任何既有判定（fail-safe：这一步只可能把 unknown 变成已知，不会反过来）。
        # 前置条件刻意**不要求入口页的身份校验通过**：恰恰是这种「薄介绍页」验不出身份
        # （掌阅的 zhangyue.com 与「掌阅科技」字面不重叠），要求它就等于把这条路堵死。
        # 真正的门在下游、而且更硬：gap_funnel 先插 disabled 源 → 真抓一轮 →
        # 回读香港库确认有健康岗才 enable。这里只负责把候选送到那道门前。
        if platform == "unknown" and _hop_depth == 0 and _looks_like_recruiting_page(html):
            for hop in find_careers_subdomain_hops(html, final_url):
                try:
                    hopped = fingerprint(
                        hop, company=company, client=cli, timeout=timeout, _hop_depth=1
                    )
                except Exception:  # noqa: BLE001 —— 下一跳探测失败不许拖垮主判定
                    continue
                if hopped.get("adapter"):
                    hopped["reason"] = "careers_subdomain_hop_from:%s" % final_url
                    return hopped
        # 仍认不出 → 读自家首屏 JS 包找 ATS 租户地址（见 find_script_bundle_urls 上方注释）。
        # 同样只在深度 0 做、只接受「跳过去真认出了 ATS 且过了身份门」的结果。
        # 不要求「像招聘页」：这类壳常常只有几百字节（talent.deepseek.com 580 B），
        # 招聘词全在 JS 里；花销由「只读自家域名、最多 5 个包」兜住。
        if platform == "unknown" and _hop_depth == 0:
            for tenant_url in _ats_urls_in_script_bundles(cli, html, final_url, timeout):
                try:
                    hopped = fingerprint(
                        tenant_url, company=company, client=cli, timeout=timeout, _hop_depth=1
                    )
                except Exception:  # noqa: BLE001 —— 租户页探测失败不许拖垮主判定
                    continue
                if hopped.get("adapter") and hopped.get("identity_ok") is True:
                    hopped["reason"] = "ats_in_script_bundle_from:%s" % final_url
                    return hopped
        # 已识别 ATS 的普通 SPA 壳仍交给 adapter；unknown_spa 只接住认不出的壳。
        if special and (special != "unknown_spa" or platform == "unknown"):
            return {
                "platform": special,
                "adapter": None,
                "source_url": final_url,
                "reason": special,
                "http_status": status,
                "identity_ok": identity_ok,
                "identity_reason": (
                    identity_reason
                    if identity_ok
                    else "identity_unverifiable:%s" % special
                ),
            }
        return {
            "platform": platform,
            "adapter": adapter,
            "source_url": resolve_source_url(platform, final_url, html) if adapter else None,
            "reason": "host_or_html_fingerprint" if platform != "unknown" else "unrecognized",
            "http_status": status,
            "identity_ok": identity_ok,
            "identity_reason": identity_reason,
        }
    finally:
        if own_client:
            cli.close()
