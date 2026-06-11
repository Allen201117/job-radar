#!/usr/bin/env python3
"""职业洞察 T2 富化 backlog drain：从 company_profiles 队列取「待富化/超期」公司，
查 Wikidata 官方事实 → 回写 listing 洞察 + 公司画像字段。仿 enrich_backlog（队列 / 死信 / 每线程 sb）。

- T2 Wikidata（结构化事实，不过判官，源即真值）= 本 worker 默认职责。
- T3 经验层（engine 判官）为可插拔 hook：v1 千帆检索延后（用户定），故默认只跑 T2。
- 队列 = company_profiles 中 insight_checked_at 为空 或 超 TTL，且 insight_fail_count < MAX_FAIL。

用法（CI / 本机，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY；迁移 135 已应用）：
  python3 insight_backlog.py --seed-from-sources   # 先给所有源公司建画像占位再 drain
  python3 insight_backlog.py --limit 200 --workers 4
"""
import argparse
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import db
import wikidata

MAX_FAIL = 3        # 死信阈值：连续失败 ≥ 此值不再入队
TTL_DAYS = 90       # 官方事实变动罕见，90 天复核一次
SOURCE_KIND = "public_aggregate"  # Wikidata = 公开聚合（须在 013 insight_sources.source_kind 白名单内）

_TLS = threading.local()


def _thread_sb(make_sb):
    sb = getattr(_TLS, "sb", None)
    if sb is None:
        sb = make_sb()
        _TLS.sb = sb
    return sb


def _now():
    return datetime.now(timezone.utc).isoformat()


def seed_from_sources(sb):
    """给每个 distinct sources.company 建 company_profiles 占位（insight_checked_at=null 入队）。幂等。"""
    srcs = (sb.table("sources").select("company").eq("enabled", True).execute().data) or []
    companies = sorted({(s.get("company") or "").strip() for s in srcs if (s.get("company") or "").strip()})
    existing = (sb.table("company_profiles").select("company").execute().data) or []
    have = {(c.get("company") or "").strip() for c in existing}
    todo = [c for c in companies if c not in have]
    for i in range(0, len(todo), 100):
        chunk = [{"company": c} for c in todo[i:i + 100]]
        if chunk:
            sb.table("company_profiles").upsert(chunk, on_conflict="company").execute()
    print(f"seed-from-sources：{len(companies)} 源公司，新建画像占位 {len(todo)}")
    return len(todo)


def fetch_queue(sb, limit=0):
    """取队列：insight_checked_at 为空 或 超 TTL，且未超死信。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TTL_DAYS)).isoformat()
    q = (sb.table("company_profiles")
         .select("id,company,aliases,insight_fail_count")
         .lt("insight_fail_count", MAX_FAIL)
         .or_(f"insight_checked_at.is.null,insight_checked_at.lt.{cutoff}"))
    if limit:
        q = q.limit(limit)
    return (q.execute().data) or []


def _existing_wikidata_listing(sb, company_id):
    rows = (sb.table("insight_items").select("id")
            .eq("company_id", company_id).eq("dimension", "listing").eq("origin", "wikidata")
            .limit(1).execute().data) or []
    return rows[0]["id"] if rows else None


def write_listing(sb, company_id, li):
    """写 / 更新 Wikidata listing 洞察 + 溯源（仅新建时建一次来源）。li = wikidata.facts_to_listing。"""
    item = {
        "company_id": company_id, "dimension": "listing", "grade": "fact",
        "title": li["title"], "content": li["content"], "payload": li["payload"],
        "origin": "wikidata", "deidentified": True, "status": "active",
        "time_window": f"上市状态截至 {datetime.now(timezone.utc).year} 年",
        "last_verified_at": _now(),
    }
    existing = _existing_wikidata_listing(sb, company_id)
    if existing:
        sb.table("insight_items").update(item).eq("id", existing).execute()
        return existing
    item["id"] = str(uuid.uuid4())
    sb.table("insight_items").insert(item).execute()
    if li.get("source_url"):
        src = {"id": str(uuid.uuid4()), "url": li["source_url"],
               "publisher": li.get("source_publisher") or "Wikidata",
               "source_kind": SOURCE_KIND, "deidentified": True}
        sb.table("insight_sources").insert(src).execute()
        sb.table("insight_item_sources").insert({"item_id": item["id"], "source_id": src["id"]}).execute()
    return item["id"]


def enrich_company(sb, profile):
    """富化单家公司并回写。返回 'ok' | 'noface'（Wikidata 查无）| 'err'。永不抛。"""
    try:
        facts = wikidata.get_company_facts(profile["company"], profile.get("aliases"))
    except Exception:
        facts = None
    if not facts:
        # 查无也记一轮 checked_at（避免每次重试查无的公司）；不算硬失败
        try:
            sb.table("company_profiles").update({"insight_checked_at": _now()}).eq("id", profile["id"]).execute()
        except Exception:
            return "err"
        return "noface"
    try:
        li = wikidata.facts_to_listing(facts)
        if li:
            write_listing(sb, profile["id"], li)
        prof = wikidata.facts_to_profile(facts)
        prof["insight_checked_at"] = _now()
        prof["last_verified_at"] = _now()
        sb.table("company_profiles").update(prof).eq("id", profile["id"]).execute()
        return "ok"
    except Exception:
        try:
            sb.table("company_profiles").update({
                "insight_fail_count": (profile.get("insight_fail_count") or 0) + 1,
                "insight_checked_at": _now(),
            }).eq("id", profile["id"]).execute()
        except Exception:
            pass
        return "err"


def drain(sb, limit=0, workers=4, make_sb=None):
    """sb 取队列；写库走每线程独立客户端（make_sb，默认 db.get_supabase）防 Errno35。"""
    make_sb = make_sb or db.get_supabase
    rows = fetch_queue(sb, limit)
    print(f"队列待富化公司：{len(rows)}")
    if not rows:
        return {"ok": 0, "noface": 0, "err": 0}
    stat = {"ok": 0, "noface": 0, "err": 0}
    lock = threading.Lock()

    def work(p):
        try:
            res = enrich_company(_thread_sb(make_sb), p)
        except Exception:
            res = "err"
        with lock:
            stat[res] += 1
            done = sum(stat.values())
            if done % 50 == 0:
                print(f"  …{done}/{len(rows)}  {stat}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, rows))
    print(f"完成：{stat}")
    return stat


def main():
    ap = argparse.ArgumentParser(description="职业洞察 T2 Wikidata 富化 drain")
    ap.add_argument("--seed-from-sources", action="store_true", help="先给所有源公司建画像占位")
    ap.add_argument("--limit", type=int, default=0, help="本次最多富化多少公司（0=全部待处理）")
    ap.add_argument("--workers", type=int, default=4, help="并发线程数（对 Wikidata 保持礼貌，建议 ≤6）")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    if args.seed_from_sources:
        seed_from_sources(sb)
    drain(sb, limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
