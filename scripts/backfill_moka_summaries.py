#!/usr/bin/env python3
"""Moka 岗位 summary 回填器（浏览器逐岗渲染抓 JD）。

为何独立脚本而非接入 run.py：Moka 列表 JSON 加密、JD 只在 `{base}#/job/{uuid}` 详情页 DOM 里，
补 summary 必须**逐岗浏览器渲染**（~2-5s/岗）。把 5.8k 岗渲染塞进每日 cron 会拖垮夜爬（数小时），
故拆成独立、可限量、幂等的回填器——按需/周期（如每周一次 GitHub Action）跑，只补 summary 为空的 Moka 岗。

用法（本机/CI，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
  set -a; source ../.env.local; set +a
  python3 scripts/backfill_moka_summaries.py --limit 50              # 补 50 个
  python3 scripts/backfill_moka_summaries.py --limit 5 --dry-run
  # 全量并行（6 进程分片，互不重叠；每片自己起一个 Chromium）：
  for k in 0 1 2 3 4 5; do python3 scripts/backfill_moka_summaries.py --shard $k/6 --limit 2000 & done

只读 + 只更新 summary 字段（不碰 jd_url/title 等），幂等（只取 summary 为空的 Moka 岗）。
Beisen 不在此脚本：其列表接口本就带 Duty/Require 正文（china_ats._map 已修），跑每日爬取即回填。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler"))
import db  # noqa: E402
import normalizer  # noqa: E402

# JD 正文容器候选（moka 不同租户 class 不一）。取所有命中里**文本最长**的一个，比单一固定 class 稳。
_JD_SELECTORS = (
    "[class*=escription]", "[class*=jobDetail]", "[class*=job-detail]",
    "[class*=detail-content]", "[class*=position-detail]", "[class*=job-content]",
    "[class*=jobContent]", "article", "main",
)
_NOISE = ("我知道了", "立即投递", "在招职位", "分享", "收藏")


def _scrape_jd(page) -> str:
    best = ""
    for sel in _JD_SELECTORS:
        try:
            for el in page.query_selector_all(sel):  # 同 class 可能多个，全扫取最长
                t = (el.inner_text() or "").strip()
                if len(t) > len(best):
                    best = t
        except Exception:
            continue
    # 过滤明显的非 JD 噪声短文本（不退回裸 body：含导航/页脚噪声 → 低质量 summary）
    if best and len(best) < 20 and any(n in best for n in _NOISE):
        return ""
    return best


def _probe_dom(page) -> str:
    """诊断：打印该详情页真实 DOM 结构，供经验性定位 JD 容器 + 关闭标记（--probe 用，不写库）。"""
    out = []
    try:
        out.append(f"title={page.title()!r}")
    except Exception:
        pass
    try:
        body = (page.query_selector("body").inner_text() or "").strip()
        out.append(f"body_len={len(body)} body_head={body[:300]!r}")
    except Exception:
        out.append("body=<none>")
    for sel in _JD_SELECTORS:
        try:
            els = page.query_selector_all(sel)
            if els:
                lens = sorted((len((e.inner_text() or "").strip()) for e in els), reverse=True)[:3]
                out.append(f"  {sel}: n={len(els)} top_lens={lens}")
        except Exception:
            continue
    return "\n".join(out)


def _fetch_targets(sb, limit: int):
    """分页取 summary 为空 + 未超死信的 active Moka 岗，供 shard 切片。

    ⚠️ 不能用 `jd_url LIKE '%mokahr%'`（前导通配 → 无法走索引 → 13 万 active 全表扫撞
    service_role ~8s statement_timeout=57014，整个 drain 崩；实测 enrich-backlog-browser 连败）。
    改为先取 moka 源 id、再 `source_id IN(...)` + 排序键以 source_id 打头，吃 migration 150 的
    (source_id, first_seen_at desc) WHERE active+空summary+fail<3 部分索引（同 fetch_queue 8c90896）。"""
    src_ids = [s["id"] for s in
               ((sb.table("sources").select("id").eq("adapter_name", "moka").execute().data) or [])]
    if not src_ids:
        return []
    rows, page = [], 1000
    for offset in range(0, 40000, page):
        chunk = (
            sb.table("jobs")
            .select("id,jd_url,title,enrich_fail_count")
            .in_("source_id", src_ids)
            .is_("summary", "null")
            .eq("status", "active")
            .lt("enrich_fail_count", 3)  # 死信：渲染连败 3 次不再重试（避免每轮反复渲染没 JD 的岗）
            # 排序键以 source_id 打头吃 150 索引；再按 id 稳定排序供 shard 切片互不重叠。
            .order("source_id").order("id")
            .range(offset, offset + page - 1)
            .execute()
            .data
        ) or []
        rows.extend(chunk)
        if len(chunk) < page or len(rows) >= limit * 3:  # 多取一些，shard 切片后仍够 limit
            break
    return rows


def _mark_fail(sb, row, dry_run):
    """渲染失败/无 JD → enrich_fail_count+1（死信老化）。dry-run 不写；写库失败静默（下轮重试）。"""
    if dry_run:
        return
    try:
        sb.table("jobs").update({"enrich_fail_count": (row.get("enrich_fail_count") or 0) + 1}) \
            .eq("id", row["id"]).execute()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Moka summary 回填器")
    ap.add_argument("--limit", type=int, default=50, help="本片最多回填多少岗（控时长）")
    ap.add_argument("--shard", type=str, default="0/1",
                    help="分片 k/n：按 id 排序后取第 k 片（多进程并行互不重叠），默认 0/1=全量")
    ap.add_argument("--dry-run", action="store_true", help="只抓取打印，不写库")
    ap.add_argument("--probe", action="store_true",
                    help="诊断模式：渲染后打印每个详情页的真实 DOM 结构（定位 JD 容器/关闭标记），不写库")
    args = ap.parse_args()

    try:
        k, n = (int(x) for x in args.shard.split("/"))
        assert 0 <= k < n
    except Exception:
        print(f"✗ 非法 --shard '{args.shard}'（应为 k/n 且 0<=k<n）")
        sys.exit(1)

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    all_rows = _fetch_targets(sb, args.limit * n)
    rows = [r for i, r in enumerate(all_rows) if i % n == k][: args.limit]
    tag = f"[shard {k}/{n}]"
    print(f"{tag} 全部待回填 {len(all_rows)}，本片认领 {len(rows)}（limit={args.limit}）")
    if not rows:
        return

    from playwright.sync_api import sync_playwright

    filled = 0
    failed = 0
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            locale="zh-CN",
        ).new_page()
        for i, row in enumerate(rows, 1):
            jd_url = row.get("jd_url") or ""
            if "#/job/" not in jd_url:
                continue
            try:
                page.goto(jd_url, wait_until="domcontentloaded", timeout=30000)
                # 智能等待：JD 容器出现即走（多数 ~1-2s），最多 9s；比固定 4.5s 快一倍。
                try:
                    page.wait_for_selector(_JD_SELECTORS[0], timeout=9000)
                    page.wait_for_timeout(700)  # 容器出现后给渲染一点稳定时间
                except Exception:
                    page.wait_for_timeout(2500)  # 容器名不匹配的租户：退回短等待再兜底抓
                if args.probe:
                    print(f"{tag} [{i}] {row.get('title')}  {jd_url}\n{_probe_dom(page)}\n")
                    continue
                jd = _scrape_jd(page)
            except Exception as e:
                failed += 1
                print(f"{tag} [{i}] render 失败 {row.get('title')}: {str(e)[:60]}")
                _mark_fail(sb, row, args.dry_run)
                continue
            summary = normalizer.clean_summary(jd) if jd else None
            if not summary:
                failed += 1
                _mark_fail(sb, row, args.dry_run)
                continue
            if args.dry_run:
                print(f"{tag} [{i}] {row.get('title')} → {summary[:50]}…")
                filled += 1
            else:
                try:
                    sb.table("jobs").update({"summary": summary}).eq("id", row["id"]).execute()
                    filled += 1
                except Exception as e:
                    failed += 1
                    print(f"{tag} [{i}] 写库失败 {row.get('title')}: {str(e)[:60]}")
            if i % 25 == 0:
                rate = (time.time() - t0) / i
                print(f"{tag} 进度 {i}/{len(rows)}  回填 {filled}  失败 {failed}  {rate:.1f}s/岗")
        browser.close()

    print(f"\n{tag} 完成：回填 {filled}，失败/无JD {failed}，"
          f"耗时 {(time.time()-t0)/60:.1f} 分钟{'（dry-run 未写库）' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
