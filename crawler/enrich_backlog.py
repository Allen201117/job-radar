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
import normalizer

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
    if dry_run:
        return result
    try:
        sb.table("jobs").update(patch).eq("id", row["id"]).execute()
    except Exception:
        return "err"  # 写库失败（Errno35 等瞬时错误）→ 不抛，该行留队列下轮重试
    return result


def drain(sb, adapter=None, limit=0, workers=10, dry_run=False, make_sb=None, per_host=PER_HOST):
    """sb 用于单线程取队列；写库走每线程独立客户端（make_sb 工厂，默认 db.get_supabase）防 Errno35。
    per_host = 单 host 并发上限（防限流，hotjob 等单 host 源关键）。"""
    make_sb = make_sb or db.get_supabase
    adapters = (adapter,) if adapter else HTTPX_ADAPTERS
    rows, smap = fetch_queue(sb, adapters, limit)
    print(f"队列待富化（httpx 类，adapter={adapter or '全部'}）：{len(rows)}")
    if not rows:
        return {"filled": 0, "miss": 0, "err": 0}
    # 按 source 轮转交错，避免并发线程集中打同一租户
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source_id"], []).append(r)
    rows = [r for tup in zip_longest(*by_src.values()) for r in tup if r]

    stat = {"filled": 0, "miss": 0, "err": 0}
    lock = threading.Lock()

    def work(row):
        src = smap.get(row["source_id"])
        host = urlparse((src or {}).get("source_url") or "").netloc
        try:
            with _host_sem(host, per_host):  # 按 host 限并发，防单 host 被打到限流
                res = enrich_row(_thread_sb(make_sb), row, src, dry_run)
        except Exception:
            res = "err"  # 兜底：任何意外都不许炸穿 ex.map（否则掀翻整批，本 drain 实锤过）
        with lock:
            stat[res] += 1
            done = stat["filled"] + stat["miss"] + stat["err"]
            if done % 200 == 0:
                print(f"  …{done}/{len(rows)}  filled={stat['filled']} miss={stat['miss']} err={stat['err']}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, rows))

    print(f"完成：填充 {stat['filled']}，无果/死信+1 {stat['miss']}，写库错(留队列重试) {stat['err']}"
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
