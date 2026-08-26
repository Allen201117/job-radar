"""零搜索额度的招聘入口发现：公司官网首页 → 招聘候选链接。"""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from threading import Lock
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

import company_name_match
import db
import platform_fingerprint
import wikidata


_TIMEOUT = 15
_MAX_GETS = 24
_MAX_CONCURRENT_GETS = 8
_CAREER_SUBDOMAINS = (
    "careers", "jobs", "job", "hr", "zhaopin", "recruit", "talent",
    "join", "campus", "hire", "joinus",
)
_COMMON_PATHS = (
    "/careers", "/career", "/jobs", "/job", "/join", "/join-us",
    "/joinus", "/recruitment", "/recruit", "/zhaopin", "/hr", "/about/join",
)
_CAREER_CONTENT_KEYWORDS = (
    "招聘", "职位", "岗位", "careers", "jobs", "社会招聘", "校园招聘",
    "join us", "recruit", "应聘", "投递",
)
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


def career_entry_candidates(home_url: str) -> list[str]:
    """由官网域名生成候选招聘入口 URL（子域 + 路径），按命中概率排序，不发网络请求。"""
    home_url = _http_url(home_url)
    if not home_url:
        return []
    parsed = urlparse(home_url)
    registered = _registered_domain(parsed.hostname)
    if not registered:
        return []
    origin = "%s://%s" % (parsed.scheme, parsed.netloc)
    candidates = [
        "%s://%s.%s/" % (parsed.scheme, subdomain, registered)
        for subdomain in _CAREER_SUBDOMAINS
    ]
    candidates.extend(urljoin(origin + "/", path) for path in _COMMON_PATHS)
    seen = set()
    return [url for url in candidates if not (url in seen or seen.add(url))]


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
    """返回官网 URL 与来源通道；按本地表 → sources → Wikidata → LLM 静默降级。"""
    company_key = str(company or "").strip().lower()
    try:
        import logo_util

        domain = (logo_util.COMPANY_DOMAIN_OVERRIDES or {}).get(company_key)
        home_url = _http_url("https://%s/" % str(domain or "").strip().strip("/"))
        if home_url:
            return {
                "home_url": home_url,
                "entry_channel": "verified_domain_table",
            }
    except Exception:
        pass

    if source_rows is None:
        try:
            sb = supabase or db.get_supabase()
            rows = db.fetch_all_rows(
                lambda: sb.table("sources").select(
                    "id,company,source_url,enabled"
                ).eq("enabled", True)
            )
        except Exception:
            rows = []
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
    if matches:
        return {
            "home_url": max(matches)[-1],
            "entry_channel": "existing_source_host",
        }

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

    llm_site = resolve_official_site_by_llm(company)
    if llm_site:
        return {"home_url": llm_site, "entry_channel": "llm_domain"}
    return None


# LLM 补域名的进程内缓存：同一轮里同名公司只问一次。
_LLM_DOMAIN_CACHE: dict = {}


def resolve_official_site_by_llm(company):
    """本地域名表、库内 source、Wikidata 都拿不到时，用 LLM 补官方主域名。

    为何必须有这一步（2026-07-27 实测）：Wikidata 按**中文名**查 QID 命中率只有 ~58%
    （125 家缺口里只解出 73 家；中信证券/龙湖/同花顺这些手工一查就有的它都判「无官网」），
    剩下的全部掉回搜索通道 —— 台账实锤那一轮 45 家里 34 家走了 search、只有 10 家走官网通道，
    等于官网通道白做。同一批 52 家丢给 LLM，52/52 全给出正确主域名
    （ccb.com / citics.com / 10jqka.com.cn / huahong.com.cn / estun.com …），
    再扒首页多命中 23 家入口。

    安全性：LLM 编错域名不会造成脏数据——后面还有页面身份门 + 真抓回读健康岗两道关，
    编造的域名要么打不开、要么身份对不上，自动丢弃。
    未配 SILICONFLOW_API_KEY 或调用失败 → 返回 None，静默回落搜索通道。
    """
    key = str(company or "").strip()
    if not key:
        return None
    if key in _LLM_DOMAIN_CACHE:
        return _LLM_DOMAIN_CACHE[key]
    site = None
    if os.environ.get("GAP_FUNNEL_LLM_DOMAIN", "true").lower() not in ("0", "false", "no", "off"):
        try:
            import insight_engine

            data = insight_engine.chat_json(
                [
                    {"role": "system", "content": "你是企业信息助手，只输出 JSON。"},
                    {"role": "user", "content":
                        "给出这家公司的**官方主域名**（不是招聘站、不是百科、不是新闻、不是招聘平台）。"
                        "不确定就填 null，绝不编造。只输出 {\"site\": \"https://域名\" 或 null}。\n"
                        f"公司：{key}"},
                ],
                max_tokens=200,
            )
            if isinstance(data, dict):
                site = _http_url(data.get("site"))
        except Exception:
            site = None
    _LLM_DOMAIN_CACHE[key] = site
    return site


def resolve_official_site(company, *, client=None):
    """公司名 → 官网 URL；本地域名表、已有 source host、Wikidata 依次兜底。"""
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


def _has_career_content(final_url, html):
    if _CAREERS_RE.search(str(final_url or "")):
        return True
    content = str(html or "").casefold()
    return sum(keyword.casefold() in content for keyword in _CAREER_CONTENT_KEYWORDS) >= 2


def find_careers_links(company, home_url, *, client=None):
    """GET 官网并合并首页锚点与招聘模板候选，总 GET 不超过 24。"""
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
    requests_lock = Lock()

    def fetch(url, *, attempts=2):
        nonlocal requests_used
        for _attempt in range(attempts):
            with requests_lock:
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
            except Exception:
                continue
            if int(getattr(response, "status_code", 0) or 0) == 200:
                return response
        return None

    try:
        response = fetch(home_url)
        base_url = (
            _http_url(getattr(response, "url", None)) if response is not None else None
        ) or home_url
        candidates = []
        if response is not None:
            candidates = _extract_candidates(
                getattr(response, "text", ""), base_url, base_url
            )

        template_urls = career_entry_candidates(base_url)[:max(0, _MAX_GETS - requests_used)]
        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_GETS) as executor:
            responses = list(executor.map(
                lambda url: fetch(url, attempts=1), template_urls
            ))
            retry_indexes = [
                index for index, response in enumerate(responses)
                if response is None
            ][:max(0, _MAX_GETS - requests_used)]
            if retry_indexes:
                retries = list(executor.map(
                    lambda index: fetch(template_urls[index], attempts=1), retry_indexes
                ))
                for index, response in zip(retry_indexes, retries):
                    if response is not None:
                        responses[index] = response
        next_index = len(candidates)
        for candidate_url, response in zip(template_urls, responses):
            if response is None:
                continue
            final_url = _http_url(getattr(response, "url", None)) or candidate_url
            html = getattr(response, "text", "")
            if not _has_career_content(final_url, html):
                continue
            score, reason = _candidate_score(base_url, final_url)
            candidates.append({
                "url": final_url,
                "text": "",
                "href": candidate_url,
                "score": score,
                "reason": reason,
                "source_page": final_url,
                "_index": next_index,
            })
            next_index += 1
            for item in _extract_candidates(html, final_url, base_url):
                item["_index"] = next_index
                candidates.append(item)
                next_index += 1
        return _rank_candidates(candidates)
    finally:
        if own_client:
            cli.close()
