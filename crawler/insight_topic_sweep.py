#!/usr/bin/env python3
"""治理公开讨论「说法」层的主题相关性、数值和完全重复项。"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List

import db
import insight_topic_gate as topic_gate
import ops_runs


WRITE_BATCH_SIZE = 200
SAMPLE_SIZE = 5


def _sample(content) -> str:
    """统计输出只留一行短样本，既便于人工核验也不淹没 CI 日志。"""
    return " ".join(str(content or "").split())[:60]


def build_plan(rows: List[dict]) -> dict:
    """行数据 → 写入计划；只含纯函数判断，便于在不连库时完整单测。

    完全重复优先于主题判定：一条既重复又跑题的内容仍只统计为 dedupe，避免 dry-run
    汇总把同一行重复计数，且 apply 时仅做一次 retired 写入。
    """
    duplicate_ids = set(topic_gate.dedupe_plan(rows))
    reroute = defaultdict(int)
    samples = defaultdict(list)
    metric_updates = []
    reroute_updates = []
    retire_ids = []
    dedupe_ids = []
    keep = 0

    for row in rows:
        row_id = row.get("id")
        if not row_id:
            continue
        if row_id in duplicate_ids:
            dedupe_ids.append(row_id)
            if len(samples["dedupe"]) < SAMPLE_SIZE:
                samples["dedupe"].append(_sample(row.get("content")))
            continue

        current_key = row.get("metric_key") or ""
        action, target_key = topic_gate.classify_topic(row.get("content"), current_key)
        if action == "keep":
            keep += 1
            if len(samples["keep"]) < SAMPLE_SIZE:
                samples["keep"].append(_sample(row.get("content")))
            value = topic_gate.extract_metric_value(current_key, row.get("content"))
            if value is not None:
                metric_updates.append({"id": row_id, "metric_value": value})
        elif action == "reroute":
            reroute[target_key] += 1
            sample_key = f"reroute→{target_key}"
            if len(samples[sample_key]) < SAMPLE_SIZE:
                samples[sample_key].append(_sample(row.get("content")))
            payload = {"id": row_id, "metric_key": target_key}
            value = topic_gate.extract_metric_value(target_key, row.get("content"))
            if value is not None:
                payload["metric_value"] = value
            reroute_updates.append(payload)
        else:
            retire_ids.append(row_id)
            if len(samples["retire"]) < SAMPLE_SIZE:
                samples["retire"].append(_sample(row.get("content")))

    return {
        "keep": keep,
        "reroute": dict(reroute),
        "retire": retire_ids,
        "dedupe": dedupe_ids,
        "metric_updates": metric_updates,
        "reroute_updates": reroute_updates,
        "samples": dict(samples),
    }


def _chunks(values: List, size: int = WRITE_BATCH_SIZE) -> Iterable[List]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def apply_plan(supabase, plan: dict) -> None:
    """按不超过 200 条的批次写回，避免 6 千条逐行跨洋 HTTP 请求。"""
    for payloads in _chunks(plan["metric_updates"]):
        supabase.table("insight_items").upsert(payloads, on_conflict="id").execute()
    for payloads in _chunks(plan["reroute_updates"]):
        supabase.table("insight_items").upsert(payloads, on_conflict="id").execute()

    # 去重与主题退役可能在同一个批次；先去重可保证 status 写入总次数与统计一致。
    retired_ids = list(dict.fromkeys(plan["retire"] + plan["dedupe"]))
    for ids in _chunks(retired_ids):
        supabase.table("insight_items").update({"status": "retired"}).in_("id", ids).execute()


def print_summary(plan: dict, dry_run: bool) -> None:
    mode = "dry-run（未写库）" if dry_run else "apply（已写入）"
    print(f"insight topic sweep: {mode}")
    print(f"  keep: {plan['keep']}")
    print("  reroute:")
    if plan["reroute"]:
        for target, count in sorted(plan["reroute"].items()):
            print(f"    {target}: {count}")
    else:
        print("    0")
    print(f"  retire: {len(plan['retire'])}")
    print(f"  dedupe: {len(plan['dedupe'])}")
    for kind in ("keep", *sorted(key for key in plan["samples"] if key.startswith("reroute→")), "retire", "dedupe"):
        examples = plan["samples"].get(kind, [])
        if examples:
            print(f"  {kind} 样本:")
            for example in examples:
                print(f"    - {example}")


def _load_active_public_web_rows(supabase) -> List[dict]:
    """必须分页：PostgREST 超过 1000 行会静默截断，治理结果会因此失真。"""
    return db.fetch_all_rows(
        lambda: (
            supabase.table("insight_items")
            .select("id,company_id,metric_key,content,created_at")
            .eq("origin", "public_web")
            .eq("status", "active")
        )
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="治理公开讨论洞察的主题相关性、数值与重复项")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只打印统计，不写库（默认）")
    mode.add_argument("--apply", action="store_true", help="按批写回 metric_key / metric_value / status")
    parser.add_argument("--limit", type=int, help="只处理前 N 条，便于小范围核验")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须是正整数")

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，请通过环境变量提供凭据。", file=sys.stderr)
        return 1

    dry_run = not args.apply
    started_at = datetime.now(timezone.utc).isoformat()
    supabase = db.get_supabase()
    rows = _load_active_public_web_rows(supabase)
    if args.limit is not None:
        rows = rows[:args.limit]
    plan = build_plan(rows)
    if not dry_run:
        apply_plan(supabase, plan)
    print_summary(plan, dry_run)

    # dry-run 的「不写库」承诺包括旁路台账；apply 才记录真实治理产出。
    if not dry_run:
        ops_runs.record_ops_run(
            supabase,
            "insight_topic_sweep",
            {
                "scanned": len(rows),
                "keep": plan["keep"],
                "reroute": sum(plan["reroute"].values()),
                "retired": len(plan["retire"]),
                "dedupe": len(plan["dedupe"]),
                "metric_values": len(plan["metric_updates"]),
            },
            status=ops_runs.status_from_counts(len(rows), 0),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
