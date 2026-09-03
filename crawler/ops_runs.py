"""后台任务每日台账。

台账是旁路观测：任何写入失败都只告警，不得影响原任务主流程。
"""
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _as_datetime(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_iso(value):
    return _as_datetime(value).astimezone(timezone.utc).isoformat()


def status_from_counts(processed, failed):
    """按实际处理量生成台账状态；空队列也属于正常跑完。"""
    total = max(0, int(processed or 0))
    failures = max(0, int(failed or 0))
    if total > 0 and failures >= total:
        return "failed"
    if failures > 0:
        return "partial"
    return "success"


# skip 原因分布的键数上限。原因大多来自代码里的有限枚举，但 `crash:<ExcName>` 是开放集合，
# 不封顶就可能把一行台账撑成几十个键。超出的并进 skip_other（总数守恒）。
SKIP_BREAKDOWN_MAX_KEYS = 12


def skip_breakdown(results, key="skipped", flags=()):
    """把每家公司的跳过原因聚合成 `{"skip_<原因>": 次数}`，直接并进 ops_runs 的 metrics。

    为什么要有它：本项目明令禁止「失败静默 / 绿灯零产出」，但两条校招链原先只记
    `{companies_processed, verified, draft}` —— campus_official_backlog 连续多天
    40 家零产出且 status=success，台账里**完全看不出卡在哪一步**（没有官方域？页面无信号？
    判官没过？），只能本地复现才能判因。有了这个分布，CI 跑完一眼就能定位。

    抽成公共函数而不是各链各写一份：两条链的 results 形状本来就一样，各写一份必然漂。

    · `key`   —— 存放原因字符串的字段名（两条链都是 "skipped"）
    · `flags` —— 额外的布尔字段名，为真时按字段名当原因计（如 budget_exhausted）
    没有任何跳过时返回 `{}`，不往台账里塞噪音。
    """
    counts = {}
    for row in (results or []):
        if not isinstance(row, dict):
            continue
        reason = None
        for flag in flags:
            if row.get(flag):
                reason = flag
                break
        if reason is None:
            raw = row.get(key)
            reason = str(raw).strip() if raw else ""
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return {}
    # 按次数降序保留前 N 个，其余并进 skip_other —— 总数守恒，不丢信息量最大的那几个
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kept = ordered[:SKIP_BREAKDOWN_MAX_KEYS]
    out = {f"skip_{name}": n for name, n in kept}
    overflow = sum(n for _name, n in ordered[SKIP_BREAKDOWN_MAX_KEYS:])
    if overflow:
        out["skip_other"] = out.get("skip_other", 0) + overflow
    return out


def record_ops_run(
    supabase,
    module,
    metrics,
    status="success",
    started_at=None,
    finished_at=None,
):
    """写一条 ops_runs；失败返回 False 并吞掉异常。"""
    try:
        finished = _as_datetime(finished_at)
        started = _as_datetime(started_at or finished)
        row = {
            "module": str(module),
            "run_date": finished.astimezone(SHANGHAI).date().isoformat(),
            "metrics": dict(metrics or {}),
            "status": status if status in ("success", "partial", "failed") else "failed",
            "started_at": _as_iso(started),
            "finished_at": _as_iso(finished),
        }
        supabase.table("ops_runs").insert(row).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - 旁路台账不能打断主任务
        sys.stderr.write(f"[ops-runs] {module} 台账写入失败（主任务不受影响）: {type(exc).__name__}\n")
        return False
