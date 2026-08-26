"""北极星每日快照：旁路写入，失败不能阻断每日抓取。"""
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import gap_census
import jobs_db
import must_apply


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_snapshot_metrics(companies, rows, valid_active_jobs, active_jobs):
    """纯函数：沿用必投缺口台账已算好的健康口径，汇总国内清单的当天快照。"""
    by_industry = {}
    for company in companies or []:
        row = next((item for item in rows if item["company"] == company.get("name")), None)
        for industry in company.get("industries") or []:
            current = by_industry.setdefault(industry, {"healthy": 0, "total": 0})
            current["total"] += 1
            current["healthy"] += int(bool(row and row.get("state") == "healthy"))

    if not by_industry:
        raise ValueError("must-apply list is empty")

    worst_industry, worst = min(
        by_industry.items(),
        key=lambda item: (item[1]["healthy"] / item[1]["total"] if item[1]["total"] else 1, item[0]),
    )
    valid = _as_int(valid_active_jobs)
    active = _as_int(active_jobs)
    return {
        "must_apply_healthy_companies": sum(row.get("state") == "healthy" for row in rows),
        "must_apply_total_companies": len(rows),
        "worst_industry": worst_industry,
        "worst_industry_healthy_companies": worst["healthy"],
        "worst_industry_total_companies": worst["total"],
        "valid_active_jobs": valid,
        "active_jobs": active,
        "job_validity_rate": valid / active if active > 0 else None,
        "list_version": must_apply.version(),
    }


def _fetch_job_counts(conn):
    rows = jobs_db.fetch_all(conn, """
      select
        count_valid_active_jobs() as valid_active_jobs,
        count(*) filter (where status = 'active') as active_jobs
      from jobs
    """)
    if not rows:
        raise RuntimeError("north-star job count query returned no rows")
    return rows[0]


def record_daily_snapshot(supabase, jobs_conn, now=None, census_rows=None):
    """读取当前真实数据并 upsert；可复用当轮 census，任何异常都只告警。"""
    try:
        jobs_conn = jobs_conn or jobs_db.get_conn()
        companies = gap_census.load_companies("domestic")
        counts = _fetch_job_counts(jobs_conn)
        if census_rows is None:
            aggregates = gap_census.fetch_job_aggregates(jobs_conn, companies)
            census_rows = [gap_census.classify_company(company, aggregates, []) for company in companies]
        snapshot_at = (now or datetime.now(timezone.utc)).astimezone(SHANGHAI)
        row = {
            "snapshot_date": snapshot_at.date().isoformat(),
            **build_snapshot_metrics(
                companies,
                census_rows,
                counts.get("valid_active_jobs"),
                counts.get("active_jobs"),
            ),
            "written_at": snapshot_at.isoformat(),
        }
        supabase.table("north_star_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        return True
    except Exception as exc:  # noqa: BLE001 - 旁路快照不能打断主任务
        sys.stderr.write(f"[north-star-snapshot] 写入失败（主任务不受影响）: {type(exc).__name__}\n")
        return False
