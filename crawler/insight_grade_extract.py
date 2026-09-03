#!/usr/bin/env python3
"""为公开讨论洞察补齐可筛选的 1–5 档位值。"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

import db
import insight_engine
import llm_budget
import ops_runs
from insight_grade_scale import GRADE_SCALES, GRADE_UNIT, build_prompt, is_gradable, parse_response


BATCH_SIZE = 20
WRITE_BATCH_SIZE = 200
GRADE_METRIC_KEYS = tuple(GRADE_SCALES)


def _chunks(values: list, size: int) -> Iterable[list]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _sample(content) -> str:
    return " ".join(str(content or "").split())[:50]


def _group_updates(updates: list[dict]) -> dict[tuple, list[str]]:
    """按相同档位聚合，减少跨网请求且避免写入无关字段。"""
    grouped: dict[tuple, list[str]] = defaultdict(list)
    for update in updates:
        row_id = update.get("id")
        value = update.get("metric_value")
        unit = update.get("metric_unit")
        if not row_id or value is None or unit != GRADE_UNIT:
            continue
        grouped[(value, unit)].append(str(row_id))
    return grouped


def apply_updates(supabase, updates: list[dict]) -> None:
    """只更新档位两列，按同档位的 id 批量 update。

    不能用 PostgREST upsert：它实际是 INSERT ... ON CONFLICT，部分 payload 会先被
    Postgres 以 INSERT 校验，缺少 company_id 等 NOT NULL 字段时整批失败。update + in_
    才是这里只改 metric_value / metric_unit 的正确语义。
    """
    for (grade, unit), ids in _group_updates(updates).items():
        for chunk in _chunks(ids, WRITE_BATCH_SIZE):
            supabase.table("insight_items").update({
                "metric_value": grade,
                "metric_unit": unit,
            }).in_("id", chunk).execute()


def extract_grades(supabase, rows: list[dict], dry_run: bool, metric_keys=None) -> dict:
    """分主题、每 20 条请求一次模型，返回可打印和可写回的完整计划。"""
    allowed_keys = tuple(metric_keys or GRADE_METRIC_KEYS)
    grouped: dict[str, list[dict]] = {key: [] for key in allowed_keys if is_gradable(key)}
    for row in rows or []:
        key = row.get("metric_key")
        if key in grouped:
            grouped[key].append(row)

    plan = {
        "metric_keys": tuple(grouped),
        "scanned": sum(len(grouped[key]) for key in grouped),
        "attempted": 0,
        "llm_calls": 0,
        "llm_failures": 0,
        "budget_exhausted": False,
        "updates": [],
        "graded": {key: [] for key in grouped},
    }

    for metric_key in grouped:
        for batch in _chunks(grouped[metric_key], BATCH_SIZE):
            # 日顶到了就立即停止；此前已拿到的结果仍会在 apply 时写回，不能整轮白跑。
            if not llm_budget.check_and_consume(supabase, kind="insight_grade", n=1):
                plan["budget_exhausted"] = True
                break
            try:
                payload = insight_engine.chat_json(
                    build_prompt(metric_key, batch),
                    temperature=0,
                    # 20 条仅需短 JSON；按条数线性留余量，避免截断又不浪费额度。
                    max_tokens=max(256, 96 + len(batch) * 28),
                    tag="grade-extract",
                )
                plan["llm_calls"] += 1
            except Exception as exc:  # 单批异常不覆盖已完成批次，留到下一轮重试。
                plan["llm_failures"] += 1
                print(
                    f"[insight-grade] {metric_key} 一批判档失败（将跳过本批）: {type(exc).__name__}",
                    file=sys.stderr,
                )
                continue

            plan["attempted"] += len(batch)
            for row, grade in zip(batch, parse_response(payload, len(batch))):
                if grade is None:
                    continue
                update = {"id": row["id"], "metric_value": grade, "metric_unit": GRADE_UNIT}
                plan["updates"].append(update)
                plan["graded"][metric_key].append({"grade": grade, "content": row.get("content")})
        if plan["budget_exhausted"]:
            break

    if not dry_run:
        apply_updates(supabase, plan["updates"])
    return plan


def _load_rows(supabase, metric_keys) -> list[dict]:
    """分页读取候选行；PostgREST 单次最多 1000 行，不能直接 .execute()。"""
    return db.fetch_all_rows(
        lambda: (
            supabase.table("insight_items")
            .select("id,metric_key,content")
            .eq("origin", "public_web")
            .eq("status", "active")
            .in_("metric_key", list(metric_keys))
            .is_("metric_value", "null")
        )
    )


def print_summary(plan: dict, dry_run: bool) -> None:
    mode = "dry-run（未写 insight_items）" if dry_run else "apply（已写入）"
    print(f"insight grade extract: {mode}")
    print(
        f"  扫描: {plan['scanned']}；已请求: {plan['attempted']}；"
        f"判出: {len(plan['updates'])}；未判出: {plan['attempted'] - len(plan['updates'])}"
    )
    print(f"  LLM 调用: {plan['llm_calls']}；失败批次: {plan['llm_failures']}；额度耗尽: {plan['budget_exhausted']}")
    for metric_key in plan["metric_keys"]:
        print(f"  {metric_key}:")
        by_grade = defaultdict(list)
        for item in plan["graded"].get(metric_key, []):
            by_grade[item["grade"]].append(_sample(item["content"]))
        for grade in range(1, 6):
            examples = by_grade[grade][:3]
            print(f"    {grade} 档: {len(by_grade[grade])}")
            for example in examples:
                print(f"      - {example}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="为公开讨论的档位类洞察补齐 1–5 档数值")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只调 LLM、打印分布，不写 insight_items（默认）")
    mode.add_argument("--apply", action="store_true", help="将判出的档位批量写回 metric_value / metric_unit")
    parser.add_argument("--limit", type=int, help="最多处理多少条")
    parser.add_argument("--metric", choices=GRADE_METRIC_KEYS, help="只处理一个档位主题")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须是正整数")

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，请通过环境变量提供凭据。", file=sys.stderr)
        return 1

    dry_run = not args.apply
    metric_keys = (args.metric,) if args.metric else GRADE_METRIC_KEYS
    started_at = datetime.now(timezone.utc).isoformat()
    supabase = db.get_supabase()
    rows = _load_rows(supabase, metric_keys)
    if args.limit is not None:
        rows = rows[:args.limit]
    plan = extract_grades(supabase, rows, dry_run=dry_run, metric_keys=metric_keys)
    print_summary(plan, dry_run)

    # dry-run 不写 insight_items 或 ops_runs；但 check_and_consume 仍会记真实 LLM 成本，
    # 否则一次 dry-run 就能绕开日额度闸。apply 才留下本任务的 ops_runs 台账。
    if not dry_run:
        status = "partial" if plan["budget_exhausted"] else ops_runs.status_from_counts(
            plan["llm_calls"], plan["llm_failures"]
        )
        ops_runs.record_ops_run(
            supabase,
            "insight_grade_extract",
            {
                "scanned": plan["scanned"],
                "attempted": plan["attempted"],
                "graded": len(plan["updates"]),
                "ungraded": plan["attempted"] - len(plan["updates"]),
                "llm_calls": plan["llm_calls"],
                "llm_failures": plan["llm_failures"],
                "budget_exhausted": int(plan["budget_exhausted"]),
            },
            status=status,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
