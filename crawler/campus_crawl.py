"""校招高频车道编排：选源 → 抓 → 回读校招岗数 → 判开闸 → 加急重抓 → 留痕。

用途（2027 届秋招）：校招公司**一次性放出全部岗位**，开闸即从几十跳到几百上千。
daily-crawl 每 6 小时一轮、浏览器源每天一轮，最坏要等一天才进库；本车道在招聘季把
「必投清单里的校招源」单独拎出来每小时刷一遍，并在检测到开闸时立刻再抓一遍不等下一轮。

判据全在 campus_lane.py（纯函数、可单测），这里只做 IO 与编排。

与既有链路的关系：
  · 本车道是**叠加的加密轮次**，daily-crawl / enrich-crawl 覆盖面一行不减。
  · 抓全自检复用 crawl_runs.reported_total / coverage_complete（迁移 176/177），不重复造。
  · ⚠️ 不新增任何撤岗路径：校招岗数下降只记录，绝不据此标 expired（见迁移 188 红线注释）。
"""

import os
import sys
from datetime import datetime, timezone

import campus_lane
import db
import jobs_db
import must_apply
import ops_runs
from run import run_crawl


def _log(msg: str) -> None:
    print(f"[campus-lane] {msg}", flush=True)


def campus_counts_by_source(conn) -> dict:
    """香港 jobs 库：每个源当下 active 校招岗数 {source_id: count}。"""
    rows = jobs_db.fetch_all(conn, f"""
        select source_id::text as source_id, count(*)::int as n
        from jobs
        where status = 'active' and source_id is not null
          and {campus_lane.CAMPUS_JOB_SQL_PREDICATE}
        group by 1
    """)
    return {r["source_id"]: r["n"] for r in rows}


def recent_campus_producing_source_ids(conn, days: int = 30) -> set:
    """近 N 天真产过校招岗的源 —— 选源并集的另一半（见 campus_lane.select_campus_sources 注释）。

    只靠 sources.board 选源会漏掉把校招社招混在同一个列表里的自建门户：live 实测 430 个
    真产校招岗的源里 board 只覆盖 281 个，漏的 149 个恰恰是比亚迪/小红书/华为/蚂蚁这些大户。
    """
    rows = jobs_db.fetch_all(conn, f"""
        select distinct source_id::text as source_id
        from jobs
        where status = 'active' and source_id is not null
          and last_seen_at > now() - make_interval(days => %s)
          and {campus_lane.CAMPUS_JOB_SQL_PREDICATE}
    """, (days,))
    return {r["source_id"] for r in rows}


def last_snapshot_counts(supabase, source_ids: list) -> dict:
    """每个源最近一条快照的 campus_job_count（开闸判据的基线）。无快照的源不出现在返回里。"""
    out = {}
    if not source_ids:
        return out
    # 表是变更日志（只在数字变化时插行），单源行数很少；按 captured_at 倒序取首条即可。
    for chunk_start in range(0, len(source_ids), 100):
        chunk = source_ids[chunk_start:chunk_start + 100]
        resp = (supabase.table("campus_board_snapshots")
                .select("source_id, campus_job_count, captured_at")
                .in_("source_id", chunk)
                .order("captured_at", desc=True)
                .execute())
        for row in (resp.data or []):
            out.setdefault(row["source_id"], row["campus_job_count"])
    return out


def write_snapshots(supabase, rows: list) -> int:
    """插入快照行（调用方已过滤掉「数字没变」的源）。失败只告警不阻断主流程。"""
    if not rows:
        return 0
    try:
        supabase.table("campus_board_snapshots").insert(rows).execute()
        return len(rows)
    except Exception as e:  # 留痕是旁路，绝不能因为它把抓取整轮弄挂
        _log(f"⚠️ 快照写入失败（不影响抓取结果）：{type(e).__name__}: {e}")
        return 0


def main() -> int:
    force = (os.environ.get("CAMPUS_LANE_FORCE") or "").lower() in ("1", "true", "yes")
    month = datetime.now(timezone.utc).month
    if not campus_lane.is_campus_season(month) and not force:
        _log(f"{month} 月为校招淡季，本轮跳过（需强跑设 CAMPUS_LANE_FORCE=true）。")
        return 0

    if not jobs_db.enabled():
        # 校招岗数必须从香港 jobs 库回读；没配就只能抓、判不了开闸 → 明确报错而不是静默降级，
        # 否则会出现「CI 绿灯但开闸检测从没跑过」的假象。
        _log("❌ 未配置 JOBS_DATABASE_URL，无法回读校招岗数做开闸检测。")
        return 1

    supabase = db.get_supabase()
    all_sources = db.get_sources(supabase)
    conn = jobs_db.get_conn()
    try:
        producing = recent_campus_producing_source_ids(conn)
        selected = campus_lane.select_campus_sources(
            all_sources, producing, must_apply.match_company)
        if not selected:
            _log("本轮没有符合条件的校招源（board ∪ 实际产出 ∩ 必投清单），退出。")
            return 0

        by_board = sum(1 for s in selected if s.get("board") in campus_lane.CAMPUS_BOARDS)
        _log(f"选中 {len(selected)} 源（board 命中 {by_board}，"
             f"实际产出补充 {len(selected) - by_board}）/ 全库 {len(all_sources)} 源")

        before = campus_counts_by_source(conn)
        run_crawl(sources_override=selected, tier="all")

        # 抓完回读 → 判开闸
        after = campus_counts_by_source(conn)
        sel_ids = [str(s["id"]) for s in selected]
        baseline = last_snapshot_counts(supabase, sel_ids)

        snapshots, surged = [], []
        for s in selected:
            sid = str(s["id"])
            curr = after.get(sid, 0)
            # 基线优先用上一条快照；该源首次进车道则无基线 → detect_surge 返回 False（不误报）
            prev = baseline.get(sid)
            if prev is not None and curr == prev:
                continue  # 变更日志：数字没变不插行
            is_surge = campus_lane.detect_surge(prev, curr)
            snapshots.append({
                "source_id": sid,
                "company": s.get("company") or "",
                "campus_job_count": curr,
                "prev_campus_job_count": prev,
                "surge": is_surge,
            })
            if is_surge:
                surged.append(s)
                _log(f"🔥 开闸：{s.get('company')} 校招岗 {prev} → {curr}"
                     f"（本轮新增 {curr - before.get(sid, 0)}）")

        write_snapshots(supabase, snapshots)

        # 加急重抓：开闸当轮立刻再抓一遍，不等下一个整点。
        # 一次性放出上千岗时，单轮抓取常因分页/超时没拿全；紧接着的第二轮能把余量补上，
        # 是否真抓全由 crawl_runs.coverage_complete（adapter 自报）判定，不在这里自己下结论。
        if surged:
            _log(f"开闸 {len(surged)} 家 → 立即加急重抓："
                 f"{', '.join((s.get('company') or '?') for s in surged)}")
            run_crawl(sources_override=surged, tier="all")

        ops_runs.record_ops_run(supabase, "campus_lane", {
            "sources": len(selected),
            "surged": len(surged),
            "snapshots": len(snapshots),
            "campus_jobs_total": sum(after.get(str(s["id"]), 0) for s in selected),
        })
        _log(f"完成：{len(selected)} 源，开闸 {len(surged)} 家，留痕 {len(snapshots)} 条。")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
