"""必投清单缺口台账：一次聚合 jobs，再在 Python 内按清单 pattern 归属公司。"""
import os
from math import ceil
from datetime import datetime, timedelta, timezone

import db
import jobs_db
import must_apply


DEFAULT_TARGET_INDUSTRIES = (
    "金融", "教育", "能源/化工", "地产/建筑", "物流/供应链", "传媒/文娱"
)

# 复验车道只回捞「我们改代码就可能变好」的失败态。
# 刻意不含 governance_candidate / login_wall / anti_bot / manual_review / healthy：
# 前四个是人工或对方的问题（改 adapter 不会让登录墙消失），healthy 没什么可复验的。
_REVALIDATE_STATES = frozenset({
    "no_stable_jd", "wrong_platform", "no_active_jobs", "thin_only",
})
_DEFAULT_REVALIDATE_SLOTS = 3
# 上次尝试至少隔这么久才回捞。没有这道门，短退避（失败后 1 天重试那种）会被复验车道
# 当场抵消 = 退避形同虚设，且每天重复敲同一批站点。7 天足够覆盖「改了 adapter」的节奏。
_REVALIDATE_MIN_AGE_DAYS = 7


def _revalidate_slots(value=None):
    """每轮最多回捞几家。env `GAP_FUNNEL_REVALIDATE_SLOTS`，设 0 = 关掉这条车道。"""
    if value is not None:
        return max(0, int(value))
    raw = str(os.environ.get("GAP_FUNNEL_REVALIDATE_SLOTS", "")).strip()
    if not raw:
        return _DEFAULT_REVALIDATE_SLOTS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_REVALIDATE_SLOTS

# ⚠️ 计数**只算本 scope 的岗**（`job_scope = %(scope)s`）。
# 2026-09-05 之前不分 scope：国内清单会把大陆集团的 352 个海外岗算成中国供给、
# 海外清单会把优衣库的 1,918 个中国岗算成海外供给。指标诚实优先于覆盖率好看。
# `other_scope_healthy` 是**另一个** scope 的健康岗数，只写进台账 evidence 供人判断
# 「这家公司不是没岗，是岗不在这个范围」——它不参与状态判定。
_JOB_AGGREGATE_SQL = """
select
  company,
  count(*) filter (where job_scope = %(scope)s) as active_total,
  count(*) filter (
    where job_scope = %(scope)s
      and summary is not null and char_length(btrim(summary)) >= 60
  ) as healthy,
  count(*) filter (
    where job_scope <> %(scope)s
      and summary is not null and char_length(btrim(summary)) >= 60
  ) as other_scope_healthy
  {brand_columns}
from jobs
where status = 'active'
group by company
"""


def _matches(value, patterns):
    """库里这行公司名是不是这家清单公司；`patterns` = pattern + 别名（见 must_apply.company_patterns）。"""
    if isinstance(patterns, str):
        patterns = [patterns]
    return must_apply.match_company_against_patterns(value, patterns)


def _as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _base_company(company):
    return {
        "company": str(company.get("name") or "").strip(),
        "pattern": str(company.get("pattern") or "").strip(),
        "industries": sorted({
            str(x).strip() for x in (company.get("industries") or []) if str(x).strip()
        }),
    }


def classify_company(company, healthy_jobs, sources_rows, prev_row=None):
    """纯函数：给单个清单槽位计算当前台账状态，不执行任何 IO。"""
    base = _base_company(company)
    pattern = base["pattern"]
    # 别名一并参与匹配：库里可能用英文名记着这家公司（壳牌=Shell / 大陆集团=Continental），
    # 只按中文 pattern 匹配就会「有源有岗却判零源」，进而驱动人去重复插源（迁移 225 的同岗两行即此）。
    patterns = must_apply.company_patterns({
        "pattern": pattern, "aliases": company.get("aliases"),
    })
    matched_jobs = [
        row for row in (healthy_jobs or [])
        if _matches((row or {}).get("company"), patterns)
    ]
    direct_active = sum(_as_int(row.get("active_total")) for row in matched_jobs)
    direct_healthy = sum(_as_int(row.get("healthy")) for row in matched_jobs)
    # 「有源有岗」不等于「有中国岗」：普查的岗位聚合**不按 job_scope 过滤**（历史如此，
    # 改它会一次性动 329+327 家的口径，另案）。所以至少把 scope 拆分如实记进台账——
    # 大陆集团 425 个健康岗里只有 73 个标着 domestic，看台账的人有权知道这件事，
    # 而不是看到「healthy 425」就以为中国岗很多。
    # 「这个范围里没岗」不等于「这家公司没岗」：大陆集团国内 73 个、海外还有 352 个。
    # 记下另一个范围的数，看台账的人才分得清「真没供给」和「供给不在这个范围」。
    has_other_scope = any("other_scope_healthy" in (row or {}) for row in matched_jobs)
    other_scope_healthy = sum(_as_int(row.get("other_scope_healthy")) for row in matched_jobs)
    parent_rollup = {"active_total": 0, "healthy": 0}
    if company.get("parentPattern") and company.get("brandTokens"):
        for row in healthy_jobs or []:
            rollup = (row.get("brand_rollups") or {}).get(pattern) or {}
            parent_rollup["active_total"] += _as_int(rollup.get("active_total"))
            parent_rollup["healthy"] += _as_int(rollup.get("healthy"))
    accepted_parent = (
        parent_rollup
        if parent_rollup["healthy"] >= 3
        else {"active_total": 0, "healthy": 0}
    )
    active_total = direct_active + accepted_parent["active_total"]
    healthy_total = direct_healthy + accepted_parent["healthy"]
    matched_sources = [
        row for row in (sources_rows or [])
        if _matches((row or {}).get("company"), patterns)
    ]
    enabled_sources = [row for row in matched_sources if row.get("enabled")]
    prev = dict(prev_row or {})

    if healthy_total > 0:
        state = "healthy"
    elif active_total > 0:
        state = "thin_only"
    elif enabled_sources:
        state = "no_active_jobs"
    elif prev.get("state") not in (None, "", "healthy", "thin_only", "no_active_jobs"):
        # 搜索/指纹失败态是历史尝试结果；census 只在新证据推翻它时改写。
        state = prev["state"]
    else:
        state = "unknown"

    evidence = dict(prev.get("evidence") or {})
    evidence.update({
        "list_version": must_apply.version(),
        "active_jobs": active_total,
        "healthy_jobs": healthy_total,
        "direct_healthy_jobs": direct_healthy,
        "other_scope_healthy_jobs": other_scope_healthy if has_other_scope else None,
        "parent_portal_healthy_jobs": accepted_parent["healthy"],
        "covered_via_parent_portal": accepted_parent["healthy"] > 0,
        "matched_job_companies": sorted({
            str(row.get("company")) for row in matched_jobs if row.get("company")
        }),
        "matched_source_ids": [
            str(row.get("id")) for row in matched_sources if row.get("id")
        ],
        # 靠别名（而非清单名本身）命中的模式：台账要能自己解释「为什么这家不再是零源」，
        # 否则下一个人看到「大陆集团 healthy」还是会去 sources 里搜中文名、搜不到又插一条。
        "matched_alias_patterns": [
            alias for alias in patterns[1:]
            if any(
                _matches((row or {}).get("company"), [alias])
                for row in matched_jobs + matched_sources
            )
        ],
    })
    source_id = None
    if enabled_sources:
        source_id = enabled_sources[0].get("id")
    elif state not in ("unknown",) and prev.get("source_id"):
        source_id = prev.get("source_id")

    out = {
        **base,
        "state": state,
        "source_id": source_id,
        "official_entry_url": prev.get("official_entry_url"),
        "detected_platform": prev.get("detected_platform"),
        "fail_reason": prev.get("fail_reason"),
        "evidence": evidence,
        "attempts": _as_int(prev.get("attempts")),
        "rounds_no_entry": _as_int(prev.get("rounds_no_entry")),
        "last_attempt_at": prev.get("last_attempt_at"),
        "next_retry_at": prev.get("next_retry_at"),
    }
    if state == "healthy":
        out["fail_reason"] = None
        out["next_retry_at"] = None
    return out


def _parse_datetime(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _wanted(company, user_wanted):
    low = str(company or "").strip().lower()
    for wanted in user_wanted or set():
        token = str(wanted or "").strip().lower()
        if token and (token in low or low in token):
            return True
    return False


def _coverage_for(row, industry_coverage):
    values = [
        float(industry_coverage.get(industry, 1.0))
        for industry in (row.get("industries") or [])
    ]
    return min(values) if values else 1.0


def plan_queue(rows, target_industries, user_wanted, industry_coverage, *,
               now=None, cap=20, ignore_backoff=False, revalidate_slots=None):
    """纯函数：过滤到期项，优先首跑并避免单行业长期占满队列。

    ignore_backoff=True 用于**人工点名单家公司**（CLI/workflow 的 --company）：
    点名却因退避不跑，会让人以为系统坏了，更要命的是会锁死自我修复——
    公司因某个 bug 失败 → 退避 45 天 → 修好 bug 想验证却跑不动 → 只能干等。
    定时任务默认 False，退避照常生效。

    revalidate_slots = 复验车道：用**剩余配额**回捞等得最久的退避项，治的正是上面那句
    「只能干等」在定时跑里的版本——ignore_backoff 只救得了「有人想起来点名」的公司。
    2026-09-05 实证：埃斯顿 8-28 判 no_stable_jd 退避到 9-30，而 8-27 落地的 beisen 改动
    当天就能从同一个 URL 抓到 63 个健康岗；期间 8 次定时跑一次都没复测它，63 个岗白白
    锁了 8 天。**adapter 是持续在改的，退避却假设「失败原因不会变」，这个假设是错的。**
    ⚠️ 只回捞「能力相关」的失败态（我们改代码就可能变好的）；治理/登录墙/反爬是人工或
    对方的问题，改 adapter 不会让它们变好，回捞它们只是每天空烧。
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    targets = {str(x).strip() for x in (target_industries or set()) if str(x).strip()}
    eligible = []
    backed_off = []
    for row in rows or []:
        state = row.get("state") or "unknown"
        retry_at = _parse_datetime(row.get("next_retry_at"))
        if (
            ignore_backoff
            or (state == "unknown" and retry_at is None)
            or (retry_at is not None and retry_at <= now)
        ):
            eligible.append(row)
        elif retry_at is not None and state in _REVALIDATE_STATES:
            backed_off.append(row)

    def key(row):
        industries = set(row.get("industries") or [])
        return (
            0 if _as_int(row.get("attempts")) == 0 else 1,
            0 if industries & targets else 1,
            0 if _wanted(row.get("company"), user_wanted) else 1,
            _coverage_for(row, industry_coverage),
            str(row.get("company") or "").casefold(),
        )

    limit = max(0, int(cap or 0))
    if not limit:
        return []
    per_industry_limit = max(3, int(ceil(limit * 0.4)))
    selected = []
    deferred = []
    industry_counts = {}
    for row in sorted(eligible, key=key):
        industries = row.get("industries") or []
        industry = str(industries[0]).strip() if industries else ""
        if industry_counts.get(industry, 0) < per_industry_limit:
            selected.append(row)
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
        else:
            deferred.append(row)
        if len(selected) >= limit:
            return selected
    queue = (selected + deferred)[:limit]
    return queue + _revalidation_picks(
        backed_off, queue, limit=limit, slots=revalidate_slots, now=now
    )


def _revalidation_picks(backed_off, queue, *, limit, slots, now):
    """用剩余配额回捞等得最久的退避项。到期项永远优先——这里只吃它们剩下的。"""
    slots = _revalidate_slots(slots)
    room = min(slots, limit - len(queue))
    if room <= 0 or not backed_off:
        return []
    already = {id(row) for row in queue}
    cutoff = now - timedelta(days=_REVALIDATE_MIN_AGE_DAYS)
    pool = []
    for row in backed_off:
        if id(row) in already:
            continue
        last = _parse_datetime(row.get("last_attempt_at"))
        # ⚠️ last_attempt_at 缺失**不算**「等了很久」：那是「排了期但还没跑过」，
        # 退避该照常生效。当成 1970 会让每一条这样的行天天被回捞。
        if last is None or last > cutoff:
            continue
        pool.append((last, str(row.get("company") or "").casefold(), row))
    pool.sort(key=lambda item: item[:2])          # 等得最久的先回捞
    return [row for _last, _name, row in pool[:room]]


def load_companies(scope="domestic"):
    grouped = must_apply.by_industry() if scope == "domestic" else must_apply.overseas_by_industry()
    merged = {}
    for industry, entries in grouped.items():
        for entry in entries or []:
            name = str(entry.get("name") or "").strip()
            pattern = str(entry.get("pattern") or "").strip()
            if not name or not pattern:
                continue
            row = merged.setdefault(name, {
                "name": name,
                "pattern": pattern,
                "industries": [],
            })
            if entry.get("aliases"):
                row["aliases"] = [
                    str(alias).strip()
                    for alias in entry["aliases"]
                    if str(alias).strip()
                ]
            if entry.get("parentPattern"):
                row["parentPattern"] = str(entry["parentPattern"]).strip()
            if entry.get("brandTokens"):
                row["brandTokens"] = [
                    str(token).strip()
                    for token in entry["brandTokens"]
                    if str(token).strip()
                ]
            if industry not in row["industries"]:
                row["industries"].append(industry)
    return list(merged.values())


def _brand_rules(companies):
    rules = []
    seen = set()
    for company in companies or []:
        pattern = str(company.get("pattern") or "").strip()
        parent = str(company.get("parentPattern") or "").strip()
        tokens = [
            str(token).strip()
            for token in (company.get("brandTokens") or [])
            if str(token).strip()
        ]
        if pattern and parent and tokens and pattern not in seen:
            seen.add(pattern)
            rules.append({
                "pattern": pattern,
                "parentPattern": parent,
                "brandTokens": tokens,
            })
    return rules


def _job_aggregate_query(companies, scope="domestic"):
    columns = []
    params = {"scope": scope}
    rules = _brand_rules(companies)
    for index, rule in enumerate(rules):
        prefix = "brand_%d" % index
        params.update({
            prefix + "_parent": rule["parentPattern"],
            prefix + "_direct": rule["pattern"],
            prefix + "_tokens": [
                "%%%s%%" % token for token in rule["brandTokens"]
            ],
        })
        matches = (
            "company ilike %({prefix}_parent)s "
            "and company not ilike %({prefix}_direct)s "
            "and job_scope = %(scope)s "
            "and title ilike any(%({prefix}_tokens)s::text[])"
        ).format(prefix=prefix)
        columns.append(
            """,
  count(*) filter (where {matches}) as brand_{index}_active,
  count(*) filter (
    where summary is not null
      and char_length(btrim(summary)) >= 60
      and {matches}
  ) as brand_{index}_healthy""".format(matches=matches, index=index)
        )
    return (
        _JOB_AGGREGATE_SQL.format(brand_columns="".join(columns)),
        params,
        rules,
    )


def fetch_job_aggregates(conn, companies, scope="domestic"):
    sql, params, rules = _job_aggregate_query(companies, scope)
    rows = jobs_db.fetch_all(conn, sql, params)
    for row in rows:
        row["brand_rollups"] = {
            rule["pattern"]: {
                "active_total": _as_int(row.get("brand_%d_active" % index)),
                "healthy": _as_int(row.get("brand_%d_healthy" % index)),
            }
            for index, rule in enumerate(rules)
        }
    return rows


def fetch_sources(supabase):
    return db.fetch_all_rows(
        lambda: supabase.table("sources").select("id,company,source_url,adapter_name,enabled")
    )


def fetch_previous_rows(supabase, scope):
    return db.fetch_all_rows(
        lambda: supabase.table("must_apply_gap_attempts").select("*").eq("scope", scope)
    )


def fetch_user_wanted(supabase):
    try:
        rows = db.fetch_all_rows(
            lambda: supabase.table("user_preferences").select("user_id,target_companies"),
            order_key="user_id",
        )
    except Exception:
        return set()
    return {
        str(company).strip()
        for row in rows
        for company in (row.get("target_companies") or [])
        if str(company).strip()
    }


def compute_industry_coverage(rows, companies):
    totals = {}
    healthy = {}
    by_name = {row["company"]: row for row in rows}
    for company in companies:
        is_healthy = by_name.get(company["name"], {}).get("state") == "healthy"
        for industry in company.get("industries") or []:
            totals[industry] = totals.get(industry, 0) + 1
            healthy[industry] = healthy.get(industry, 0) + int(is_healthy)
    return {
        industry: healthy.get(industry, 0) / total
        for industry, total in totals.items() if total
    }


def target_industries_from_env():
    raw = os.environ.get("GAP_FUNNEL_INDUSTRIES")
    values = raw.split(",") if raw is not None else DEFAULT_TARGET_INDUSTRIES
    return {str(x).strip() for x in values if str(x).strip()}


def schedule_initial_retry(row, now):
    """让首次 census 发现的旧薄源/空源进入本轮，而非因 NULL retry 永久悬空。"""
    out = dict(row)
    if (
        out.get("state") in ("thin_only", "no_active_jobs")
        and not out.get("next_retry_at")
    ):
        out["next_retry_at"] = now.astimezone(timezone.utc).isoformat()
    return out


def _upsert_attempts(supabase, scope, rows, now):
    payload = [
        {**row, "scope": scope, "updated_at": now.isoformat()}
        for row in rows
    ]
    if payload:
        supabase.table("must_apply_gap_attempts").upsert(
            payload, on_conflict="scope,company"
        ).execute()


def census(supabase, jobs_conn, *, scope="domestic", cap=20, company=None,
           apply=False, now=None):
    """执行一次 census；apply=False 时只返回拟变更，不写台账。"""
    if scope not in ("domestic", "overseas"):
        raise ValueError("scope must be domestic or overseas")
    now = now or datetime.now(timezone.utc)
    companies = load_companies(scope)
    if company:
        companies = [row for row in companies if row["name"] == company]
    aggregates = fetch_job_aggregates(jobs_conn, companies, scope)
    sources = fetch_sources(supabase)
    previous = {row.get("company"): row for row in fetch_previous_rows(supabase, scope)}
    rows = []
    for item in companies:
        prev = previous.get(item["name"])
        row = classify_company(item, aggregates, sources, prev)
        rows.append(schedule_initial_retry(row, now))
    coverage = compute_industry_coverage(rows, companies)
    wanted = fetch_user_wanted(supabase)
    queue = plan_queue(
        rows,
        target_industries_from_env(),
        wanted,
        coverage,
        ignore_backoff=bool(company),
        now=now,
        cap=cap,
    )
    # 台账是我们自己的簿记（不是 sources/jobs），dry-run 也要落盘：
    # 它记的是「每家公司当前处于什么状态」，不落盘就等于每轮从零开始。
    _upsert_attempts(supabase, scope, rows, now)
    return {
        "rows": rows,
        "queue": queue,
        "industry_coverage": coverage,
        "user_wanted": wanted,
    }
