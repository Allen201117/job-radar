import httpx
import re
import threading
from urllib.parse import urlparse


USER_AGENT = "JobRadarBot/0.1"
_ROBOTS_CACHE = {}
_ROBOTS_CACHE_LOCK = threading.Lock()

# 厂商 API 文档明确声明「公开、无鉴权、供程序化分发消费」的 ATS 端点白名单。
# robots.txt 是针对网页爬虫的指令；这些 JSON API 由厂商官方文档开放给岗位聚合方
# （SmartRecruiters Posting API 公开无鉴权，且其 robots.txt 对 LinkedInBot 显式
# Allow /v1/companies/ —— 岗位分发聚合本就是厂商许可的用途，只是没把 UA 一一列全）。
# ⚠️ 仅限「host + 路径前缀」精确豁免，不得扩大到任何网页路径；新增条目必须附厂商公开文档依据。
_PUBLIC_API_ALLOWLIST = (
    # https://developers.smartrecruiters.com/docs/posting-api （公开 Posting API）
    ("api.smartrecruiters.com", "/v1/companies/"),
)


def _public_api_allowed(hostname: str, path: str) -> bool:
    host = (hostname or "").lower()
    for allow_host, prefix in _PUBLIC_API_ALLOWLIST:
        if host == allow_host and (path or "/").startswith(prefix):
            return True
    return False


def check_robots(source_url: str) -> dict:
    """
    检查 source_url 对应的 robots.txt。
    返回 {"allowed": True/False, "reason": str}
    """
    parsed = urlparse(source_url)
    if _public_api_allowed(parsed.hostname or "", parsed.path or "/"):
        return {"allowed": True, "reason": "vendor-documented public API"}
    key = ((parsed.scheme or "").lower(), (parsed.hostname or "").lower())

    # 结果按 host 缓存，但 robots 的规则仍须按本次 path 解析。网络请求在锁外进行，
    # 不把不同 host 的首轮 robots 检查串行化；同 host 并发 miss 最多多抓一次。
    with _ROBOTS_CACHE_LOCK:
        cached = _ROBOTS_CACHE.get(key)
    if cached is None:
        robots_url = f"{parsed.scheme}://{parsed.hostname}/robots.txt"
        try:
            resp = httpx.get(
                robots_url,
                headers={"User-Agent": USER_AGENT},
                timeout=10,
                follow_redirects=True,
            )
            fetched = (
                None if resp.status_code >= 500 else resp.text,
                "robots.txt server error" if resp.status_code >= 500 else "",
            )
        except httpx.TimeoutException:
            fetched = (None, "robots.txt timeout")
        except httpx.ConnectError:
            fetched = (None, "robots.txt unreachable")
        except Exception as e:
            fetched = (None, f"robots.txt error: {e}")
        with _ROBOTS_CACHE_LOCK:
            cached = _ROBOTS_CACHE.get(key)
            if cached is None:
                _ROBOTS_CACHE[key] = fetched
                cached = fetched

    text, reason = cached
    if text is None:
        return {"allowed": True, "reason": reason}
    return _parse_robots(text, parsed.path, parsed.query)


_ME_AGENTS = ("jobradarbot", "jobradar")

_RULE_RE_CACHE: dict = {}


def _rule_matches(core: str, anchored: bool, target: str) -> bool:
    """规则路径（含 `*` 通配）是否匹配目标串。anchored=True 时要求匹配到末尾。"""
    if "*" not in core:
        return target == core if anchored else target.startswith(core)
    key = (core, anchored)
    rx = _RULE_RE_CACHE.get(key)
    if rx is None:
        body = ".*".join(re.escape(part) for part in core.split("*"))
        rx = re.compile("^" + body + ("$" if anchored else ""))
        _RULE_RE_CACHE[key] = rx
    return bool(rx.search(target))


def _parse_robots(text: str, path: str, query: str = "") -> dict:
    """解析 robots.txt，按标准语义判定目标路径是否可抓。

    关键点（修正旧版只看 Disallow、无视 Allow 的 bug）：
    - 同时收集 Allow 与 Disallow 规则；
    - **最长匹配优先**：匹配目标路径的规则里，路径前缀最长者生效；长度相同则 Allow 胜
      （Google robots 规范）。例：`Disallow: /` + `Allow: /api/pcsx` → `/api/pcsx/search` 允许。
    - user-agent 组优先：若有针对本 bot 具名的组则只用该组，否则用 `*` 组；
    - `*` 通配任意字符序列，末尾 `$` 为路径结束锚点（Google robots 规范）。
      ⚠️ 2026-09-08 补：此前 `*` 被当普通字符字面比较，于是 `Disallow: /*.pdf$` 退化成
      「路径必须恰好等于字符串 /*.pdf」→ 永远匹配不上 → `/jobs/cv.pdf` 被**错误放行**。
    - 匹配串同时试 `path` 与 `path?query` 两种形态，任一命中即算命中。
      ⚠️ 这是**刻意比规范更保守**：规范说匹配串是 path+query，只试它会让
      `Disallow: /private$` 放行 `/private?x=1`。两种都试 ⇒ 本函数的拦截集合恒为规范的超集，
      改动方向只会「多拦」不会「少拦」——合规上宁可少抓，不可多抓。
    - 路径比较保持大小写不敏感：规范其实是大小写敏感的，但改成敏感只会**放松**拦截
      （`Disallow: /Jobs` 将不再挡 `/jobs`），与上一条同理，故刻意不改。
    """
    groups: list = []  # [{"agents": set[str], "rules": [(is_allow, rule)]}]
    cur = None
    for raw in text.split("\n"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("user-agent:"):
            agent = low.split(":", 1)[1].strip()
            # 连续 user-agent 行属于同一组；规则出现后再遇 user-agent 开新组。
            if cur is None or cur["rules"]:
                cur = {"agents": set(), "rules": []}
                groups.append(cur)
            cur["agents"].add(agent)
        elif low.startswith("allow:") or low.startswith("disallow:"):
            if cur is None:
                continue
            is_allow = low.startswith("allow:")
            rule = line.split(":", 1)[1].strip()  # 路径大小写敏感，统一小写比较
            cur["rules"].append((is_allow, rule))
        # sitemap/crawl-delay 等其它字段忽略（不影响分组归属）

    named = [g for g in groups if any(a in _ME_AGENTS for a in g["agents"])]
    star = [g for g in groups if "*" in g["agents"]]
    applicable = named if named else star
    rules = [r for g in applicable for r in g["rules"]]

    path_l = (path or "/").lower()
    targets = [path_l]
    if query:
        targets.append(f"{path_l}?{query.lower()}")
    best = None  # (specificity, is_allow, rule)
    for is_allow, rule in rules:
        rl = rule.lower()
        if not rl:
            continue  # 空 Disallow = 允许全部，不构成匹配
        anchored = rl.endswith("$")
        core = rl[:-1] if anchored else rl
        matched = any(_rule_matches(core, anchored, t) for t in targets)
        spec = len(core)
        if matched and (best is None or spec > best[0] or (spec == best[0] and is_allow)):
            best = (spec, is_allow, rule)

    if best is None or best[1]:
        return {"allowed": True, "reason": ""}
    return {"allowed": False, "reason": f"robots.txt disallows {best[2]}"}
