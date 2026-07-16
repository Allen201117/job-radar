import httpx
from urllib.parse import urlparse


USER_AGENT = "JobRadarBot/0.1"

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
    robots_url = f"{parsed.scheme}://{parsed.hostname}/robots.txt"

    try:
        resp = httpx.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code >= 500:
            return {"allowed": True, "reason": "robots.txt server error"}

        text = resp.text
        return _parse_robots(text, parsed.path)

    except httpx.TimeoutException:
        return {"allowed": True, "reason": "robots.txt timeout"}
    except httpx.ConnectError:
        return {"allowed": True, "reason": "robots.txt unreachable"}
    except Exception as e:
        return {"allowed": True, "reason": f"robots.txt error: {e}"}


_ME_AGENTS = ("jobradarbot", "jobradar")


def _parse_robots(text: str, path: str) -> dict:
    """解析 robots.txt，按标准语义判定目标路径是否可抓。

    关键点（修正旧版只看 Disallow、无视 Allow 的 bug）：
    - 同时收集 Allow 与 Disallow 规则；
    - **最长匹配优先**：匹配目标路径的规则里，路径前缀最长者生效；长度相同则 Allow 胜
      （Google robots 规范）。例：`Disallow: /` + `Allow: /api/pcsx` → `/api/pcsx/search` 允许。
    - user-agent 组优先：若有针对本 bot 具名的组则只用该组，否则用 `*` 组；
    - 末尾 `$` 视为路径结束锚点（精确匹配）。
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
    best = None  # (specificity, is_allow, rule)
    for is_allow, rule in rules:
        rl = rule.lower()
        if not rl:
            continue  # 空 Disallow = 允许全部，不构成匹配
        if rl.endswith("$"):
            pat = rl[:-1]
            matched = path_l == pat
            spec = len(pat)
        else:
            matched = path_l.startswith(rl)
            spec = len(rl)
        if matched and (best is None or spec > best[0] or (spec == best[0] and is_allow)):
            best = (spec, is_allow, rule)

    if best is None or best[1]:
        return {"allowed": True, "reason": ""}
    return {"allowed": False, "reason": f"robots.txt disallows {best[2]}"}
