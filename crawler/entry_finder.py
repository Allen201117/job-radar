"""官方招聘入口发现：按 provider 级联搜索，首个可信入口即停。"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import search_router


_THIRD_PARTY_HOSTS = (
    "zhaopin.com", "liepin.com", "51job.com", "zhipin.com", "lagou.com",
    "jobui.com", "jobui.cn", "kanzhun.com", "job592.com", "linkedin.com",
    "indeed.com", "maimai.cn", "nowcoder.com", "leetcode.cn", "leetcode.com",
    "recruit.net", "bebee.com", "wondercv.com", "superjianli.com",
    "shixiseng.com", "yinhangzhaopin.com", "yingjiesheng.com", "dajie.com",
    "saramin.co.kr", "glassdoor.com", "monster.com",
    # 牛企招聘：实测赛力斯、福耀玻璃的「官方入口」被判到了 jobs.niuqizp.com 上。
    "niuqizp.com",
)
_CONTENT_HOSTS = (
    "zhihu.com", "csdn.net", "sohu.com", "weixin.qq.com", "jianshu.com",
    "baijiahao.baidu.com",
    # 企业工商信息站不是招聘入口：实测华谊兄弟/柠萌影业/正午阳光三家的 official_entry_url
    # 被判成了 aiqicha.baidu.com/details/…（爱企查），白跑一轮还被记成 no_stable_jd。
    # 上面 baidu.com 的特判只挡 /baike，爱企查走 /details 从这个缝里漏了过去。
    "aiqicha.baidu.com", "qcc.com", "tianyancha.com", "qixin.com",
)
_CAMPUS_REPOST_HOSTS = (
    "ncss.cn", "career.tsinghua.edu.cn", "scc.pku.edu.cn",
    "career.pku.edu.cn", "job.xjtu.edu.cn",
)
_AGGREGATOR_HOSTS = (
    "bendibao.com", "gaoxiaojob.com", "yingjiesheng.com", "chinahr.com",
    "job5156.com", "ppkao.com",
)
_ATS_HOSTS = (
    ("mokahr.com", "moka"),
    ("zhiye.com", "beisen"),
    ("italent.cn", "italent"),
    ("hotjob.cn", "hotjob"),
    ("dayee.com", "dayee"),
    ("myworkdayjobs.com", "workday"),
    ("successfactors", "successfactors"),
    ("sapsf", "successfactors"),
    ("eightfold.ai", "eightfold"),
    ("oraclecloud.com", "oracle"),
    ("avature.net", "avature"),
    ("taleo.net", "taleo"),
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("feishu.cn", "feishu"),
    ("iguopin.com", "iguopin"),
)
_PATH_TOKEN_RE = re.compile(r"(?:^|[/_.-])(job|jobs|career|careers|recruit|recruitment|zhaopin|hr|campus)(?:[/_.-]|$)", re.I)
# 招聘子域（host 以此开头）：careers.midea.com / hr.vivo.com / zhaopin.jd.com / join.xxx.com
_CAREER_SUBDOMAIN_RE = re.compile(
    r"^(?:m\.|www\.)?(job|jobs|career|careers|recruit|recruitment|zhaopin|hr|campus|talent|join|apply|hire)\.",
    re.I,
)
_CONTENT_PATH_RE = re.compile(r"(?:^|/)(baike|wiki|news|article|encyclopedia)(?:/|$)", re.I)
_COMPANY_STOP = {
    "co", "company", "corp", "corporation", "group", "holding", "holdings",
    "inc", "limited", "ltd", "the",
}


def _host_matches(host, domain):
    return host == domain or host.endswith("." + domain)


def _ats_host_matches(host, token):
    if "." in token:
        return _host_matches(host, token)
    return token in host.split(".")


def classify_candidate_url(url, company):
    """纯函数：返回 (verdict, score, reason)。"""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return ("reject", -100, "invalid_url")
    host = (parsed.hostname or "").lower().rstrip(".")
    path = (parsed.path or "/").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return ("reject", -100, "invalid_url")

    if host.endswith(".edu.cn") or host.endswith(".edu"):
        return ("reject", -100, "institutional_host")
    if host.endswith(".gov.cn"):
        return ("reject", -100, "government_notice")
    for domain in _AGGREGATOR_HOSTS:
        if _host_matches(host, domain):
            return ("reject", -100, "aggregator_site")

    # 国聘是创始人确认的唯一第三方平台例外。
    if _host_matches(host, "iguopin.com"):
        query = parse_qs(parsed.query or "")
        if path.rstrip("/") == "/job" and (query.get("company") or [""])[0].strip():
            return ("trusted_ats", 100, "trusted_ats:iguopin")
        return ("reject", -100, "iguopin_search_page")
    for domain in _THIRD_PARTY_HOSTS:
        if _host_matches(host, domain):
            return ("reject", -100, "third_party_job_platform")
    if _host_matches(host, "baidu.com") and path.startswith("/baike"):
        return ("reject", -95, "content_site")
    if _host_matches(host, "163.com") and (
        host.startswith("news.") or path.startswith("/news") or _CONTENT_PATH_RE.search(path)
    ):
        return ("reject", -95, "content_site")
    for domain in _CONTENT_HOSTS:
        if _host_matches(host, domain):
            return ("reject", -95, "content_site")
    for domain in _CAMPUS_REPOST_HOSTS:
        if _host_matches(host, domain):
            return ("reject", -95, "campus_repost")
    if _CONTENT_PATH_RE.search(path):
        return ("reject", -90, "news_or_encyclopedia_path")

    for token, platform in _ATS_HOSTS:
        if _ats_host_matches(host, token):
            return ("trusted_ats", 100, "trusted_ats:" + platform)

    score = 0
    reasons = []
    if _PATH_TOKEN_RE.search(path):
        score += 55
        reasons.append("career_path")
    # 招聘子域本身就是强官方信号：中国公司的官方招聘站大量是 careers./hr./zhaopin./job(s). 开头、
    # 路径却是根「/」（实测 careers.midea.com 就因此被判 insufficient_official_signal 误杀）。
    # 且中文公司名切不出 latin 词 → 下面的 company_host 对它们永远不生效，只靠 path 会漏掉一大批。
    # 放宽是安全的：真正判「这页是不是这家公司」的是 fingerprint 里的页面身份门。
    if _CAREER_SUBDOMAIN_RE.match(host):
        score += 55
        reasons.append("career_subdomain")
    words = [
        word for word in re.findall(r"[a-z0-9]+", str(company or "").lower())
        if len(word) >= 3 and word not in _COMPANY_STOP
    ]
    compact = "".join(words)
    if (compact and compact in host.replace("-", "")) or any(word in host for word in words):
        score += 35
        reasons.append("company_host")
    if score > 0:
        return ("likely_official", score, "+".join(reasons))
    return ("reject", -10, "insufficient_official_signal")


def _provider_plan(router, supabase):
    providers = list(getattr(router, "providers", []) or [])
    available = []
    for provider in providers:
        try:
            if provider.is_configured() and not search_router.provider_blacklisted(provider):
                remaining = int(provider.remaining(supabase))
                if remaining > 0:
                    available.append((provider, remaining))
        except Exception:
            continue
    qianfan = next(
        (provider for provider, _remaining in available
         if getattr(provider, "name", "") == "qianfan"),
        None,
    )
    http_candidates = [
        (provider, remaining) for provider, remaining in available
        if getattr(provider, "name", "") != "qianfan"
    ]
    http_candidates.sort(
        key=lambda item: (-item[1], str(getattr(item[0], "name", "")))
    )
    fallback = http_candidates[0][0] if http_candidates else None
    return [provider for provider in (qianfan, fallback) if provider]


def _search_one(provider, supabase, query, top_k, client, consume):
    try:
        results = provider.search(query, top_k, client) or []
    except search_router.SearchAccountError as exc:
        search_router.blacklist_provider(provider, exc)
        results = []
        error = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    except Exception as exc:
        results = []
        error = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    else:
        error = None
        if consume:
            provider.consume(supabase, 1)
    return results, error


def find_official_entry(company, supabase, *, router=None, prev_row=None,
                        top_k=8, client=None, max_searches=2, now=None,
                        consume=True):
    """搜索单家公司；每轮最多两次，返回入口与台账失败态字段。"""
    router = router or search_router.default_router()
    now = now or datetime.now(timezone.utc)
    queries = [
        "%s 招聘 官网" % company,
        "%s 社会招聘 职位" % company,
    ]
    plan = _provider_plan(router, supabase)
    limit = min(2, max(0, int(max_searches or 0)), len(queries), len(plan))
    evidence = []
    errors = []
    search_used = 0

    if limit == 0:
        return {
            "found": False,
            "state": "unknown",
            "official_entry_url": None,
            "search_used": 0,
            "rounds_no_entry": int((prev_row or {}).get("rounds_no_entry") or 0),
            "next_retry_at": (now + timedelta(days=1)).isoformat(),
            "fail_reason": "无可用搜索 provider 或本轮搜索额度已耗尽",
            "evidence": {"candidate_urls": [], "search_errors": []},
        }

    for index in range(limit):
        provider = plan[index]
        query = queries[index]
        results, error = _search_one(
            provider, supabase, query, top_k, client, consume
        )
        search_used += int(error is None)
        if error:
            errors.append({"provider": getattr(provider, "name", "?"), "error": error})
            continue
        classified = []
        for result in results:
            url = (result or {}).get("url")
            verdict, score, reason = classify_candidate_url(url, company)
            item = {
                "url": url,
                "title": (result or {}).get("title"),
                "verdict": verdict,
                "score": score,
                "reason": reason,
                "provider": getattr(provider, "name", "?"),
            }
            evidence.append(item)
            if verdict in ("trusted_ats", "likely_official"):
                classified.append(item)
        if classified:
            accepted = sorted(
                classified,
                key=lambda item: (-item["score"], str(item.get("url") or "")),
            )[:5]
            best = accepted[0]
            candidates = sorted(
                evidence,
                key=lambda item: (-item["score"], str(item.get("url") or "")),
            )[:5]
            return {
                "found": True,
                "state": "entry_found",
                "official_entry_url": best["url"],
                "candidates": accepted,
                "search_used": search_used,
                "rounds_no_entry": 0,
                "next_retry_at": None,
                "evidence": {
                    "search_provider": best["provider"],
                    "candidate_urls": candidates,
                    "search_errors": errors,
                },
            }

    rounds = int((prev_row or {}).get("rounds_no_entry") or 0) + 1
    governance = rounds >= 2
    candidates = sorted(
        evidence,
        key=lambda item: (-item["score"], str(item.get("url") or "")),
    )[:5]
    return {
        "found": False,
        "state": "governance_candidate" if governance else "no_official_entry",
        "official_entry_url": None,
        "search_used": search_used,
        "rounds_no_entry": rounds,
        "next_retry_at": None if governance else (now + timedelta(days=30)).isoformat(),
        "fail_reason": "未找到可信官方招聘入口",
        "evidence": {
            "candidate_urls": candidates,
            "search_errors": errors,
        },
    }
