#!/usr/bin/env python3
"""职业洞察过期下架巡检：valid_until 已过的 active 条目 → retired（保鲜，治"又旧"）。

设计见 docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md（Phase 3）。
纯日期逻辑（is_expired）可单测；只读 + 轻量 update，走 service role，无外部 key。
注：只退役**显式带 valid_until 且已过**的条目（如时令 timing seed）；无 valid_until 的（如 listing 事实）
由各 drain 的 TTL 自行复核，不在此动。
"""
import os
import sys
from datetime import datetime, timezone


def expired_cutoff(now=None):
    """今天的 UTC 日期串；valid_until < 此值即过期（含当天有效，次日才算过期）。"""
    now = now or datetime.now(timezone.utc)
    return now.date().isoformat()


def is_expired(item, now=None):
    """item.valid_until 已过（< 今天）→ True。无 valid_until 永不过期。纯函数。"""
    vu = (item or {}).get("valid_until")
    if not vu:
        return False
    return str(vu)[:10] < expired_cutoff(now)


def sweep(sb, now=None):
    """把所有 valid_until 已过的 active 条目批量置 retired。返回退役条数。"""
    rows = (sb.table("insight_items").select("id,valid_until")
            .eq("status", "active").not_.is_("valid_until", "null").execute().data) or []
    expired = [r["id"] for r in rows if is_expired(r, now)]
    for i in range(0, len(expired), 200):
        sb.table("insight_items").update({"status": "retired"}).in_("id", expired[i:i + 200]).execute()
    print(f"过期下架：{len(expired)}/{len(rows)} 条 active(带 valid_until) → retired（cutoff={expired_cutoff(now)}）")
    return len(expired)


def main():
    import db
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)
    sweep(db.get_supabase())


if __name__ == "__main__":
    main()
