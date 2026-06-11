#!/usr/bin/env python3
"""外企岗位 summary 回填器（workday / oracle / eightfold / smartrecruiters，httpx 逐岗 detail）。

为何独立脚本而非靠 run.py 重爬：适配器补正文的代码只作用于「当前还挂在 live 列表」的岗位，
存量里**已不在列表但仍 active** 的空 summary 行重爬永远碰不到（实测 oracle 重爬 77→74 只清 3 行）。
本脚本按 jd_url 反推各 ATS 的公开 detail 端点直接逐行补，一次清干净；与 moka 版
（scripts/backfill_moka_summaries.py，浏览器渲染）同一思路，外企四家族全是公开 JSON API 故无需浏览器。

用法（本机/CI，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
  set -a; source .env.local; set +a
  python3 scripts/backfill_foreign_summaries.py --dry-run --limit 10
  python3 scripts/backfill_foreign_summaries.py                  # 全量
  python3 scripts/backfill_foreign_summaries.py --adapter workday

幂等：只取 summary 为空的 active 岗；只更新 summary（job_type 仅在原值为空且正文可推导时一并补，
对齐 run.py 的 extract_job_type(title, summary) 口径）。detail 404/已撤岗的行保持原样（随生命周期老化）。
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler"))
import db  # noqa: E402
import enrich  # noqa: E402
import normalizer  # noqa: E402

ADAPTERS = ("workday", "oracle", "eightfold", "smartrecruiters")
# detail 反推逻辑统一住在 crawler/enrich.py（DRY）；本脚本只做「全量扫空 summary → 富化」一次性回填。
FETCHERS = {a: enrich.ENRICH_REGISTRY[a] for a in ADAPTERS}


def main():
    ap = argparse.ArgumentParser(description="外企 summary 回填器")
    ap.add_argument("--limit", type=int, default=0, help="本次最多回填多少岗（0=全部）")
    ap.add_argument("--adapter", choices=ADAPTERS, default=None, help="只回填某一家族")
    ap.add_argument("--workers", type=int, default=8, help="并发线程数")
    ap.add_argument("--dry-run", action="store_true", help="只抓取打印，不写库")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    adapters = [args.adapter] if args.adapter else list(ADAPTERS)
    sources = (sb.table("sources").select("id,company,source_url,adapter_name")
               .in_("adapter_name", adapters).execute().data) or []
    smap = {s["id"]: s for s in sources}
    if not smap:
        print("没有匹配的 sources，退出。")
        return

    # 分页取全部空 summary 的 active 岗（PostgREST 单页上限 1000）
    rows = []
    page = 0
    while True:
        batch = (sb.table("jobs").select("id,source_id,title,jd_url,job_type")
                 .in_("source_id", list(smap.keys()))
                 .is_("summary", "null").eq("status", "active")
                 .range(page * 1000, page * 1000 + 999).execute().data) or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    if args.limit:
        rows = rows[: args.limit]
    print(f"待回填外企空 summary 岗：{len(rows)}（adapter={args.adapter or '全部'}）")
    if not rows:
        return

    # 按 source 轮转交错，避免并发线程集中打同一租户
    by_src: dict = {}
    for r in rows:
        by_src.setdefault(r["source_id"], []).append(r)
    rows = [r for tup in zip_longest(*by_src.values()) for r in tup if r]

    stat = {"filled": 0, "gone": 0, "fail": 0}

    def work(row):
        src = smap.get(row["source_id"])
        fetcher = FETCHERS.get((src or {}).get("adapter_name") or "")
        if not src or not fetcher:
            stat["fail"] += 1
            return
        try:
            body = fetcher(row, src)
        except Exception as e:
            print(f"  ✗ fetch {row['title'][:40]}: {str(e)[:60]}")
            stat["fail"] += 1
            return
        summary = normalizer.clean_summary(body) if body else None
        if not summary:
            stat["gone"] += 1  # 404/已撤岗/无正文：保持原样
            return
        patch = {"summary": summary}
        if not row.get("job_type"):
            jt = normalizer.extract_job_type(row.get("title") or "", summary)
            if jt:
                patch["job_type"] = jt
        if args.dry_run:
            print(f"  [dry] {row['title'][:44]} → {summary[:60]}…")
            stat["filled"] += 1
            return
        try:
            sb.table("jobs").update(patch).eq("id", row["id"]).execute()
            stat["filled"] += 1
            if stat["filled"] % 100 == 0:
                print(f"  …已回填 {stat['filled']}/{len(rows)}")
        except Exception as e:
            print(f"  ✗ 写库 {row['title'][:40]}: {str(e)[:60]}")
            stat["fail"] += 1

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, rows))

    print(f"\n完成：回填 {stat['filled']}，已撤岗/无正文 {stat['gone']}，失败 {stat['fail']}"
          f"{'（dry-run 未写库）' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
