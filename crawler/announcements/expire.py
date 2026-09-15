"""过期治理：报名截止日已过 → expired；无结构化截止日的走 TTL 兜底。

判死信号（对齐 CLAUDE.md「列表里没有 ≠ 撤岗」）：**只认时间**，不据「列表缺席」判死。
- 有结构化 deadline 且 < 今天 → expired（最可靠）。
- 无 deadline → 发布日（或首见日兜底）+ TTL 天 < 今天 → expired（保守，宁可晚下架不误杀）。
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone

TTL_DAYS = int(os.environ.get("ANNOUNCEMENT_TTL_DAYS", "45"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def expire(sb, today: date | None = None, ttl_days: int | None = None) -> dict:
    today = today or date.today()
    ttl = ttl_days if ttl_days is not None else TTL_DAYS
    cutoff = today - timedelta(days=ttl)
    cutoff_ts = datetime.combine(cutoff, time.min, tzinfo=timezone.utc).isoformat()

    # 1. 有结构化截止日且已过
    r1 = (sb.table("announcement_postings")
          .update({"status": "expired", "updated_at": _now_iso()})
          .eq("status", "active")
          .not_.is_("deadline", "null")
          .lt("deadline", today.isoformat())
          .execute())
    by_deadline = len(r1.data or [])

    # 2. 无截止日 + 发布日超 TTL
    r2 = (sb.table("announcement_postings")
          .update({"status": "expired", "updated_at": _now_iso()})
          .eq("status", "active")
          .is_("deadline", "null")
          .not_.is_("published_at", "null")
          .lt("published_at", cutoff.isoformat())
          .execute())
    by_ttl_pub = len(r2.data or [])

    # 3. 无截止日 + 无发布日 → 用首见日兜底
    r3 = (sb.table("announcement_postings")
          .update({"status": "expired", "updated_at": _now_iso()})
          .eq("status", "active")
          .is_("deadline", "null")
          .is_("published_at", "null")
          .lt("first_seen_at", cutoff_ts)
          .execute())
    by_ttl_seen = len(r3.data or [])

    return {"by_deadline": by_deadline, "by_ttl": by_ttl_pub + by_ttl_seen}


def main() -> int:
    import db
    db.load_environment()
    sb = db.get_supabase()
    exp = expire(sb)
    print(f"[announce-expire] 截止日过期 {exp['by_deadline']} / TTL 兜底 {exp['by_ttl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
