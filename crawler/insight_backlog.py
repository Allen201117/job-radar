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
import insight_engine as E
import official_cninfo as CN
import official_edgar as EDG
import search_router
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


def _existing_listing(sb, company_id):
    """该公司 listing 条目（任意 origin）；wikidata/official 共用一行，官方源就地升级覆盖，避免重复卡片。"""
    rows = (sb.table("insight_items").select("id")
            .eq("company_id", company_id).eq("dimension", "listing")
            .limit(1).execute().data) or []
    return rows[0]["id"] if rows else None


def write_listing(sb, company_id, li):
    """写 / 更新 listing 洞察 + 溯源（仅新建时建一次来源）。li = wikidata.facts_to_listing 或 official_edgar 同形。"""
    item = {
        "company_id": company_id, "dimension": "listing", "grade": "fact",
        "title": li["title"], "content": li["content"], "payload": li["payload"],
        "origin": li.get("origin", "wikidata"), "deidentified": True, "status": "active",
        "time_window": f"上市状态截至 {datetime.now(timezone.utc).year} 年",
        "last_verified_at": _now(),
    }
    existing = _existing_listing(sb, company_id)
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
    except Exception as e:
        print(f"  [wd-err] {profile['company']}: {type(e).__name__}: {str(e)[:140]}")
        facts = None
    if not facts:
        # 查无也记一轮 checked_at（避免每次重试查无的公司）；不算硬失败
        try:
            sb.table("company_profiles").update({"insight_checked_at": _now()}).eq("id", profile["id"]).execute()
        except Exception:
            return "err"
        return "noface"
    try:
        # 官方披露优先：EDGAR(美股·ticker，更权威+最新申报) → 巨潮(A股·名，默认关，须 INSIGHT_CNINFO_ENABLED) → Wikidata 回落
        li = EDG.get_listing_by_ticker(facts.get("ticker")) if facts.get("ticker") else None
        if not li and CN.enabled():
            li = CN.get_listing_by_name(profile["company"], profile.get("aliases"))
        if not li:
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


# ============================================================
# T3 经验层：多源搜索（博查/Tavily/Serper/千帆，search_router）→ 验证引擎（接地→判官→共识）→ 写 active/pending_review
# 各源受每日额度：drain_t3 串行 + search_usage/qianfan_usage 持久预算守门，绝不冲破各自日顶。
# 见 docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md。
# ============================================================
T3_TTL_DAYS = 180  # 经验类复核更慢
T3_QUERY = "{c} 工作体验 加班 文化 薪资 待遇 怎么样"
_ROUTER = search_router.default_router()  # 多源搜索；未配 key 的源自动跳过（配哪个用哪个）


def _pick_sources(results, claim, max_n=3):
    """给条目选附来源：被引用那条 + 其它不同 publisher 的，凑 ≥2 个不同 publisher 以过共识门。"""
    idx = claim.get("source_idx")
    chosen, seen = [], set()
    if isinstance(idx, int) and 0 <= idx < len(results):
        chosen.append(results[idx]); seen.add(results[idx].get("publisher"))
    for r in results:
        if len(chosen) >= max_n:
            break
        if r in chosen or r.get("publisher") in seen:
            continue
        chosen.append(r); seen.add(r.get("publisher"))
    return chosen


def write_experience(sb, company_id, claim, sources, judge, status):
    """写一条 T3 经验条目（dimension=culture, origin=public_web）+ 多来源（去标识、仅短 excerpt，禁整段 UGC）。"""
    item_id = str(uuid.uuid4())
    sb.table("insight_items").insert({
        "id": item_id, "company_id": company_id, "dimension": "culture",
        "grade": claim.get("grade") or "experience",
        "title": claim.get("title") or "公开讨论 · 群体印象",
        "content": claim.get("content"),
        "sample_size": int(claim["sample_size"]) if str(claim.get("sample_size") or "").isdigit() else None,
        "payload": {}, "origin": "public_web", "deidentified": True, "status": status,
        "time_window": claim.get("time_window") or f"{datetime.now(timezone.utc).year} 观察",
        "verification": {"verdict": judge.get("verdict"), "confidence": judge.get("confidence")},
        "last_verified_at": _now(),
        # 保鲜：1 年后过期 → 过期下架巡检(insight_sweep)自动退役；180 天复核会续期。不长期滞留老聚合。
        "valid_until": (datetime.now(timezone.utc) + timedelta(days=365)).date().isoformat(),
    }).execute()
    for s in sources:
        sid = str(uuid.uuid4())
        sb.table("insight_sources").insert({
            "id": sid, "url": s["url"], "publisher": s.get("publisher"),
            "source_kind": "community_deidentified",
            "excerpt": (claim.get("quote") or s.get("snippet") or "")[:200],
            "deidentified": True,
        }).execute()
        sb.table("insight_item_sources").insert({"item_id": item_id, "source_id": sid}).execute()


def fetch_t3_queue(sb, limit):
    """T3 队列：notable（已 T2 富化、founded_year 非空）+ t3 待处理/超期 + 未超死信。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=T3_TTL_DAYS)).isoformat()
    q = (sb.table("company_profiles").select("id,company,aliases,t3_fail_count")
         .lt("t3_fail_count", MAX_FAIL)
         .not_.is_("founded_year", "null")
         .or_(f"t3_checked_at.is.null,t3_checked_at.lt.{cutoff}"))
    if limit:
        q = q.limit(limit)
    return (q.execute().data) or []


def enrich_company_t3(sb, profile):
    """单公司 T3：千帆检索 → run_pipeline(culture) → 写。返回 'wrote' | 'empty' | 'err'。永不抛。"""
    try:
        results = _ROUTER.search(sb, T3_QUERY.format(c=profile["company"]))
        # 额度由 router 在各 provider 内部按次记账，勿在此重复 consume
    except Exception:
        results = []
    if not results:
        try:
            sb.table("company_profiles").update({"t3_checked_at": _now()}).eq("id", profile["id"]).execute()
        except Exception:
            return "err"
        return "empty"
    try:
        pipeline = E.run_pipeline(profile["company"], "culture", results)
        pubs = len({r.get("publisher") for r in results if r.get("publisher")})
        print(f"  [t3] {profile['company']}: 多源检索 {len(results)} 条/{pubs} 域 → "
              f"claims {len(pipeline)} → {[e['status'] for e in pipeline]}")
        run_start = _now()
        wrote_any = False
        for entry in pipeline:
            if entry["status"] == "drop":
                continue
            claim = dict(entry["claim"])
            # 经验类样本量 = 检索到的公开讨论篇数（每条结果=一篇讨论；诚实满足读时门 ≥5 + 来源 ≥2 publisher）
            if not str(claim.get("sample_size") or "").isdigit():
                claim["sample_size"] = len(results)
            write_experience(sb, profile["id"], claim,
                             _pick_sources(results, entry["claim"]), entry.get("judge") or {}, entry["status"])
            wrote_any = True
        if wrote_any:
            # 替换旧代：退役本次之前写入的 public_web culture，避免新旧聚合堆积 / 老内容滞留（保即时性）
            sb.table("insight_items").update({"status": "retired"}) \
                .eq("company_id", profile["id"]).eq("origin", "public_web") \
                .eq("dimension", "culture").eq("status", "active") \
                .lt("last_verified_at", run_start).execute()
        sb.table("company_profiles").update({"t3_checked_at": _now()}).eq("id", profile["id"]).execute()
        return "wrote"
    except Exception:
        try:
            sb.table("company_profiles").update({
                "t3_fail_count": (profile.get("t3_fail_count") or 0) + 1, "t3_checked_at": _now(),
            }).eq("id", profile["id"]).execute()
        except Exception:
            pass
        return "err"


def drain_t3(sb, limit=0):
    """T3 drain（多源搜索，各源受每日额度 → 串行 + 预算守门，绝不冲破各自日顶）。"""
    if not _ROUTER.is_configured():
        print("✗ 无搜索源配置（BOCHA/TAVILY/SERPER/千帆 key 全缺或熔断）→ 跳过 T3")
        return {"wrote": 0, "empty": 0, "err": 0, "budget_left": 0}
    remaining = _ROUTER.remaining(sb)
    print(f"搜索源当日剩余总额度：{remaining}")
    if remaining <= 0:
        return {"wrote": 0, "empty": 0, "err": 0, "budget_left": 0}
    cap = remaining if not limit else min(remaining, limit)
    rows = fetch_t3_queue(sb, cap)
    print(f"T3 队列（notable·待富化）取 {len(rows)} 家（额度封顶 {cap}）")
    stat = {"wrote": 0, "empty": 0, "err": 0}
    for p in rows:
        if _ROUTER.remaining(sb) <= 0:
            print("额度用尽，停"); break
        stat[enrich_company_t3(sb, p)] += 1
    stat["budget_left"] = _ROUTER.remaining(sb)
    print(f"T3 完成：{stat}")
    return stat


def main():
    ap = argparse.ArgumentParser(description="职业洞察富化 drain（T2 Wikidata 默认 / --t3 经验层）")
    ap.add_argument("--seed-from-sources", action="store_true", help="先给所有源公司建画像占位")
    ap.add_argument("--t3", action="store_true", help="跑 T3 经验层（千帆检索，受 50/日额度）而非 T2")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理多少公司（0=全部/额度上限）")
    ap.add_argument("--workers", type=int, default=4, help="T2 并发线程数（对 Wikidata 礼貌，建议 ≤6）")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    if args.t3:
        drain_t3(sb, limit=args.limit)
        return
    if args.seed_from_sources:
        seed_from_sources(sb)
    drain(sb, limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
