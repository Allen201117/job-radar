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
