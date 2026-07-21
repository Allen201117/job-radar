#!/usr/bin/env python3
"""校招往年时间线 B3 —— 每日 cron drain：单公司搜索 → 结构化 writer(B1) → 判官 → 官方源门(B2)
→ 幂等写 recruitment_cycle_observations。

红线（选项 A，创始人 2026-07-21 拍板）：auto-verify 只在「官方招聘域名 grounding + 判官 entailment」
同时成立时发生；够不着官方证据的一律停 draft（RLS 只读 verified，用户看不到）。宁缺不编。

用法（CI / 本机，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY + SILICONFLOW_API_KEY +
至少一个搜索源 key；迁移 182 已应用）：
  python3 campus_cycle_backlog.py --company 字节跳动   # 单公司现查（调试用）
  python3 campus_cycle_backlog.py --limit 8            # 每日批量（塌陷行业优先）
"""
import argparse
import os
import random
import sys
from datetime import datetime, timezone

import db
import must_apply
import ops_runs
import search_router
from campus_cycle_extract import build_messages, parse_cycle_claims
from insight_backlog import fetch_one_company
from insight_engine import chat_json, judge_claim, llm_config, llm_run_health, llm_run_unhealthy, reset_llm_health
from official_gate import (
    decide_cycle_status,
    is_entailment,
    is_official_grounding,
    official_hosts_from_sources,
    registrable_host,
)

# 塌陷行业（同 auto_discover.CAMPUS_GAP_INDUSTRIES，用户反馈校招时间线覆盖薄弱，P2 设计文档定调）优先补。
COLLAPSED_INDUSTRIES = ("传媒/文娱", "物流/供应链", "教育", "金融")

_ROUTER = search_router.default_router()  # 多源搜索；与 T3(insight_backlog) 共用同一套每日预算


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _month_overlap(a1, b1, a2, b2):
    """两个月份区间 [a1,b1] [a2,b2] 是否重叠（选项 B 放宽：重叠即视为「时间一致」）。
    入参已保证 a<=b（me 缺省时等于 ms）。不处理跨年环绕（校招批次区间不跨年）。"""
    return max(a1, a2) <= min(b1, b2)


def current_cohort(now):
    """本轮默认写入的目标届别（grad_class）+ 该届失效日（valid_until）。
    规则：5 月起「下一届」进入秋招季，把 grad_class 滚到下一届；1-4 月仍算当前届的春招收尾。
    例：2026-07 → ("2027届","2027-06-30")；2027-03 → ("2027届","2027-06-30")。"""
    grad_year = now.year + 1 if now.month >= 5 else now.year
    return f"{grad_year}届", f"{grad_year}-06-30"


def select_cycle_targets(must_apply_by_industry, covered_company_names, cap, seed=0):
    """纯函数：挑本轮要 drain 时间线的公司。塌陷行业（COLLAPSED_INDUSTRIES）优先；已有 verified
    时间线记录的公司排除（幂等，不重复补）；同优先级内按 seed 轮转（避免每天死磕同一批），封顶 cap。
    镜像 auto_discover.plan_campus_gap_targets 的排序风格。返回 [{company, industry}]。"""
    covered = {str(c).strip() for c in (covered_company_names or []) if str(c).strip()}
    seen, priority, rest = set(), [], []
    for industry, companies in (must_apply_by_industry or {}).items():
        for entry in (companies or []):
            name = (entry.get("name") or "").strip() if isinstance(entry, dict) else ""
            if not name or name in seen or name in covered:
                continue
            seen.add(name)
            target = {"company": name, "industry": industry}
            (priority if industry in COLLAPSED_INDUSTRIES else rest).append(target)
    rng = random.Random(seed)
    rng.shuffle(priority)
    rng.shuffle(rest)
    return (priority + rest)[:max(0, int(cap or 0))]


def fetch_covered_company_names(sb):
    """已有 ≥1 条 verified 校招时间线记录的公司名集合（幂等：这些公司本轮不再重复挑选）。
    ⚠️ 分页拉全量（同项目其它队列查询惯例）：该表会随时间增长，避免将来撞 PostgREST 1000 行硬顶。"""
    verified_rows = db.fetch_all_rows(
        lambda: sb.table("recruitment_cycle_observations").select("company_id").eq("verify_status", "verified"))
    ids = sorted({r.get("company_id") for r in verified_rows if r.get("company_id")})
    if not ids:
        return set()
    names = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        rows = sb.table("company_profiles").select("id,company").in_("id", chunk).execute().data or []
        for r in rows:
            if r.get("company"):
                names.add(r["company"])
    return names


def _existing_status_by_key(sb, company_id, grad_class):
    """该公司该届别已有的 (season,batch,event) → verify_status（同 key 多行时 verified 优先）。
    用于幂等 + 冲突判断：verified 已定案的事实绝不覆盖；draft 不无限堆积重复。"""
    rows = (sb.table("recruitment_cycle_observations")
            .select("season,batch,event,verify_status")
            .eq("company_id", company_id).eq("grad_class", grad_class)
            .execute().data) or []
    out = {}
    for r in rows:
        key = (r.get("season"), r.get("batch"), r.get("event"))
        if key not in out or r.get("verify_status") == "verified":
            out[key] = r.get("verify_status")
    return out


def drain_one_company(sb, company):
    """单公司往年时间线 drain：搜索 → writer 抽取(B1) → 逐 claim 判官 + 官方源门(B2) → 幂等写入。
    永不抛（cron 无人值守，单公司异常不能拖垮整批）。返回统计 dict。"""
    stats = {
        "company": company, "claims_seen": 0, "verified": 0, "draft": 0,
        "skipped_conflict": 0, "skipped_dup_draft": 0, "skipped_bad_index": 0,
    }

    profile = fetch_one_company(sb, company)
    if not profile:
        return {"company": company, "skipped": "no_company"}

    if not llm_config()["configured"]:
        return {"company": company, "skipped": "llm_not_configured"}

    if _ROUTER.remaining(sb) <= 0:
        return {"company": company, "budget_exhausted": True}

    query = f"{company} 校招 网申 提前批 正式批 时间 月份"
    try:
        results = _ROUTER.search(sb, query)
    except Exception as e:
        print(f"  [campus-cycle-err] {company} 搜索失败: {type(e).__name__}: {str(e)[:160]}")
        return {"company": company, "skipped": "search_error"}
    if not results:
        return {"company": company, "skipped": "no_search_results"}

    try:
        source_rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("company,source_url").eq("company", company))
    except Exception as e:
        # 查失败就当没有官方源（保守方向：最多让本轮本该 verified 的降级成 draft，绝不会因为
        # 查询异常反而误判出「官方」而错误自动发布）。
        print(f"  [campus-cycle-err] {company} 查询官方源列表失败: {type(e).__name__}: {str(e)[:160]}")
        source_rows = []
    official_hosts = official_hosts_from_sources(
        [r.get("source_url") for r in source_rows if r.get("source_url")])

    try:
        claims = parse_cycle_claims(chat_json(build_messages(company, results)))
    except Exception as e:
        print(f"  [campus-cycle-err] {company} writer 失败: {type(e).__name__}: {str(e)[:160]}")
        return {"company": company, "skipped": "writer_error"}

    stats["claims_seen"] = len(claims)
    if not claims:
        return stats

    grad_class, valid_until = current_cohort(datetime.now(timezone.utc))
    existing_status = _existing_status_by_key(sb, profile["id"], grad_class)

    # ① 逐 claim 判官，收集过 entailment 的（季/批/事件 + 月份区间 + 去重域名 + 是否官方）。
    entail = []
    for claim in claims:
        idx = claim.get("source_idx")
        if not isinstance(idx, int) or idx < 0 or idx >= len(results):
            stats["skipped_bad_index"] += 1
            continue
        g = results[idx]
        claim_sentence = f"{company}{claim['season']}{claim['batch']}约{claim['value_text']}{claim['event']}"
        try:
            judge = judge_claim(claim_sentence, g.get("text") or g.get("snippet") or "")
        except Exception as e:
            print(f"  [campus-cycle-err] {company} 判官失败: {type(e).__name__}: {str(e)[:160]}")
            continue
        if not is_entailment(judge.get("verdict"), judge.get("confidence")):
            continue  # 判官不支持原文 → 丢（宁缺不编）
        ms = claim["month_start"]
        me = claim["month_end"] if claim["month_end"] is not None else ms
        entail.append({
            "season": claim["season"], "batch": claim["batch"], "event": claim["event"],
            "ms": ms, "me": me, "host": registrable_host(g.get("url")),
            "official": is_official_grounding(g.get("url"), official_hosts),
            "claim": claim, "url": g.get("url"), "quote": claim.get("quote"),
        })

    # ② 按 event(季/批/事件)分组；组内按「月份区间重叠」聚共识簇（选项 B，2026-07-21 放宽）。
    #    anchor = 让最多不同源与之重叠的那条真实区间；≥2 个不同源重叠即发布。一个 event 只写一条。
    groups = {}
    for e in entail:
        groups.setdefault((e["season"], e["batch"], e["event"]), []).append(e)

    for ev_key, items in groups.items():
        season, batch, event = ev_key
        prior = existing_status.get(ev_key)
        if prior == "verified":
            # 已定案事实绝不覆盖（不变量：verified 只能靠 superseded_by 改错，本 cron 不碰）
            stats["skipped_conflict"] += 1
            continue
        # 选 anchor：与之月份区间重叠的「不同源」最多；并列取区间最窄、再取起始月最小（确定性）。
        best = None
        for anchor in items:
            cluster = [e for e in items if _month_overlap(e["ms"], e["me"], anchor["ms"], anchor["me"])]
            n_pub = len({e["host"] for e in cluster})
            rank = (n_pub, -(anchor["me"] - anchor["ms"]), -anchor["ms"])
            if best is None or rank > best[0]:
                best = (rank, anchor, cluster, n_pub)
        _, anchor, cluster, n_pub = best
        has_official = any(e["official"] for e in cluster)
        status, source_kind, confidence = decide_cycle_status(has_official, n_pub)
        if prior == "draft" and status == "draft":
            stats["skipped_dup_draft"] += 1  # 已有草稿、这条也草稿 → 不堆积
            continue

        aclaim = anchor["claim"]
        ev_src = next((e for e in cluster if e["official"]), anchor)  # 证据优先取簇内官方源
        time_expr_type = "月" if aclaim["month_end"] in (None, aclaim["month_start"]) else "日期范围"
        row = {
            "company_id": profile["id"],
            "grad_class": grad_class,
            "season": season,
            "batch": batch,
            "event": event,
            "time_expr_type": time_expr_type,
            "value_text": aclaim["value_text"],
            "month_start": aclaim["month_start"],
            "month_end": aclaim["month_end"],
            "confidence": confidence,
            "evidence_url": ev_src["url"],
            "evidence_excerpt": (ev_src["quote"] or "")[:200],
            "evidence_fetched_at": _now_iso(),
            "source_kind": source_kind,
            "verify_status": status,
            "valid_until": valid_until,
            "created_by": "cron",
        }
        try:
            sb.table("recruitment_cycle_observations").insert(row).execute()
        except Exception as e:
            print(f"  [campus-cycle-err] {company} 写入失败: {type(e).__name__}: {str(e)[:160]}")
            continue
        if status == "verified":
            existing_status[ev_key] = "verified"
        stats["verified" if status == "verified" else "draft"] += 1

    return stats


def main():
    ap = argparse.ArgumentParser(description="校招往年时间线自动填充（B3 drain，官方源门宁缺不编）")
    ap.add_argument("--company", default="", help="只填充单家公司（workflow_dispatch 调试用）")
    ap.add_argument("--limit", type=int, default=8, help="本次最多处理多少家公司（塌陷行业优先，批量模式用）")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    started_at = _now_iso()
    reset_llm_health()

    if args.company:
        results = [drain_one_company(sb, args.company)]
    else:
        by_industry = must_apply.by_industry()
        covered = fetch_covered_company_names(sb)
        seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
        targets = select_cycle_targets(by_industry, covered, args.limit, seed=seed)
        print(f"[campus_cycle_backlog] 已覆盖(verified)={len(covered)} 家 → 本轮目标 {len(targets)} 家")
        results = []
        for t in targets:
            if _ROUTER.remaining(sb) <= 0:
                print("[campus_cycle_backlog] 搜索额度用尽，本轮提前结束")
                break
            results.append(drain_one_company(sb, t["company"]))

    companies_processed = len(results)
    verified = sum(r.get("verified", 0) for r in results)
    draft = sum(r.get("draft", 0) for r in results)
    skipped = sum(1 for r in results if r.get("skipped") or r.get("budget_exhausted"))
    for r in results:
        tag = ("budget_exhausted" if r.get("budget_exhausted") else r.get("skipped")) or "ok"
        print(f"  {r.get('company')}: {tag} verified={r.get('verified', 0)} draft={r.get('draft', 0)}")

    ops_runs.record_ops_run(
        sb,
        "campus_cycle_backlog",
        {
            "companies_processed": companies_processed,
            "verified": verified,
            "draft": draft,
            "skipped": skipped,
        },
        status=ops_runs.status_from_counts(companies_processed, 0),
        started_at=started_at,
        finished_at=_now_iso(),
    )

    # 真实健康信号：LLM 整体失败（账户欠费 / 鉴权失效）时标红，别让 workflow 绿灯盖住故障。
    if llm_run_unhealthy():
        h = llm_run_health()
        print(f"✗ LLM 整体失败（ok={h['ok']} fail={h['fail']} account_error={h['account_error']}）"
              f"——大概率 SiliconFlow 账户欠费 / key 失效，本轮没产出。")
        sys.exit(1)


if __name__ == "__main__":
    main()
