#!/usr/bin/env python3
"""JD summary backlog drain：从 Postgres 队列取空 summary 的 active 岗，按 jd_url 反推 detail
端点富化（enrich.py 注册表），httpx 并发回写。死信：富化无果 → enrich_fail_count+1（≥3 不再入队）。

为何独立于 run.py：run.py 是「抓列表→入库骨架」；本 runner 是「按 jd_url 直推 detail 补正文」，
能覆盖已不在 live 列表的存量空行（re-crawl 碰不到的那批）。与 daily/enrich-crawl 解耦。

用法（本机/CI，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
  set -a; source ../.env.local; set +a
  python3 enrich_backlog.py --adapter hotjob --limit 50 --dry-run
  python3 enrich_backlog.py --limit 8000 --workers 12          # 全 httpx 类
"""
import argparse
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import zip_longest

from urllib.parse import urlparse

import db
import enrich
import jobs_db
import normalizer
import ops_runs

# P1 = httpx 类（无浏览器、可高并发）。browser 类（beisen/moka/feishu）P2 单独 shard。
HTTPX_ADAPTERS = tuple(a for a in enrich.ENRICH_REGISTRY)
MAX_FAIL = 3       # 死信阈值：连续无果 ≥ 此值不再入队
PER_HOST = 3       # 单 host 并发上限（礼貌 + 防被限流）。hotjob 全在 wecruit.hotjob.cn 一台 host，
#                    8 worker 全压它 → 实测 459/3000 后被限流(miss 2541)；按 host 限 3 后恢复高填充。

_host_sems = {}
_host_sems_lock = threading.Lock()


def _host_sem(host, per_host):
    with _host_sems_lock:
        s = _host_sems.get(host)
        if s is None:
            s = threading.Semaphore(per_host)
            _host_sems[host] = s
        return s

# 每线程独立 supabase 客户端：supabase-py 走 HTTP/2 单连接多路复用，被多 worker 线程共享
# 并发读写同一 socket → Errno 35 大面积失败（run.py 2026-06-10 实锤、本 drain 2026-06-11 复现）。
_TLS = threading.local()


def _thread_sb(make_sb):
    sb = getattr(_TLS, "sb", None)
    if sb is None:
        sb = make_sb()
        _TLS.sb = sb
    return sb


def _thread_jobs_conn(make_jobs_conn):
    """Phase 1：每线程独立香港 jobs 库连接（psycopg2 连接非线程安全）。"""
    conn = getattr(_TLS, "jobs_conn", None)
    if conn is None:
        conn = make_jobs_conn()
        _TLS.jobs_conn = conn
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def fetch_queue(sb, adapters, limit=0, jobs_conn=None):
    """取队列：这些 adapter 下 active + 空 summary + enrich_fail_count<MAX_FAIL 的岗，按最新优先。
    返回 (rows, smap)。sources 永远走 Supabase；jobs 在 jobs_conn(香港库) 给定时直连查，否则 Supabase。"""
    srcs = (sb.table("sources").select("id,company,source_url,adapter_name")
            .in_("adapter_name", list(adapters)).execute().data) or []
    smap = {s["id"]: s for s in srcs}
    if not smap:
        return [], smap
    if jobs_conn is not None:
        sql = ("select id, source_id, title, jd_url, job_type, enrich_fail_count from jobs "
               "where source_id = any(%s::uuid[]) and summary is null and status='active' and enrich_fail_count < %s "
               "order by source_id, first_seen_at desc" + (f" limit {int(limit)}" if limit else ""))
        return jobs_db.fetch_all(jobs_conn, sql, (list(smap.keys()), MAX_FAIL)), smap
    rows = []
    page = 0
    while True:
        batch = (sb.table("jobs")
                 .select("id,source_id,title,jd_url,job_type,enrich_fail_count")
                 .in_("source_id", list(smap.keys()))
                 .is_("summary", "null").eq("status", "active")
                 .lt("enrich_fail_count", MAX_FAIL)
                 # 排序键必须以 source_id 打头，才吃得到 migration 150 的
                 # (source_id, first_seen_at desc) WHERE active+空 summary+fail<MAX 部分索引。
                 # 裸 ORDER BY first_seen_at DESC + source_id IN(本 adapter 上百个源) 会被
                 # PostgREST 的通用(generic)预编译计划带去走日期索引、扫全表找稀疏的本 adapter 行
                 # → statement_timeout(57014)。hotjob 分片实锤：裸 first_seen 偶发 4s+/超时，
                 # 改 (source_id, first_seen) 后 30 连发 max 0.6s、零尖刺。源内仍按最新优先。
                 .order("source_id").order("first_seen_at", desc=True)
                 .range(page * 1000, page * 1000 + 999).execute().data) or []
        rows.extend(batch)
        if limit and len(rows) >= limit:
            return rows[:limit], smap
        if len(batch) < 1000:
            break
        page += 1
    return rows, smap


def fetch_liveness_queue(sb, adapters, limit=0, jobs_conn=None):
    """死活巡检队列：这些 adapter 下**所有** active 岗（不限空 summary），按 enrich_checked_at 最旧优先
    （从未复检的 NULL 最先）轮转复检——逐岗 detail 探活，撤岗信号 → expired。返回 (rows, smap)。
    sources 走 Supabase；jobs 在 jobs_conn(香港库) 给定时直连查，否则 Supabase。

    与 fetch_queue（只取空 summary 的富化 backlog）区别：巡检覆盖**已有正文**的存量岗，
    这些岗 fetch_queue 永远碰不到，正是「岗位关闭后没人下架」的死角（尤以 wt/hotjob 量大）。

    刻意 NOT 过滤 enrich_fail_count（不同于 fetch_queue 的 <MAX_FAIL）：backlog 放弃富化的高失败岗
    （补不到正文）恰是最可疑的「假 active」，必须仍纳入巡检才有机会被撤岗下架。每岗每轮只查一次
    （enrich_checked_at 轮转封顶单轮成本），死岗一旦 expired 即离开 active 集，集合自清。"""
    srcs = (sb.table("sources").select("id,company,source_url,adapter_name")
            .in_("adapter_name", list(adapters)).execute().data) or []
    smap = {s["id"]: s for s in srcs}
    if not smap:
        return [], smap
    if jobs_conn is not None:
        sql = ("select id, source_id, title, jd_url, job_type, summary, enrich_fail_count from jobs "
               "where source_id = any(%s::uuid[]) and status='active' "
               "order by source_id, enrich_checked_at asc nulls first" + (f" limit {int(limit)}" if limit else ""))
        return jobs_db.fetch_all(jobs_conn, sql, (list(smap.keys()),)), smap
    rows = []
    page = 0
    while True:
        batch = (sb.table("jobs")
                 .select("id,source_id,title,jd_url,job_type,summary,enrich_fail_count")
                 .in_("source_id", list(smap.keys()))
                 .eq("status", "active")
                 # 同 fetch_queue（8c90896）：排序键以 source_id 打头，才吃得到 migration 151 的
                 # (source_id, enrich_checked_at nulls first) WHERE active 部分索引。裸 ORDER BY
                 # enrich_checked_at + source_id IN(本 adapter 上百源) 会被 PostgREST 通用计划带去全表扫
                 # → 57014（wt/hotjob 分片实锤超时）。源内仍 NULL/最旧优先，轮转语义不变。
                 .order("source_id").order("enrich_checked_at", desc=False, nullsfirst=True)
                 .range(page * 1000, page * 1000 + 999).execute().data) or []
        rows.extend(batch)
        if limit and len(rows) >= limit:
            return rows[:limit], smap
        if len(batch) < 1000:
            break
        page += 1
    return rows, smap


def enrich_row(sb, row, src, dry_run=False, jobs_conn=None):
    """富化单行并回写。返回 'filled' | 'alive' | 'miss' | 'expired' | 'err'。永不抛。
    jobs_conn 给定时写库走香港 PG（jobs_db），否则走 Supabase（sb）。
    - 'expired'：fetcher 报源站已撤岗（JobClosedError，如 hotjob state=1017）→ 置 status='expired'，
      不再当死信富化（这类「假 active」岗永远补不到 summary 且污染岗位库）。
    - 'miss'：无正文 / 网络异常 → enrich_fail_count+1（网络错误走重试，不 expired）。"""
    adapter = (src or {}).get("adapter_name") or ""
    closed = False
    try:
        body = enrich.enrich_one(adapter, row, src)
    except enrich.JobClosedError:
        closed = True
        body = ""
    except Exception:
        body = ""
    if closed:
        patch = {"status": "expired", "enrich_checked_at": _now()}
        result = "expired"
    else:
        summary = normalizer.clean_summary(body) if body else None
        if summary and not row.get("summary"):
            patch = {"summary": summary, "enrich_checked_at": _now()}
            if not row.get("job_type"):
                jt = normalizer.extract_job_type(row.get("title") or "", summary)
                if jt:
                    patch["job_type"] = jt
            result = "filled"
        elif row.get("summary"):
            # 巡检专属分支：仍在招、已有正文 → 只盖复检时间戳（不重写 summary，省写入、不扰动正文）。
            # backlog 路径 fetch_queue 不 select summary → row.get("summary") 恒 None，永不进此分支（行为不变）。
            patch = {"enrich_checked_at": _now()}
            result = "alive"
        else:
            patch = {"enrich_fail_count": (row.get("enrich_fail_count") or 0) + 1,
                     "enrich_checked_at": _now()}
            result = "miss"
    if dry_run:
        return result
    try:
        if jobs_conn is not None:
            cols = list(patch.keys())
            set_clause = ", ".join(f"{c} = %s" for c in cols)
            jobs_db.execute(jobs_conn, f"update jobs set {set_clause} where id = %s",
                            [patch[c] for c in cols] + [row["id"]])
        else:
            sb.table("jobs").update(patch).eq("id", row["id"]).execute()
    except Exception:
        return "err"  # 写库失败（Errno35 等瞬时错误）→ 不抛，该行留队列下轮重试
    return result


# 源级失败自适应（01 spec §6.1）：某 adapter 本轮 miss 率异常高（疑似被限流）→ 跳过该 adapter 本轮剩余岗
# + 记 warning（不默默失败）。被跳过岗不盖 enrich_checked_at → 留队列下轮（限流冷却后）重试。
# 阈值保守：必须先有足够样本（min_sample）且 miss 占比超线（miss_ratio）才熔断，避免对「天生难探」的源误杀。
ADAPTIVE_MIN_SAMPLE = int(os.environ.get("ENRICH_ADAPTIVE_MIN_SAMPLE", "50"))
ADAPTIVE_MISS_RATIO = float(os.environ.get("ENRICH_ADAPTIVE_MISS_RATIO", "0.7"))


def should_trip_adapter(checked, miss, min_sample=ADAPTIVE_MIN_SAMPLE, miss_ratio=ADAPTIVE_MISS_RATIO):
    """纯函数：本轮该 adapter 已检 checked 个、其中 miss 个无果 → 是否应熔断跳过剩余。
    样本不足（< min_sample）一律不熔断；达样本且 miss/checked >= miss_ratio 才熔断。"""
    if checked < min_sample or checked <= 0:
        return False
    return (miss / checked) >= miss_ratio


def drain(sb, adapter=None, limit=0, workers=10, dry_run=False, make_sb=None, per_host=PER_HOST, sweep=False, make_jobs_conn=None):
    """sb：取 sources（Supabase）。jobs 读写：配了 JOBS_DATABASE_URL 走香港 PG（每线程独立连接防并发），
    否则走 Supabase（每线程独立 sb 防 Errno35）。per_host=单 host 并发上限（防限流，hotjob 等单 host 关键）。
    sweep=True：死活巡检（复检所有 active 岗、撤岗置 expired）；否则只富化空 summary 的 backlog。
    巡检仅覆盖 HTTPX_ADAPTERS（含 wt/hotjob）。每岗任一结果都推进 enrich_checked_at → 轮转复检。"""
    make_sb = make_sb or db.get_supabase
    use_jobs = jobs_db.enabled()
    make_jobs_conn = make_jobs_conn or (jobs_db.get_conn if use_jobs else None)
    fetch_conn = make_jobs_conn() if use_jobs else None  # 单线程取队列用的香港库连接
    adapters = (adapter,) if adapter else HTTPX_ADAPTERS
    rows, smap = (fetch_liveness_queue if sweep else fetch_queue)(sb, adapters, limit, jobs_conn=fetch_conn)
    print(f"{'死活巡检' if sweep else '富化队列'}（httpx 类，adapter={adapter or '全部'}）：{len(rows)}")
    if not rows:
        return {"filled": 0, "alive": 0, "miss": 0, "expired": 0, "err": 0, "skipped": 0}
    # 按 source 轮转交错，避免并发线程集中打同一租户
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source_id"], []).append(r)
    rows = [r for tup in zip_longest(*by_src.values()) for r in tup if r]

    stat = {"filled": 0, "alive": 0, "miss": 0, "expired": 0, "err": 0, "skipped": 0}
    lock = threading.Lock()
    per_adapter = {}          # adapter -> {"checked", "miss"}（源级自适应统计）
    tripped = set()           # 已熔断（本轮跳过剩余）的 adapter
    close_events = []         # 巡检确认撤岗 → CLOSED 里程碑（02 spec §5；批量末尾 best-effort 落库）
    day = jobs_db._day()

    def adapter_of(src):
        return (src or {}).get("adapter_name") or "(unknown)"

    def work(row):
        src = smap.get(row["source_id"])
        adp = adapter_of(src)
        with lock:
            if adp in tripped:    # 该 adapter 本轮已熔断 → 跳过，不探不写（留队列下轮重试）
                stat["skipped"] += 1
                return
        host = urlparse((src or {}).get("source_url") or "").netloc
        try:
            with _host_sem(host, per_host):  # 按 host 限并发，防单 host 被打到限流
                if use_jobs:
                    res = enrich_row(None, row, src, dry_run, jobs_conn=_thread_jobs_conn(make_jobs_conn))
                else:
                    res = enrich_row(_thread_sb(make_sb), row, src, dry_run)
        except Exception:
            res = "err"  # 兜底：任何意外都不许炸穿 ex.map（否则掀翻整批，本 drain 实锤过）
        with lock:
            stat[res] += 1
            a = per_adapter.setdefault(adp, {"checked": 0, "miss": 0})
            a["checked"] += 1
            if res == "miss":
                a["miss"] += 1
            if res == "expired":  # 巡检确认撤岗 → 收集 CLOSED（批量末尾一次性落库，避免每岗一次往返）
                close_events.append(jobs_db.plan_close_event(row["id"], row.get("source_id"), day))
            # 源级自适应：miss 率异常高 → 熔断该 adapter 本轮剩余（一次性 warning，不默默失败）
            if adp not in tripped and should_trip_adapter(a["checked"], a["miss"]):
                tripped.add(adp)
                print(f"⚠️ [自适应] adapter={adp} 本轮 miss {a['miss']}/{a['checked']} 过高（疑似被限流），"
                      f"跳过本轮剩余 {adp} 岗（不盖时间戳，下轮重试）")
            done = stat["filled"] + stat["alive"] + stat["miss"] + stat["expired"] + stat["err"] + stat["skipped"]
            if done % 200 == 0:
                print(f"  …{done}/{len(rows)}  filled={stat['filled']} alive={stat['alive']} "
                      f"miss={stat['miss']} expired={stat['expired']} err={stat['err']} skipped={stat['skipped']}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, rows))

    # CLOSED 里程碑 best-effort 批量落库（仅香港库、非 dry-run）；失败只 warning，不影响巡检结果。
    if close_events and not dry_run and use_jobs:
        rec_conn = fetch_conn or make_jobs_conn()
        jobs_db.record_job_events(rec_conn, close_events)

    print(f"完成：填充 {stat['filled']}，仍在招 {stat['alive']}，无果/死信+1 {stat['miss']}，"
          f"源站撤岗→expired {stat['expired']}，写库错(留队列重试) {stat['err']}，"
          f"限流跳过(下轮重试) {stat['skipped']}"
          f"{'（dry-run 未写库）' if dry_run else ''}")
    if tripped:
        print(f"⚠️ 本轮熔断 adapter：{', '.join(sorted(tripped))}（疑似限流，已跳过其剩余岗）")
    return stat


def main():
    ap = argparse.ArgumentParser(description="JD summary backlog drain（httpx 类）")
    ap.add_argument("--adapter", choices=HTTPX_ADAPTERS, default=None, help="只 drain 某一 adapter")
    ap.add_argument("--limit", type=int, default=0, help="本次最多富化多少岗（0=全部）")
    ap.add_argument("--workers", type=int, default=10, help="并发线程数")
    ap.add_argument("--dry-run", action="store_true", help="抓取打印但不写库")
    ap.add_argument("--sweep", action="store_true",
                    help="死活巡检：复检所有 active 岗（不限空 summary），撤岗置 expired（按 enrich_checked_at 最旧轮转）")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    started_at = _now()
    stat = drain(
        sb,
        adapter=args.adapter,
        limit=args.limit,
        workers=args.workers,
        dry_run=args.dry_run,
        sweep=args.sweep,
    )
    if not args.dry_run:
        # checked = 真正探了的（不含限流跳过的 skipped）
        checked = stat["filled"] + stat["alive"] + stat["miss"] + stat["expired"] + stat["err"]
        ops_runs.record_ops_run(
            sb,
            "liveness_sweep" if args.sweep else "enrich_backlog",
            {
                "checked": checked,
                "enriched": stat["filled"],
                "alive": stat["alive"],
                "expired": stat["expired"],
                "miss": stat["miss"],
                "failed": stat["err"],
                "skipped": stat.get("skipped", 0),
                "adapter": args.adapter or "all",
            },
            status=ops_runs.status_from_counts(checked, stat["err"]),
            started_at=started_at,
            finished_at=_now(),
        )


if __name__ == "__main__":
    main()
