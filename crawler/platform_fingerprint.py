"""招聘入口平台指纹。只做公开页面 GET，不绕验证码或登录态。"""
import re
import unicodedata
from html import unescape
from urllib.parse import parse_qs, urlparse

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


def detect_platform(final_url, html):
    """纯函数：最终 host → HTML 第三方 host → 接口路径特征。"""
    parsed = urlparse(str(final_url or ""))
    direct = _host_detection(parsed.hostname, parsed.path)
    if direct:
        return direct

    text = str(html or "")
    for candidate in _URL_RE.findall(text):
        embedded = urlparse(candidate.rstrip(");,"))
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


def detect_page_state(status_code, html):
    """纯函数：识别反爬、登录墙、公告/PDF 与未知 SPA 特殊态。"""
    text = str(html or "")
    lower = text.lower()
    if status_code in (403, 412, 503):
        return "anti_bot"
    if (
        "access denied" in lower
        or "cloudflare challenge" in lower
        or "cf-chl-" in lower
        or ("akamai" in lower and ("challenge" in lower or "denied" in lower))
        or ("请开启javascript" in lower and "/api/" not in lower)
    ):
        return "anti_bot"
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
    host_related = _host_company_related(final_url, company)
    for kind, variant in _company_variants(company):
        if variant and (variant in title_compact or variant in body_compact):
            reason = "page_company_match:%s" % kind
            if host_related:
                reason += "+host_related"
            return (True, reason)
    return (False, "page_company_not_found")


def _adapter_api_url(platform, candidate):
    parsed = urlparse(str(candidate or ""))
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


def fingerprint(url, *, company=None, client=None, timeout=15):
    """GET 招聘入口并返回平台、adapter、可探活 URL 与判定证据。失败重试一次。"""
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
