"""修复台账：把一次「自动修复」session 的结果写成一行 ops_runs(module='auto_repair')。

用法：python3 repair_ledger.py --file <path.json>

输入 JSON 形状：
{
  "started_at": "2026-09-19T01:00:00+00:00",
  "finished_at": "2026-09-19T01:40:00+00:00",
  "items": [
    {
      "check_id": "jobs.active_total",   // 或 "issue"：contract 里没有对应 check_id 的老 issue
      "title": "一句人话标题",
      "outcome": "fixed",                // fixed|closed_stale|waiting_founder|needs_founder_action|fix_failed|still_breaching|skipped_gave_up
      "evidence": "一句话证据",
      "commit": "abc1234",               // 可选
      "ask": "需要创始人做什么"           // waiting_founder / needs_founder_action 必填
    }
  ]
}

⚠️ 本仓库是公开仓库：title / evidence / ask 会被晨报直接念出来、进邮件正文。**不许写连接串、
IP、公司内部路径、用户邮箱或任何密钥**——这三个字段是给非技术创始人看的人话，不是调试日志。

三条硬规矩：
  1. 校验不过（outcome 不在枚举里 / waiting 类缺 ask / title 或 evidence 为空）→ 非零退出，不写库。
  2. items 可以为空——今天没有要处理的问题也要写一行，这是自动修复「今天真的跑过」的心跳。
  3. 台账用 ops_runs.record_ops_run 写，与仓库里其它后台任务同一张表、同一套约定。
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import ops_runs

try:
    import db  # noqa: E402 - 延迟到函数内使用即可，模块级导入是为了方便单测 mock.patch.object(rl, "db")
except ImportError:  # pragma: no cover - db 依赖 supabase SDK，理论上仓库里总是有
    db = None

OUTCOMES = (
    "fixed", "closed_stale", "waiting_founder", "needs_founder_action",
    "fix_failed", "still_breaching", "skipped_gave_up",
)
ASK_REQUIRED_OUTCOMES = ("waiting_founder", "needs_founder_action")
FIX_FAILED_OUTCOMES = ("fix_failed", "still_breaching")
MAX_FIELD_CHARS = 200


def _truncate(text, limit=MAX_FIELD_CHARS):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def validate_items(items):
    """校验通过 → 返回清洗后的 items（title/evidence/ask 已截断）；不通过 → 抛 ValueError。"""
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    cleaned = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] 不是对象")
        outcome = item.get("outcome")
        if outcome not in OUTCOMES:
            raise ValueError(f"items[{i}].outcome 不在允许的枚举里: {outcome!r}")
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError(f"items[{i}].title 不能为空")
        evidence = str(item.get("evidence") or "").strip()
        if not evidence:
            raise ValueError(f"items[{i}].evidence 不能为空")
        ask = str(item.get("ask") or "").strip()
        if outcome in ASK_REQUIRED_OUTCOMES and not ask:
            raise ValueError(f"items[{i}].outcome={outcome!r} 必须带非空 ask（需要创始人做什么）")
        check_id = item.get("check_id") or item.get("issue")
        if not check_id:
            raise ValueError(f"items[{i}] 必须带 check_id 或 issue 之一，用于归属")
        cleaned.append({
            "check_id": item.get("check_id"),
            "issue": item.get("issue"),
            "title": _truncate(title),
            "outcome": outcome,
            "evidence": _truncate(evidence),
            "commit": item.get("commit") or None,
            "ask": _truncate(ask) if ask else None,
        })
    return cleaned


def build_metrics(items):
    """metrics = {items, counts（所有枚举键都出现，0 也写）, total}。"""
    counts = {o: 0 for o in OUTCOMES}
    for item in items:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    return {"items": items, "counts": counts, "total": len(items)}


def status_for(items):
    """有 fix_failed → partial；其余（含空 items）→ success。still_breaching 不算失败——
    那是『已知问题还没修好但没有恶化』，跟这次修复动作本身是否顺利完成是两回事。
    """
    if any(item["outcome"] == "fix_failed" for item in items):
        return "partial"
    return "success"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="本次自动修复结果的 JSON 文件路径")
    args = parser.parse_args(argv)

    try:
        with open(args.file, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[repair-ledger] 读取/解析 {args.file} 失败: {type(exc).__name__}: {exc}\n")
        return 1

    try:
        items = validate_items(payload.get("items") or [])
    except ValueError as exc:
        sys.stderr.write(f"[repair-ledger] 校验失败，未写台账: {exc}\n")
        return 1

    started_at = payload.get("started_at")
    finished_at = payload.get("finished_at") or datetime.now(timezone.utc).isoformat()
    metrics = build_metrics(items)
    status = status_for(items)

    if db is None:
        sys.stderr.write("[repair-ledger] db 模块导入失败，无法获取 Supabase client\n")
        return 1
    try:
        sb = db.get_supabase()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[repair-ledger] 无法获取 Supabase client，台账写不了: {type(exc).__name__}\n")
        return 1

    ok = ops_runs.record_ops_run(
        sb, "auto_repair", metrics, status=status,
        started_at=started_at, finished_at=finished_at,
    )
    if not ok:
        sys.stderr.write("[repair-ledger] 台账写入失败\n")
        return 1
    print(f"[repair-ledger] 已记录 {metrics['total']} 项，status={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
