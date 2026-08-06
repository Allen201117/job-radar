"""校招板块批量探测 —— 编排与 IO（纯判据在 campus_board_probe.py）。

两层设计，因为第二层很贵：
  **层1 廉价分诊（httpx，秒级）**：推导候选 URL → robots 门 → HTTP 可达且页面像个真板块。
      152 个候选实测 20 秒跑完、命中 140。
  **层2 昂贵验收（CI 里跑）**：插 disabled 源 → 真抓一轮 → 回读香港库
      → 非重复门（比岗位身份）→ 健康岗 ≥1 → 才 enable；否则删源删脏岗。
      moka 是浏览器 adapter（单源 2-5min），所以这层必须在 CI 的时间预算里跑，不能塞进层1。

为什么分两层而不是一把梭：层1 能把 152 个候选砍到 140，更重要的是**把明显不可能的
（robots 禁止、404、空壳页）挡在浏览器抓取之前**——否则每个都要花 2-5 分钟才知道不行。

台账（`campus_board_attempts`）记录每家探到哪步、为什么失败、什么时候复查，避免天天空烧。
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

import campus_board_probe as P
import db
import jobs_db
import robots

TRIAGE_MIN_BYTES = 15000      # 小于这个基本是 400/空壳页（实测真板块 17KB~270KB）
TRIAGE_WORKERS = 12
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 退避天数是纯判据，连同校招季加速一起放在 campus_board_probe.RETRY_DAYS / retry_days()。


def _log(msg):
    print(f"[campus-probe] {msg}", flush=True)


def existing_campus_tenants(sources):
    """已经有校招板块源的租户，跳过不再探。"""
    have = set()
    for s in sources:
        ad, url = s.get("adapter_name"), s.get("source_url") or ""
        if ad == "moka" and re.search(r"campus[-_]", url, re.I):
            have.add(("moka", P.moka_tenant(url)))
        elif ad == "hotjob" and "school.html" in url.lower():
            have.add(("hotjob", str(P.hotjob_tenant(url))))
    return have


def derive_candidates(sources):
    """全库源 → 去重后的校招板块候选 [(既有源行, 候选URL)]。"""
    have = existing_campus_tenants(sources)
    seen, out = set(), []
    for s in sources:
        ad, url = s.get("adapter_name"), s.get("source_url") or ""
        if ad == "moka":
            key = ("moka", P.moka_tenant(url))
        elif ad == "hotjob":
            key = ("hotjob", str(P.hotjob_tenant(url)))
        else:
            continue
        if key[1] in (None, "None") or key in have or key in seen:
            continue
        candidate = P.campus_candidate_url(ad, url)
        if candidate:
            seen.add(key)
            out.append((s, candidate))
    return out


def triage_one(item):
    """层1：robots + HTTP 可达 + 页面像个真板块。返回 (源行, 候选URL, 结论, 最终URL)。"""
    source, candidate = item
    verdict = robots.check_robots(candidate)
    if not verdict.get("allowed"):
        # kuaishou 校招站教训：本地 adapter 跑得欢，但 robots 是 Disallow:/ → 生产一条不进
        return (source, candidate, "robots_blocked", "")
    try:
        resp = httpx.get(candidate, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    except Exception:
        return (source, candidate, "unreachable", "")
    if resp.status_code != 200 or len(resp.text) < TRIAGE_MIN_BYTES:
        return (source, candidate, "unreachable", str(resp.url))
    # moka 不带 portal id 时会 302 到该租户正确的校招 portal，用最终 URL 建源
    return (source, candidate, "triage_ok", str(resp.url))


def board_job_identities(conn, source_id):
    """从香港库取某源的岗位身份集合（用于非重复门）。"""
    rows = jobs_db.fetch_all(conn, """
        select jd_url from jobs where source_id = %s and status = 'active' limit 2000
    """, (str(source_id),))
    return P.job_identities(r["jd_url"] for r in rows)


def upsert_attempt(supabase, company, adapter, candidate_url, state, note=""):
    """台账写入，失败只告警（旁路，绝不阻断主流程）。"""
    now = datetime.now(timezone.utc)
    days = P.retry_days(state, now.month)
    row = {
        "company": company,
        "adapter_name": adapter,
        "candidate_url": candidate_url,
        "state": state,
        "note": (note or "")[:500],
        "recheck_after": (now + timedelta(days=days)).date().isoformat(),
        "updated_at": now.isoformat(),
    }
    try:
        supabase.table("campus_board_attempts").upsert(row, on_conflict="company,adapter_name").execute()
    except Exception as e:
        _log(f"⚠️ 台账写入失败（不影响探测结果）：{type(e).__name__}: {e}")


def skip_by_ledger(supabase, candidates):
    """按台账 recheck_after 跳过还没到复查日的，避免天天空烧。"""
    try:
        resp = supabase.table("campus_board_attempts").select("company, adapter_name, recheck_after").execute()
    except Exception:
        return candidates          # 台账读不到就别拦着主流程
    today = datetime.now(timezone.utc).date().isoformat()
    blocked = {
        (r["company"], r["adapter_name"])
        for r in (resp.data or [])
        if (r.get("recheck_after") or "") > today
    }
    return [(s, c) for s, c in candidates
            if (s.get("company"), s.get("adapter_name")) not in blocked]


def main():
    ap = argparse.ArgumentParser(description="校招板块批量探测")
    ap.add_argument("--apply", action="store_true",
                    help="真写库（插 disabled 源交给验收门）；缺省只 dry-run 报告")
    ap.add_argument("--limit", type=int, default=40, help="本轮最多处理多少个候选")
    args = ap.parse_args()

    supabase = db.get_supabase()
    sources = db.get_sources(supabase)
    candidates = derive_candidates(sources)
    _log(f"推导候选 {len(candidates)} 个 / 全库 {len(sources)} 源")
    candidates = skip_by_ledger(supabase, candidates)[:args.limit]
    _log(f"扣除台账未到复查日的，本轮处理 {len(candidates)} 个")
    if not candidates:
        return 0

    with ThreadPoolExecutor(max_workers=TRIAGE_WORKERS) as ex:
        triaged = list(ex.map(triage_one, candidates))

    ok = [t for t in triaged if t[2] == "triage_ok"]
    for source, candidate, state, _final in triaged:
        if state != "triage_ok":
            upsert_attempt(supabase, source.get("company"), source.get("adapter_name"), candidate, state)
    _log(f"层1 分诊：{len(ok)} 个板块存在 / {len(triaged) - len(ok)} 个排除")

    if not args.apply:
        for source, candidate, _s, final in ok:
            _log(f"  [dry-run] 待建源 {source.get('company')} → {final}")
        _log("dry-run 结束（加 --apply 才写库）")
        return 0

    # 层2：插 disabled 源，交给 campus_board_verify 在下一步真抓 + 非重复门 + 健康岗验收。
    created = 0
    for source, candidate, _s, final in ok:
        row = {
            "company": source.get("company"),
            "source_url": final or candidate,
            "adapter_name": source.get("adapter_name"),
            "crawl_method": source.get("crawl_method") or "http",
            "regions": source.get("regions") or ["CN"],
            "segment": source.get("segment"),
            "industry": source.get("industry"),
            "enabled": False,          # ⚠️ 先 disabled，验收通过才 enable
        }
        try:
            supabase.table("sources").insert(row).execute()
            created += 1
            upsert_attempt(supabase, source.get("company"), source.get("adapter_name"),
                           final or candidate, "source_added", "待验收：真抓+非重复+健康岗")
        except Exception as e:
            upsert_attempt(supabase, source.get("company"), source.get("adapter_name"),
                           final or candidate, "insert_failed", f"{type(e).__name__}: {e}")
    _log(f"层2 已插入 {created} 个 disabled 候选源，等验收门放行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
