#!/usr/bin/env python3
"""Moka 岗位 summary 回填器（浏览器逐岗渲染抓 JD）。

为何独立脚本而非接入 run.py：Moka 列表 JSON 加密、JD 只在 `{base}#/job/{uuid}` 详情页 DOM 里，
补 summary 必须**逐岗浏览器渲染**（~5s/岗）。把 5.8k 岗渲染塞进每日 cron 会拖垮夜爬（数小时），
故拆成独立、可限量、幂等的回填器——按需/周期（如每周一次 GitHub Action）跑，只补 summary 为空的 Moka 岗。

用法（本机/CI，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）：
  set -a; source ../.env.local; set +a
  python3 scripts/backfill_moka_summaries.py --limit 50        # 补 50 个
  python3 scripts/backfill_moka_summaries.py --limit 5 --dry-run

只读 + 只更新 summary 字段（不碰 jd_url/title 等），幂等（只取 summary 为空的 Moka 岗）。
Beisen 不在此脚本：其详情页冷渲染近乎空壳（反爬需先访列表暖 session），属另一套机制。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler"))
import db  # noqa: E402
import normalizer  # noqa: E402

# 实测可抓到 JD 正文的容器（class 含 description/Description）；兜底用 body 文本。
_JD_SELECTORS = ("[class*=escription]", "[class*=jobDetail]", "[class*=detail-content]")
_NOISE = ("我知道了", "立即投递", "在招职位", "分享", "收藏")


def _scrape_jd(page) -> str:
    best = ""
    for sel in _JD_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                t = (el.inner_text() or "").strip()
                if len(t) > len(best):
                    best = t
        except Exception:
            continue
    # 过滤明显的非 JD 噪声短文本
    if best and len(best) < 20 and any(n in best for n in _NOISE):
        return ""
    return best


def main():
    ap = argparse.ArgumentParser(description="Moka summary 回填器")
    ap.add_argument("--limit", type=int, default=50, help="本次最多回填多少岗（控时长）")
    ap.add_argument("--dry-run", action="store_true", help="只抓取打印，不写库")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    rows = (
        sb.table("jobs")
        .select("id,jd_url,title")
        .like("jd_url", "%mokahr%")
        .is_("summary", "null")
        .eq("status", "active")
        .limit(args.limit)
        .execute()
        .data
    ) or []
    print(f"待回填 Moka 空 summary 岗：{len(rows)}（limit={args.limit}）")
    if not rows:
        return

    from playwright.sync_api import sync_playwright

    filled = 0
    failed = 0
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
                page.wait_for_timeout(4500)
                jd = _scrape_jd(page)
            except Exception as e:
                print(f"  [{i}] render 失败 {row.get('title')}: {str(e)[:60]}")
                failed += 1
                continue
            summary = normalizer.clean_summary(jd) if jd else None
            if not summary:
                print(f"  [{i}] 无 JD：{row.get('title')}")
                failed += 1
                continue
            if args.dry_run:
                print(f"  [{i}] {row.get('title')} → {summary[:60]}…")
            else:
                try:
                    sb.table("jobs").update({"summary": summary}).eq("id", row["id"]).execute()
                    print(f"  [{i}] ✔ {row.get('title')} → {summary[:50]}…")
                    filled += 1
                except Exception as e:
                    print(f"  [{i}] 写库失败 {row.get('title')}: {str(e)[:60]}")
                    failed += 1
        browser.close()

    print(f"\n完成：回填 {filled}，失败/无JD {failed}{'（dry-run 未写库）' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
