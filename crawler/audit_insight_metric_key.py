#!/usr/bin/env python3
"""只读：按新的「说法类型门」复算存量 insight_items 的 metric_key，报影响面。

没有也不会有 --apply：改存量是不可逆操作（metric_key 一改，已成立申诉的
(dimension, metric_key) 封禁粒度、洞察库的指标聚合都跟着变），必须创始人拍板。
这里只回答一个问题：**按新规则会重新归类多少条、往哪两个方向走。**

⚠️ 报数必须双向（CLAUDE.md「①的量必须双向」）：
  · 正向 = 判不出档的条目被摘掉 metric_key / 换到对的量表（本次要修的）；
  · 反向 = **已经判出档**的条目被新规则摘掉 metric_key（这是回归，越少越好）。
只报净值会把两个相反方向的错互相抵消。
"""
import argparse
import os
import sys
from collections import Counter

import db
import insight_topic_gate as topic_gate

# 只复算说法层（public_web）条目：派生类（derived/official）的 metric_key 由算子给定，
# 不经主题门，也不该被词表改动。
ORIGIN = "public_web"


def _load_rows(supabase, statuses):
    return db.fetch_all_rows(
        lambda: (
            supabase.table("insight_items")
            .select("id,metric_key,dimension,content,metric_value,status")
            .eq("origin", ORIGIN)
            .in_("status", list(statuses))
            .not_.is_("metric_key", "null")
        )
    )


def replan(rows):
    """返回 (迁移计数, 方向计数)。纯函数，便于单测。"""
    moves = Counter()
    directions = Counter()
    for row in rows or []:
        old_key = row.get("metric_key")
        if not old_key:
            continue
        new_key, _dim = topic_gate.route_by_claim_type(row.get("content") or "", old_key)
        if new_key == old_key:
            directions["unchanged"] += 1
            continue
        moves[(old_key, new_key or "(无量表)")] += 1
        graded = row.get("metric_value") is not None
        if new_key is None:
            directions["graded_key_dropped" if graded else "ungraded_key_dropped"] += 1
        else:
            directions["graded_key_moved" if graded else "ungraded_key_moved"] += 1
    return moves, directions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="只读复算存量 insight_items 的 metric_key 归类")
    parser.add_argument("--status", action="append", default=None,
                        help="要复算的 status，可重复；默认只看 active")
    args = parser.parse_args(argv)
    statuses = args.status or ["active"]

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY。", file=sys.stderr)
        return 1

    rows = _load_rows(db.get_supabase(), statuses)
    moves, directions = replan(rows)

    print(f"insight metric_key 复算（只读，status={','.join(statuses)}，共 {len(rows)} 条）")
    print(f"  不变: {directions['unchanged']}")
    print("  ── 正向（本次要修的）──")
    print(f"    未判出档 → 摘掉 metric_key: {directions['ungraded_key_dropped']}")
    print(f"    未判出档 → 换到别的量表:   {directions['ungraded_key_moved']}")
    print("  ── 反向（回归，越少越好）──")
    print(f"    已判出档 → 摘掉 metric_key: {directions['graded_key_dropped']}")
    print(f"    已判出档 → 换到别的量表:   {directions['graded_key_moved']}")
    print("  逐项迁移：")
    for (old_key, new_key), count in moves.most_common():
        print(f"    {old_key} → {new_key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
