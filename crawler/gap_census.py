"""必投清单缺口台账：一次聚合 jobs，再在 Python 内按清单 pattern 归属公司。"""
import os
from datetime import datetime, timezone

import db
import jobs_db
import must_apply


DEFAULT_TARGET_INDUSTRIES = (
    "金融", "教育", "能源/化工", "地产/建筑", "物流/供应链", "传媒/文娱"
)

_JOB_AGGREGATE_SQL = """
select
  company,
  count(*) as active_total,
  count(*) filter (
    where summary is not null and char_length(btrim(summary)) >= 60
  ) as healthy
  {brand_columns}
from jobs
where status = 'active'
group by company
"""


def _matches(value, pattern):
    return must_apply.match_company_against_patterns(value, [pattern])


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
    matched_jobs = [
        row for row in (healthy_jobs or [])
        if _matches((row or {}).get("company"), pattern)
    ]
    direct_active = sum(_as_int(row.get("active_total")) for row in matched_jobs)
    direct_healthy = sum(_as_int(row.get("healthy")) for row in matched_jobs)
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
        if _matches((row or {}).get("company"), pattern)
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
        "parent_portal_healthy_jobs": accepted_parent["healthy"],
        "covered_via_parent_portal": accepted_parent["healthy"] > 0,
        "matched_job_companies": sorted({
            str(row.get("company")) for row in matched_jobs if row.get("company")
        }),
        "matched_source_ids": [
            str(row.get("id")) for row in matched_sources if row.get("id")
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
               now=None, cap=20):
    """纯函数：过滤到期项，按行业/用户/覆盖率/公司名稳定排序后裁剪配额。"""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    targets = {str(x).strip() for x in (target_industries or set()) if str(x).strip()}
    eligible = []
    for row in rows or []:
        state = row.get("state") or "unknown"
        retry_at = _parse_datetime(row.get("next_retry_at"))
        if state == "unknown" or (retry_at is not None and retry_at <= now):
            eligible.append(row)

    def key(row):
        industries = set(row.get("industries") or [])
        return (
            0 if industries & targets else 1,
            0 if _wanted(row.get("company"), user_wanted) else 1,
            _coverage_for(row, industry_coverage),
            str(row.get("company") or "").casefold(),
        )

    return sorted(eligible, key=key)[:max(0, int(cap or 0))]


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


def _job_aggregate_query(companies):
    columns = []
    params = {}
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


def fetch_job_aggregates(conn, companies):
    sql, params, rules = _job_aggregate_query(companies)
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
    aggregates = fetch_job_aggregates(jobs_conn, companies)
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
