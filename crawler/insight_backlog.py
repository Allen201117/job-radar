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
import copy
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import db
import insight_engine as E
import jobs_db
import llm_budget
import official_cninfo as CN
import official_edgar as EDG
import ops_runs
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
    # 分页拉全量：enabled sources 已越过 PostgREST 单次 1000 行硬顶（2026-07-20 实测 1079）→
    # 不分页时尾部公司永远排不进洞察队列。
    srcs = db.fetch_all_rows(
        lambda: sb.table("sources").select("company").eq("enabled", True))
    companies = sorted({(s.get("company") or "").strip() for s in srcs if (s.get("company") or "").strip()})
    existing = db.fetch_all_rows(
        lambda: sb.table("company_profiles").select("company"))
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
    rows = db.fetch_all_rows(
        lambda: (sb.table("company_profiles")
                 .select("id,company,aliases,insight_fail_count")
                 .lt("insight_fail_count", MAX_FAIL)
                 .or_(f"insight_checked_at.is.null,insight_checked_at.lt.{cutoff}")))
    return rows[:limit] if limit else rows


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


def _official_headcount_band(li):
    """官方财报员工数 → company_profiles.headcount_band；无财报员工数时不覆盖 Wikidata。"""
    try:
        employees = ((li.get("payload") or {}).get("financials") or {}).get("employees")
    except AttributeError:
        return None
    try:
        employees = int(employees)
    except (TypeError, ValueError):
        return None
    return wikidata.headcount_band(employees)


def _a_share_exchange(exchange):
    """交易所字段是否指向 A 股；仅此类需巨潮交叉验证。"""
    text = str(exchange or "")
    return any(name in text for name in ("上交所", "深交所", "北交所", "上海证券交易所", "深圳证券交易所", "北京证券交易所"))


def _listing_without_exchange(li, company):
    """交叉验证缺失/冲突时保留已上市事实，删除不能确认的交易所表述。"""
    cleaned = copy.deepcopy(li)
    payload = dict(cleaned.get("payload") or {})
    payload["exchange"] = None
    cleaned["payload"] = payload
    publisher = cleaned.get("source_publisher") or "公开资料"
    cleaned["content"] = f"据{publisher}公开资料，{company}为已上市公司。"
    return cleaned


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
        # 官方披露优先。A 股交易所不得直抄 Wikidata：只有巨潮开启且两边一致才写入交易所。
        wiki_li = wikidata.facts_to_listing(facts)
        li = EDG.get_listing_by_ticker(facts.get("ticker")) if facts.get("ticker") else None
        cninfo_li = CN.get_listing_by_name(profile["company"], profile.get("aliases")) if CN.enabled() else None
        if not li and cninfo_li:
            wiki_exchange = ((wiki_li or {}).get("payload") or {}).get("exchange")
            cninfo_exchange = ((cninfo_li.get("payload") or {}).get("exchange"))
            if wiki_li and wiki_exchange == cninfo_exchange:
                li = cninfo_li
            else:
                li = _listing_without_exchange(cninfo_li, profile["company"])
        if not li:
            li = wiki_li
            if li and _a_share_exchange(((li.get("payload") or {}).get("exchange"))):
                li = _listing_without_exchange(li, profile["company"])
        if li:
            write_listing(sb, profile["id"], li)
        prof = wikidata.facts_to_profile(facts)
        # EDGAR/后续官方财报里的员工数比 Wikidata 更接近披露口径；只在有官方 employees 时覆盖规模档。
        official_band = _official_headcount_band(li) if li else None
        if official_band:
            prof["headcount_band"] = official_band
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


def fetch_one_company(sb, company):
    """单公司现查：确保 company_profiles 占位存在，然后取富化所需字段。"""
    name = (company or "").strip()
    if not name:
        return None
    cols = "id,company,aliases,insight_fail_count,t3_fail_count"
    rows = (sb.table("company_profiles").select(cols).eq("company", name).limit(1).execute().data) or []
    if rows:
        return rows[0]
    sb.table("company_profiles").upsert({"company": name}, on_conflict="company").execute()
    rows = (sb.table("company_profiles").select(cols).eq("company", name).limit(1).execute().data) or []
    return rows[0] if rows else None


def drain_one_company(sb, company, t3=False):
    """单公司富化入口，供 workflow_dispatch 快车道复用。"""
    profile = fetch_one_company(sb, company)
    if not profile:
        return {"ok": 0, "noface": 0, "err": 1} if not t3 else {"wrote": 0, "empty": 0, "err": 1}
    if t3:
        res = enrich_company_t3(sb, profile)
        return {"wrote": 1 if res == "wrote" else 0,
                "empty": 1 if res == "empty" else 0,
                "err": 1 if res == "err" else 0}
    res = enrich_company(sb, profile)
    return {"ok": 1 if res == "ok" else 0,
            "noface": 1 if res == "noface" else 0,
            "err": 1 if res == "err" else 0}


def finish_insight_enrich_run(sb, company, status, diagnostics=None):
    """回写现查快车道最新 queued 台账；不碰其它公司的并发请求。"""
    if status not in ("success", "failed"):
        raise ValueError("insight enrich run status must be success or failed")
    rows = (
        sb.table("discovery_runs")
        .select("id,diagnostics")
        .eq("mode", "insight_enrich")
        .eq("company", (company or "").strip())
        .eq("status", "queued")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    ) or []
    if not rows:
        print("[insight-enrich] 未找到待回写的 queued 台账")
        return False
    previous = rows[0].get("diagnostics") or {}
    merged = {**previous, **(diagnostics or {})}
    update = {
        "status": status,
        "finished_at": _now(),
        "failure_reason": None if status == "success" else "workflow_failed",
        "error_message": None if status == "success" else str(merged.get("error") or "workflow failed")[:500],
        "diagnostics": merged,
    }
    sb.table("discovery_runs").update(update).eq("id", rows[0]["id"]).execute()
    return True


# ============================================================
# T3 经验层：多源搜索（博查/Tavily/Serper/千帆，search_router）→ 验证引擎（接地→判官→共识）→ 写 active/pending_review
# 各源受每日额度：drain_t3 串行 + search_usage/qianfan_usage 持久预算守门，绝不冲破各自日顶。
# 见 docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md。
# ============================================================
T3_TTL_DAYS = 180  # 经验类复核更慢
T3_HOST_DENYLIST = {
    "instagram.com", "facebook.com", "reddit.com", "x.com", "twitter.com", "tiktok.com",
    "zhipin.com", "zhaopin.com", "liepin.com", "51job.com", "lagou.com",
}


def resolve_t3_host_denylist(raw=None):
    """T3 来源域名黑名单；env INSIGHT_T3_HOST_DENYLIST 配置时完全覆盖默认值。"""
    if raw is None:
        raw = os.environ.get("INSIGHT_T3_HOST_DENYLIST")
    if raw in (None, ""):
        return set(T3_HOST_DENYLIST)
    return {E.registrable_host(host) for host in str(raw).split(",") if E.registrable_host(host)}


def filter_t3_results(results, denylist=None):
    """搜索结果在 writer / judge 之前按来源站点过滤，返回（保留结果，拦截数）。"""
    denylist = set(denylist) if denylist is not None else resolve_t3_host_denylist()
    kept = [result for result in (results or []) if E.registrable_host((result or {}).get("url")) not in denylist]
    return kept, len(results or []) - len(kept)


# 多维查询包目录：每条定向检索一个主题、路由到对应**已有**维度（不新增 dimension）。
# 成本：每个主题 ≈ 1 次 writer + ~2.7 次 judge ≈ 3.7 次 LLM 调用 → **主题数直接等比放大每家公司的账单**。
# 目录保留全部主题，默认集以外的主题可由 env 调回，见下面 T3_DEFAULT_TOPICS 注释。
T3_TOPIC_CATALOG = {
    "加班文化": {"topic": "加班文化", "query": "{c} 公司 加班 强度 到点下班 996 大小周 工作节奏", "dimension": "culture"},
    "实习体验": {"topic": "实习体验", "query": "{c} 公司 实习 实习生 体验 待遇 转正 怎么样", "dimension": "culture"},
    "年终奖": {"topic": "年终奖", "query": "{c} 公司 年终奖 发几个月 奖金 调薪 福利", "dimension": "compensation_intensity"},
    "晋升发展": {"topic": "晋升发展", "query": "{c} 公司 晋升 涨薪 职级 发展 机会 天花板", "dimension": "path"},
    "面试难度": {"topic": "面试难度", "query": "{c} 公司 面试 难度 流程 几轮 体验 通过", "dimension": "hiring"},
    "裁员稳定性": {"topic": "裁员稳定性", "query": "{c} 公司 裁员 缩编 业务调整 稳定 最近", "dimension": "hiring"},
}

# 默认跑 4 个主题（2026-09-03）：用户最在意薪资 / 面试 / 强度 / 稳定性四类信息差。
# 成本由 search_router 的「首源够用即停」抵消；晋升发展 / 实习体验仍保留在目录，按需由 env 调回。
# 【怎么调回来】不用改代码：设 env INSIGHT_T3_TOPICS（逗号分隔主题名，取值见 T3_TOPIC_CATALOG），
#   例：INSIGHT_T3_TOPICS='年终奖,加班文化,面试难度,裁员稳定性,晋升发展' 即加回晋升发展。
# 顺序 = 预算耗尽时的优先级（enrich_company_t3 逐条跑，额度用尽就 break）：先钱、再强度、再面试、再稳定。
T3_DEFAULT_TOPICS = ("年终奖", "加班文化", "面试难度", "裁员稳定性")


def resolve_query_pack(raw=None, catalog=None, default_topics=None):
    """纯函数：INSIGHT_T3_TOPICS 的原始字符串 → 查询包列表（顺序按 env 给的顺序）。

    容错走 fail-soft：目录里没有的主题名只告警并跳过，全部无效 / 未配置则回落默认主题——
    repo Variable 打错一个字不该让整轮 T3 变成空转。
    """
    catalog = catalog if catalog is not None else T3_TOPIC_CATALOG
    default_topics = default_topics if default_topics is not None else T3_DEFAULT_TOPICS
    names, seen = [], set()
    for chunk in str(raw or "").replace("，", ",").replace("、", ",").split(","):
        name = chunk.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if name in catalog:
            names.append(name)
        else:
            print(f"⚠ INSIGHT_T3_TOPICS 里的「{name}」不在主题目录中，已跳过（可选：{'/'.join(catalog)}）")
    if not names:
        names = [n for n in default_topics if n in catalog]
    return [dict(catalog[n]) for n in names]


T3_QUERY_PACK = resolve_query_pack(os.environ.get("INSIGHT_T3_TOPICS"))
_ROUTER = search_router.default_router()  # 多源搜索；未配 key 的源自动跳过（配哪个用哪个）


def _pick_sources(results, judge, max_n=3):
    """只取判官明确认定支持该 claim 的来源；绝不拿搜索结果凑展示门。"""
    chosen, seen = [], set()
    for idx in (judge or {}).get("supported_source_idxs") or []:
        if not isinstance(idx, int) or not (0 <= idx < len(results)):
            continue
        result = results[idx]
        publisher = E.registrable_host(result.get("url"))
        if not publisher or publisher in seen:
            continue
        chosen.append(result)
        seen.add(publisher)
        if len(chosen) >= max_n:
            break
    return chosen


def write_experience(sb, company_id, claim, sources, judge, status, dimension="culture", topic=None):
    """写一条 T3 经验条目（origin=public_web）+ 多来源（去标识、仅短 excerpt，禁整段 UGC）。
    dimension/topic 由查询包指定：路由到对应已有维度，title 带主题（如「年终奖 · 群体印象」）。"""
    item_id = str(uuid.uuid4())
    title = claim.get("title") or (f"{topic} · 群体印象" if topic else "公开讨论 · 群体印象")
    sb.table("insight_items").insert({
        "id": item_id, "company_id": company_id, "dimension": dimension,
        "grade": claim.get("grade") or "experience",
        "title": title,
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
    """T3 队列：所有已建画像的公司（= 我们在抓的源公司，需求对齐）+ t3 待处理/超期 + 未超死信。
    2026-06-28 放宽：原硬门 `founded_year 非空` 只放 64 家 notable，把 707 家「Wikidata 查无成立年份但
    我们确实在抓」的目标公司全挡在外 → T3 队列长期为空、洞察停更（最后 6/20）。改为 demand-driven：
    凡有画像即可入 T3 队列。安全/温和靠 drain_t3 的搜索额度封顶（~90/天）+ 判官 ≥2 源共识门自动 abstain
    低信号公司，不会爆预算。notable 优先（founded_year desc）先花额度在信号好的公司上。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=T3_TTL_DAYS)).isoformat()
    def query():
        return (sb.table("company_profiles").select("id,company,aliases,t3_fail_count")
                .lt("t3_fail_count", MAX_FAIL)
                .or_(f"t3_checked_at.is.null,t3_checked_at.lt.{cutoff}")
                .order("founded_year", desc=True, nullsfirst=False)
                .order("t3_checked_at", desc=False, nullsfirst=True))

    rows = db.fetch_all_rows(query)
    if not jobs_db.enabled():
        return rows[:limit] if limit else rows

    # 仅 jobs 库可用时才多取候选：按在招岗需求排序后再截断，避免 founded_year 把大户永远挤在队尾。
    if not rows:
        return []
    try:
        conn = jobs_db.get_conn()
        counts = jobs_db.fetch_all(
            conn,
            """
            select company, count(*) as active_count
            from jobs
            where status = 'active' and company = any(%s)
            group by 1
            """,
            ([str(row.get("company") or "") for row in rows],),
        )
        active_counts = {
            str(item.get("company") or ""): int(item.get("active_count") or 0)
            for item in counts
        }
        rows.sort(key=lambda row: -active_counts.get(str(row.get("company") or ""), 0))
    except Exception as exc:
        print(f"[t3] 香港 jobs 库岗位计数失败，回退 founded_year 排序: {type(exc).__name__}")
    return rows[:limit] if limit else rows


def enrich_company_t3(sb, profile):
    """单公司 T3：按多维查询包逐主题检索 → run_pipeline(对应维度) → 写。返回 'wrote' | 'empty' | 'err'。永不抛。
    额度由 router 在各 provider 内部按次记账；单查询失败不拖垮整包。
    替换旧代：本轮写完后退役本次之前的 public_web active（跨维度），不堆积老聚合（保即时性）。"""
    run_start = _now()
    wrote_any = False
    wrote_active = False
    # LLM 花费的 86% 在这条链上（2026-08-27 成本审计）。搜索侧本来就有日顶（下面 _ROUTER.remaining），
    # LLM 侧此前**完全没有天花板** → 花多少全看队列多长，账户欠费了都没人察觉。这里补上第二道闸。
    # 记账口径：gate 按主题查（与搜索额度同频），**扣减按 engine 的真实调用数**（不按估算值预扣），
    # 所以 cap 的单位就是「真实 LLM 调用次数」，与 llm_budget 语义一致。
    # 粒度取「每公司结算一次」：最坏超出一家公司的用量（~11 次），换掉逐次调用的跨洋往返。
    llm_calls_before = E.llm_usage_totals().get("calls", 0)
    for pack in T3_QUERY_PACK:
        if _ROUTER.remaining_above_reserve(sb) <= 0:
            break  # 搜索额度触到「校招预留线」→ 剩余主题留到下轮（见 search_router.campus_reserve）
        if llm_budget.remaining(sb) <= 0:
            print(f"  [t3] {profile['company']}: LLM 日顶已到，剩余主题留到下轮")
            break
        try:
            results = _ROUTER.search(sb, pack["query"].format(c=profile["company"]))
            results, host_denied = filter_t3_results(results)
            if host_denied:
                print(f"  [t3] host_denied={host_denied}")
            if not results:
                continue
            pipeline = E.run_pipeline(profile["company"], pack["dimension"], results)
            pubs = len({E.registrable_host(r.get("url")) for r in results if E.registrable_host(r.get("url"))})
            print(f"  [t3] {profile['company']}/{pack['topic']}: 多源 {len(results)} 条/{pubs} 域 → "
                  f"{[e['status'] for e in pipeline]}")
            for entry in pipeline:
                if entry["status"] == "drop":
                    continue
                claim = dict(entry["claim"])
                judge = entry.get("judge") or {}
                sources = _pick_sources(results, judge)
                source_publishers = len({E.registrable_host(s.get("url")) for s in sources
                                         if E.registrable_host(s.get("url"))})
                if not E.consensus_ok(claim.get("grade", "experience"), source_publishers):
                    continue
                write_experience(sb, profile["id"], claim, sources, judge, entry["status"],
                                 dimension=pack["dimension"], topic=pack["topic"])
                wrote_any = True
                wrote_active = wrote_active or entry["status"] == "active"
        except Exception as e:
            print(f"  [t3-err] {profile['company']}/{pack['topic']}: {type(e).__name__}: {str(e)[:120]}")
            continue
    # 本公司实际花掉多少次 LLM，如实记进日顶台账（失败只打日志，绝不阻断主任务）
    _spent = max(0, E.llm_usage_totals().get("calls", 0) - llm_calls_before)
    if _spent:
        llm_budget.check_and_consume(sb, kind="insight_t3", n=_spent)

    try:
        if wrote_active:
            # 退役本次之前的 public_web active（跨维度），换最新一代
            sb.table("insight_items").update({"status": "retired"}) \
                .eq("company_id", profile["id"]).eq("origin", "public_web").eq("status", "active") \
                .lt("last_verified_at", run_start).execute()
        sb.table("company_profiles").update({"t3_checked_at": _now()}).eq("id", profile["id"]).execute()
    except Exception:
        try:
            sb.table("company_profiles").update({
                "t3_fail_count": (profile.get("t3_fail_count") or 0) + 1, "t3_checked_at": _now(),
            }).eq("id", profile["id"]).execute()
        except Exception:
            pass
        return "err"
    return "wrote" if wrote_any else "empty"


def drain_t3(sb, limit=0):
    """T3 drain（多源搜索，各源受每日额度 → 串行 + 预算守门，绝不冲破各自日顶）。"""
    # 先探 LLM，再碰任何搜索额度。余额不足时继续搜索只会空烧有限日配额。
    try:
        E.chat_content([{"role": "user", "content": "health check"}], max_tokens=1)
    except Exception as exc:
        if E.llm_run_health()["account_error"]:
            raise RuntimeError(
                "T3 LLM 预探活失败（账户余额不足或鉴权失效）；已在搜索前中止，未调用搜索 API"
            ) from exc
        print(f"⚠ T3 LLM 预探活未通过（非账户级）：{type(exc).__name__}；继续按原流程执行")
    finally:
        E.forget_llm_probe()
    if not _ROUTER.is_configured():
        print("✗ 无搜索源配置（BOCHA/TAVILY/SERPER/千帆 key 全缺或熔断）→ 跳过 T3")
        return {"wrote": 0, "empty": 0, "err": 0, "budget_left": 0}
    # ⚠️ 用 remaining_above_reserve 而不是 remaining：搜索额度是全局共享的，
    # 这条链以前一路吃到 0，把排在它后面 45 分钟的校招时间线链**饿死了整整一周**
    # （ops_runs 连续 7 天 companies_processed=0，却因为不抛异常一直报 success）。
    remaining = _ROUTER.remaining_above_reserve(sb)
    print(f"搜索源当日可用额度（已扣校招预留 {search_router.campus_reserve()}）：{remaining}")
    if remaining <= 0:
        return {"wrote": 0, "empty": 0, "err": 0, "budget_left": 0}
    cap = remaining if not limit else min(remaining, limit)
    rows = fetch_t3_queue(sb, cap)
    print(f"T3 队列（notable·待富化）取 {len(rows)} 家（额度封顶 {cap}）")
    stat = {"wrote": 0, "empty": 0, "err": 0}
    for p in rows:
        if _ROUTER.remaining_above_reserve(sb) <= 0:
            print("额度触到校招预留线，停"); break
        stat[enrich_company_t3(sb, p)] += 1
    stat["budget_left"] = _ROUTER.remaining_above_reserve(sb)
    print(f"T3 完成：{stat}")
    return stat


def _llm_health_gate():
    """LLM 整体失败（账户欠费 / 鉴权失效）→ exit(1) 标红。别让 workflow 绿灯盖住 LLM 故障。
    0 次 LLM 调用（T2 官方事实路径本就不怎么用 LLM）不触发，不会误报。"""
    if E.llm_run_unhealthy():
        h = E.llm_run_health()
        print(f"✗ LLM 整体失败（ok={h['ok']} fail={h['fail']} account_error={h['account_error']}）"
              f"——大概率 SiliconFlow 账户欠费 / key 失效，本轮没产出。")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="职业洞察富化 drain（T2 Wikidata 默认 / --t3 经验层）")
    ap.add_argument("--seed-from-sources", action="store_true", help="先给所有源公司建画像占位")
    ap.add_argument("--t3", action="store_true", help="跑 T3 经验层（千帆检索，受 50/日额度）而非 T2")
    ap.add_argument("--company", default="", help="只富化单家公司（现查快车道用）")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理多少公司（0=全部/额度上限）")
    ap.add_argument("--workers", type=int, default=4, help="T2 并发线程数（对 Wikidata 礼貌，建议 ≤6）")
    ap.add_argument("--finish-run", action="store_true", help="回写单公司现查台账终态（workflow 收尾用）")
    ap.add_argument("--finish-status", choices=("success", "failed"), default="success")
    ap.add_argument("--finish-diagnostics", default="", help="收尾写入 diagnostics.workflow")
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    if args.finish_run:
        if not args.company:
            print("✗ --finish-run 需要 --company")
            sys.exit(1)
        diagnostics = {"workflow": args.finish_diagnostics or "insight enrich finished"}
        if args.finish_status == "failed":
            diagnostics["error"] = args.finish_diagnostics or "workflow failed"
        if not finish_insight_enrich_run(sb, args.company, args.finish_status, diagnostics):
            sys.exit(1)
        return
    started_at = _now()
    E.reset_llm_health()
    if args.t3:
        stat = drain_one_company(sb, args.company, t3=True) if args.company else drain_t3(sb, limit=args.limit)
        checked = stat["wrote"] + stat["empty"] + stat["err"]
        ops_runs.record_ops_run(
            sb,
            "insight_backlog",
            {
                "checked": checked,
                "companies_enriched": stat["wrote"],
                "failed": stat["err"],
                "mode": "experience",
            },
            status=ops_runs.status_from_counts(checked, stat["err"]),
            started_at=started_at,
            finished_at=_now(),
        )
        # 本轮真实 token 用量落台账（2026-08-27 前代码里从不记 usage，只能按字符数瞎估花费，
        # 账户 8-25 欠费了都没人察觉）。写失败只打日志，不阻断。
        E.record_usage_ops_run(sb)
        _llm_health_gate()
        return
    seeded = 0
    if args.seed_from_sources and not args.company:
        seeded = seed_from_sources(sb)
    stat = drain_one_company(sb, args.company, t3=False) if args.company else drain(sb, limit=args.limit, workers=args.workers)
    checked = stat["ok"] + stat["noface"] + stat["err"]
    ops_runs.record_ops_run(
        sb,
        "insight_backlog",
        {
            "checked": checked,
            "companies_enriched": stat["ok"],
            "failed": stat["err"],
            "seeded": seeded,
            "mode": "official_facts",
        },
        status=ops_runs.status_from_counts(checked, stat["err"]),
        started_at=started_at,
        finished_at=_now(),
    )
    E.record_usage_ops_run(sb)   # 同上：真实 token 用量落台账
    _llm_health_gate()


if __name__ == "__main__":
    main()
