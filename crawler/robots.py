import httpx
from urllib.parse import urlparse


USER_AGENT = "JobRadarBot/0.1"


def check_robots(source_url: str) -> dict:
    """
    检查 source_url 对应的 robots.txt。
    返回 {"allowed": True/False, "reason": str}
    """
    parsed = urlparse(source_url)
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


def _parse_robots(text: str, path: str) -> dict:
    """解析 robots.txt 内容，检查是否有 disallow 规则覆盖目标路径。"""
    lines = text.split("\n")
    current_agents = []
    disallowed = []

    for line in lines:
        line = line.strip().lower()

        if line.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            current_agents.append(agent)

        elif line.startswith("disallow:") and current_agents:
            rule = line.split(":", 1)[1].strip()
            if any(a in ("*", "jobradarbot", "jobradar") for a in current_agents):
                disallowed.append(rule)
            current_agents = []

        elif not line or line.startswith("#"):
            continue
        else:
            current_agents = []

    # 检查是否有完全禁止
    if "/" in disallowed and not any(d.startswith("/") and d != "/" for d in disallowed):
        return {"allowed": False, "reason": "robots.txt disallows /"}

    # 检查是否有规则覆盖目标路径
    path_lower = path.lower()
    for rule in disallowed:
        if rule and path_lower.startswith(rule):
            return {"allowed": False, "reason": f"robots.txt disallows {rule}"}

    return {"allowed": True, "reason": ""}
