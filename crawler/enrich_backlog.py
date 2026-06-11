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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import zip_longest

import db
import enrich
import normalizer

# P1 = httpx 类（无浏览器、可高并发）。browser 类（beisen/moka/feishu）P2 单独 shard。
HTTPX_ADAPTERS = tuple(a for a in enrich.ENRICH_REGISTRY)
MAX_FAIL = 3  # 死信阈值：连续无果 ≥ 此值不再入队


def _now():
    return datetime.now(timezone.utc).isoformat()


def fetch_queue(sb, adapters, limit=0):
    """取队列：这些 adapter 下 active + 空 summary + enrich_fail_count<MAX_FAIL 的岗，按最新优先。
    返回 (rows, smap)。"""
    srcs = (sb.table("sources").select("id,company,source_url,adapter_name")
            .in_("adapter_name", list(adapters)).execute().data) or []
    smap = {s["id"]: s for s in srcs}
    if not smap:
        return [], smap
    rows = []
    page = 0
    while True:
        batch = (sb.table("jobs")
                 .select("id,source_id,title,jd_url,job_type,enrich_fail_count")
                 .in_("source_id", list(smap.keys()))
                 .is_("summary", "null").eq("status", "active")
                 .lt("enrich_fail_count", MAX_FAIL)
                 .order("first_seen_at", desc=True)
                 .range(page * 1000, page * 1000 + 999).execute().data) or []
        rows.extend(batch)
        if limit and len(rows) >= limit:
            return rows[:limit], smap
        if len(batch) < 1000:
            break
        page += 1
    return rows, smap


def enrich_row(sb, row, src, dry_run=False):
    """富化单行并回写。返回 'filled' | 'miss'（无果/死信+1）。永不抛（异常 → miss）。"""
    adapter = (src or {}).get("adapter_name") or ""
    try:
        body = enrich.enrich_one(adapter, row, src)
    except Exception:
        body = ""
    summary = normalizer.clean_summary(body) if body else None
    if summary:
        patch = {"summary": summary, "enrich_checked_at": _now()}
        if not row.get("job_type"):
            jt = normalizer.extract_job_type(row.get("title") or "", summary)
            if jt:
                patch["job_type"] = jt
        result = "filled"
    else:
        patch = {"enrich_fail_count": (row.get("enrich_fail_count") or 0) + 1,
                 "enrich_checked_at": _now()}
        result = "miss"
    if not dry_run:
        sb.table("jobs").update(patch).eq("id", row["id"]).execute()
    return result


def drain(sb, adapter=None, limit=0, workers=10, dry_run=False):
    adapters = (adapter,) if adapter else HTTPX_ADAPTERS
    rows, smap = fetch_queue(sb, adapters, limit)
    print(f"队列待富化（httpx 类，adapter={adapter or '全部'}）：{len(rows)}")
    if not rows:
        return {"filled": 0, "miss": 0}
    # 按 source 轮转交错，避免并发线程集中打同一租户
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source_id"], []).append(r)
    rows = [r for tup in zip_longest(*by_src.values()) for r in tup if r]

    stat = {"filled": 0, "miss": 0}

    def work(row):
        res = enrich_row(sb, row, smap.get(row["source_id"]), dry_run)
        stat[res] += 1
        done = stat["filled"] + stat["miss"]
        if done % 100 == 0:
            print(f"  …{done}/{len(rows)}  filled={stat['filled']} miss={stat['miss']}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, rows))

    print(f"完成：填充 {stat['filled']}，无果/死信+1 {stat['miss']}"
          f"{'（dry-run 未写库）' if dry_run else ''}")
    return stat


def main():
    ap = argparse.ArgumentParser(description="JD summary backlog drain（httpx 类）")
    ap.add_argument("--adapter", choices=HTTPX_ADAPTERS, default=None, help="只 drain 某一 adapter")
    ap.add_argument("--limit", type=int, default=0, help="本次最多富化多少岗（0=全部）")
    ap.add_argument("--workers", type=int, default=10, help="并发线程数")
    ap.add_argument("--dry-run", action="store_true", help="抓取打印但不写库")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    drain(sb, adapter=args.adapter, limit=args.limit, workers=args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
