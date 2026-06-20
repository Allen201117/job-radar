"""search_usage 表预算守卫：各 provider 当日已用次数（跨 CI run 持久），镜像 qianfan_usage。

绝不冲破每源日顶 → 付费搜索成本可控。串行调用，read-modify-write 精确。
"""
from datetime import datetime, timezone


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def used(sb, provider):
    rows = (sb.table("search_usage").select("used")
            .eq("provider", provider).eq("day", _today()).limit(1).execute().data) or []
    return rows[0]["used"] if rows else 0


def remaining(sb, provider, cap):
    return max(0, int(cap) - used(sb, provider))


def consume(sb, provider, n=1):
    """读+增当日计数。返回增后值。"""
    cur = used(sb, provider) + n
    sb.table("search_usage").upsert(
        {"provider": provider, "day": _today(), "used": cur,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="provider,day",
    ).execute()
    return cur
