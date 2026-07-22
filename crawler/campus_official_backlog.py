#!/usr/bin/env python3
"""校招今年精确日期 快路② —— 每日 cron：官方校招页 httpx 并发直取 → 精确日期抽取 →
判官 → 官方源门 auto-verify → 幂等写 recruitment_cycle_observations。

红线（宁缺不编）：只 auto-verify「官方招聘域名 grounding（抓的就是公司自有官方页）+ 判官
entailment」的精确日期；SPA 空壳/无日期信号的诚实跳过。不吃搜索额度（全程 httpx 抓公开页）。

用法（CI/本机，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY + SILICONFLOW_API_KEY）：
  python3 campus_official_backlog.py --company 字节跳动
  python3 campus_official_backlog.py --limit 40 --workers 6
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import db
import must_apply
import ops_runs
from campus_cycle_backlog import current_cohort, _existing_status_by_key, fetch_covered_company_names
from campus_official_extract import build_official_messages, parse_precise_claims
from campus_official_pages import official_campus_urls, fetch_first_with_signal
from insight_backlog import fetch_one_company
from insight_engine import (chat_json, judge_claim, llm_config, llm_run_health,
                            llm_run_unhealthy, reset_llm_health)
from official_gate import (decide_cycle_status, is_entailment, is_official_grounding,
                           official_hosts_from_sources)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def drain_official_one(sb, company, now):
    """单公司快路② drain。永不抛。返回统计 dict。"""
    stats = {"company": company, "claims_seen": 0, "verified": 0, "draft": 0, "skipped": None}

    profile = fetch_one_company(sb, company)
    if not profile:
        return {"company": company, "skipped": "no_company"}
    if not llm_config()["configured"]:
        return {"company": company, "skipped": "llm_not_configured"}

    try:
        source_rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("company,source_url").eq("company", company))
    except Exception as e:
        print(f"  [campus-official-err] {company} 查源失败: {type(e).__name__}: {str(e)[:120]}")
        return {"company": company, "skipped": "sources_error"}
    official_hosts = official_hosts_from_sources(
        [r.get("source_url") for r in source_rows if r.get("source_url")])
    if not official_hosts:
        return {"company": company, "skipped": "no_official_host"}

    urls = official_campus_urls(source_rows, official_hosts)
    page_url, page_text = fetch_first_with_signal(urls)
    if not page_url:
        return {"company": company, "skipped": "no_campus_page_signal"}
    if not is_official_grounding(page_url, official_hosts):
        return {"company": company, "skipped": "page_not_official"}

    try:
        claims = parse_precise_claims(chat_json(build_official_messages(company, page_text)), now)
    except Exception as e:
        print(f"  [campus-official-err] {company} 抽取失败: {type(e).__name__}: {str(e)[:120]}")
        return {"company": company, "skipped": "writer_error"}
    stats["claims_seen"] = len(claims)
    if not claims:
        return stats

    grad_class, valid_until = current_cohort(now)
    existing = _existing_status_by_key(sb, profile["id"], grad_class)

    for c in claims:
        ev_key = (c["season"], c["batch"], c["event"])
        if existing.get(ev_key) == "verified":
            continue  # verified 事实不可覆盖（不变量）
        claim_sentence = f"{company}{c['season']}{c['batch']}{c['value_text']}"
        try:
            judge = judge_claim(claim_sentence, page_text)
        except Exception as e:
            print(f"  [campus-official-err] {company} 判官失败: {type(e).__name__}: {str(e)[:120]}")
            continue
        if not is_entailment(judge.get("verdict"), judge.get("confidence")):
            continue
        # 官方页 grounding=True → decide 返回 ('verified','official_notice','high')
        status, source_kind, confidence = decide_cycle_status(
            is_official_grounding(page_url, official_hosts), 1)
        time_expr_type = "日期范围" if c["date_end"] else "精确日期"
        row = {
            "company_id": profile["id"], "grad_class": grad_class,
            "season": c["season"], "batch": c["batch"], "event": c["event"],
            "time_expr_type": time_expr_type, "value_text": c["value_text"],
            "month_start": c["month_start"], "month_end": c["month_end"],
            "date_start": c["date_start"], "date_end": c["date_end"],
            "confidence": confidence, "evidence_url": page_url,
            "evidence_excerpt": (c["quote"] or "")[:200], "evidence_fetched_at": _now_iso(),
            "source_kind": source_kind, "verify_status": status,
            "valid_until": valid_until, "created_by": "cron",
        }
        try:
            sb.table("recruitment_cycle_observations").insert(row).execute()
        except Exception as e:
            print(f"  [campus-official-err] {company} 写入失败: {type(e).__name__}: {str(e)[:120]}")
            continue
        if status == "verified":
            existing[ev_key] = "verified"
        stats["verified" if status == "verified" else "draft"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser(description="校招今年精确日期 快路②（官方页并发直取，宁缺不编）")
    ap.add_argument("--company", default="")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    now = datetime.now(timezone.utc)
    started_at = _now_iso()
    reset_llm_health()

    if args.company:
        results = [drain_official_one(sb, args.company, now)]
    else:
        by_industry = must_apply.by_industry()
        covered = fetch_covered_company_names(sb)  # 已有 verified 时间线的公司本轮不重复（含精确日期）
        seen, targets = set(), []
        for _ind, companies in (by_industry or {}).items():
            for entry in (companies or []):
                name = (entry.get("name") or "").strip() if isinstance(entry, dict) else ""
                if name and name not in seen and name not in covered:
                    seen.add(name)
                    targets.append(name)
        targets = targets[:max(0, args.limit)]
        print(f"[campus_official_backlog] 目标 {len(targets)} 家（已覆盖 {len(covered)} 家跳过），workers={args.workers}")
        results = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {ex.submit(drain_official_one, sb, name, now): name for name in targets}
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({"company": futs[fut], "skipped": f"crash:{type(e).__name__}"})

    processed = len(results)
    verified = sum(r.get("verified", 0) for r in results)
    draft = sum(r.get("draft", 0) for r in results)
    for r in results:
        print(f"  {r.get('company')}: {r.get('skipped') or 'ok'} "
              f"verified={r.get('verified', 0)} draft={r.get('draft', 0)}")

    ops_runs.record_ops_run(
        sb, "campus_official_backlog",
        {"companies_processed": processed, "verified": verified, "draft": draft},
        status=ops_runs.status_from_counts(processed, 0),
        started_at=started_at, finished_at=_now_iso())

    if llm_run_unhealthy():
        h = llm_run_health()
        print(f"✗ LLM 整体失败（ok={h['ok']} fail={h['fail']} account_error={h['account_error']}）")
        sys.exit(1)


if __name__ == "__main__":
    main()
