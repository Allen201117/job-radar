"""零搜索额度的招聘入口发现：公司官网首页 → 招聘候选链接。"""
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

import company_name_match
import db
import platform_fingerprint
import wikidata


_TIMEOUT = 15
_MAX_GETS = 8
_COMMON_PATHS = ("/careers", "/join", "/jobs", "/zhaopin", "/about/join")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,en;q=0.8",
}
_CAREERS_RE = re.compile(
    r"(招聘|人才|加入我们|招贤|工作机会|"
    r"\bcareers?\b|\bjoin[\W_]?us\b|\bjobs?\b|\brecruit(?:ment|ing)?\b|"
    r"\btalent\b|\bzhaopin\b|(?:^|[^a-z])hr(?:[^a-z]|$))",
    re.I,
)
_COMPOUND_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn",
    "com.hk", "com.tw", "co.uk", "co.jp", "com.au",
}


def _http_url(value):
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.hostname else None


def _registered_domain(host):
    parts = [part for part in str(host or "").lower().rstrip(".").split(".") if part]
    if len(parts) <= 2:
        return ".".join(parts)
    suffix2 = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if suffix2 in _COMPOUND_SUFFIXES else suffix2


def _same_or_near_company(source_company, company):
    left = str(source_company or "").strip()
    right = str(company or "").strip()
    if not left or not right:
        return False
    compact_left = re.sub(r"[\W_]+", "", left.casefold())
    compact_right = re.sub(r"[\W_]+", "", right.casefold())
    if compact_left == compact_right:
        return True
    if company_name_match.company_name_matches(left, right):
        return True
    if company_name_match.company_name_matches(right, left):
        return True
    shorter, longer = sorted((compact_left, compact_right), key=len)
    return len(shorter) >= 4 and shorter in longer


def _source_home_url(source_url):
    parsed = urlparse(str(source_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return "%s://%s/" % (parsed.scheme, parsed.netloc)


def resolve_official_site_details(
    company, *, client=None, supabase=None, source_rows=None
):
    """返回官网 URL 与来源通道；异常按 Wikidata → sources 顺序静默降级。"""
    own_client = client is None
    cli = client or httpx.Client(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers=_HEADERS,
    )
    try:
        try:
            qid = wikidata.search_qid(company, cli)
            if qid:
                data = wikidata._get(
                    {
                        "action": "wbgetentities",
                        "ids": qid,
                        "props": "claims|labels",
                        "languages": "zh|zh-hans|en",
                    },
                    cli,
                )
                entity = (data.get("entities") or {}).get(qid)
                if entity:
                    official_site = _http_url(
                        wikidata.parse_company_facts(entity, {}).get("official_site")
                    )
                    if official_site:
                        return {
                            "home_url": official_site,
                            "entry_channel": "wikidata_site",
                        }
        except Exception:
            pass
    finally:
        if own_client:
            cli.close()

    if source_rows is None:
        try:
            sb = supabase or db.get_supabase()
            rows = db.fetch_all_rows(
                lambda: sb.table("sources").select(
                    "id,company,source_url,enabled"
                ).eq("enabled", True)
            )
        except Exception:
            return None
    else:
        rows = list(source_rows)

    matches = []
    target = re.sub(r"[\W_]+", "", str(company or "").casefold())
    for index, row in enumerate(rows):
        if row.get("enabled") is False:
            continue
        source_company = str(row.get("company") or "").strip()
        if not _same_or_near_company(source_company, company):
            continue
        home_url = _source_home_url(row.get("source_url"))
        if not home_url:
            continue
        source_key = re.sub(r"[\W_]+", "", source_company.casefold())
        matches.append((
            1 if source_key == target else 0,
            1 if row.get("enabled") else 0,
            -index,
            home_url,
        ))
    if not matches:
        return None
    home_url = max(matches)[-1]
    return {
        "home_url": home_url,
        "entry_channel": "existing_source_host",
    }


def resolve_official_site(company, *, client=None):
    """公司名 → 官网 URL；Wikidata P856 优先，已有 source host 次之。"""
    result = resolve_official_site_details(company, client=client)
    return result["home_url"] if result else None


def _is_ats_host(host):
    host = str(host or "").lower().rstrip(".")
    if not host:
        return False
    return platform_fingerprint.detect_platform(
        "https://%s/" % host, ""
    )[0] != "unknown"


def _candidate_score(home_url, candidate_url):
    home_host = (urlparse(home_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    if (
        candidate_host != home_host
        and _registered_domain(candidate_host) == _registered_domain(home_host)
    ):
        return 300, "same_site_subdomain"
    if candidate_host == home_host:
        return 200, "same_host_path"
    if _is_ats_host(candidate_host):
        return 120, "external_ats"
    return 100, "external"


def _extract_candidates(html, page_url, home_url):
    try:
        anchors = HTMLParser(str(html or "")).css("a")
    except Exception:
        return []
    candidates = []
    seen = set()
    for index, anchor in enumerate(anchors):
        href = unescape(str(anchor.attributes.get("href") or "").strip())
        text = str(anchor.text(separator=" ", strip=True) or "").strip()
        if not href or not (_CAREERS_RE.search(text) or _CAREERS_RE.search(href)):
            continue
        url = _http_url(urljoin(page_url, href))
        if not url or url in seen:
            continue
        seen.add(url)
        score, reason = _candidate_score(home_url, url)
        candidates.append({
            "url": url,
            "text": text,
            "href": href,
            "score": score,
            "reason": reason,
            "source_page": page_url,
            "_index": index,
        })
    return candidates


def _rank_candidates(items):
    seen = set()
    unique = []
    for item in items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    unique.sort(key=lambda item: (-item["score"], item.get("_index", 0)))
    return [
        {key: value for key, value in item.items() if key != "_index"}
        for item in unique[:5]
    ]


def find_careers_links(company, home_url, *, client=None):
    """GET 官网并抽招聘链接；无首页命中时试常见路径，总 GET（含重试）不超过 8。"""
    del company  # 身份核验统一交给下游 platform_fingerprint。
    home_url = _http_url(home_url)
    if not home_url:
        return []
    own_client = client is None
    cli = client or httpx.Client(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers=_HEADERS,
    )
    requests_used = 0

    def fetch(url):
        nonlocal requests_used
        for _attempt in range(2):
            if requests_used >= _MAX_GETS:
                return None
            requests_used += 1
            try:
                response = cli.get(
                    url,
                    timeout=_TIMEOUT,
                    follow_redirects=True,
                    headers=_HEADERS,
                )
                if int(getattr(response, "status_code", 0) or 0) >= 400:
                    continue
                return response
            except Exception:
                continue
        return None

    try:
        response = fetch(home_url)
        base_url = (
            _http_url(getattr(response, "url", None)) if response is not None else None
        ) or home_url
        if response is not None:
            candidates = _extract_candidates(
                getattr(response, "text", ""), base_url, base_url
            )
            if candidates:
                return _rank_candidates(candidates)

        parsed = urlparse(base_url)
        origin = "%s://%s/" % (parsed.scheme, parsed.netloc)
        for path in _COMMON_PATHS:
            path_url = urljoin(origin, path)
            response = fetch(path_url)
            if response is None:
                continue
            final_url = _http_url(getattr(response, "url", None)) or path_url
            html = getattr(response, "text", "")
            candidates = _extract_candidates(html, final_url, base_url)
            if (
                _CAREERS_RE.search(final_url)
                or _CAREERS_RE.search(unescape(str(html or "")))
            ):
                score, reason = _candidate_score(base_url, final_url)
                candidates.insert(0, {
                    "url": final_url,
                    "text": "",
                    "href": path,
                    "score": score,
                    "reason": reason,
                    "source_page": final_url,
                    "_index": -1,
                })
            if candidates:
                return _rank_candidates(candidates)
        return []
    finally:
        if own_client:
            cli.close()
