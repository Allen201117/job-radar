#!/usr/bin/env python3
"""P0-3 业务线级信号派生：把自有岗位库算成结构化、可索引、可筛选的 signal 条目。

产出写进 ``insight_items``（origin='derived' / assertion='signal'），每个主体每个指标一行，
天天重算即覆盖。这是「洞察库」页面能按指标筛选、排序、跨公司比较的前提——
散文没法索引，只有 (subject_id, metric_key, metric_value) 可以。

诚实边界（spec §1.5，违反即返工）：
  · 岗位库只能答「在招结构 / 稳定性 / 门槛 / 在架时长」。强度、晋升、面试**不在这里**，
    薪资只有 1.8% 的岗位明写，因此 salary_range_k 是小覆盖字段，不是公司薪酬水平。
  · 每条统计必须带样本量 n，并在正文里写出来；样本不足**整条省略**，不写 0、不写「暂无」。
  · 只给数字与口径，不下「该公司在扩张 / 值得去」这类结论——结论留给用户。

⚠️ 趋势为什么不在这里由 first_seen_at 直接算：expired 岗每日被 purge 永久删除，
   「30-60 天前」的窗口只剩活到今天的那部分，与「近 30 天」口径不同，相除会系统性偏高。
   趋势只由 insight_subject_daily 的跨日快照得出（见迁移 206）。
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

import bu_extract
import db
import job_function
import jobs_db
import normalizer
import ops_runs

# ── 样本量硬门（镜像 lib/insight-derive.ts 的 SIGNAL_MIN_*，改一处必同改）────────
MIN_COMPANY = 10          # 公司级主体至少这么多在招岗才产出任何指标
MIN_BU = 20               # 业务线级主体门槛更高（spec §1.5）
MIN_DIST = 10             # 分布类（城市/职能/类型/学历）至少这么多个有值样本
MIN_SALARY = 10           # 薪资中位数：明写薪资的岗位至少这么多个
MIN_TREND = 10            # 趋势两期各自的最小样本

# 岗位表里要用到的列。刻意不取 summary：390k 行 × 400 字 ≈ 150MB，而派生层一个字都用不到。
JOB_COLUMNS = (
    "title", "location", "experience", "education", "salary_text",
    "first_seen_at", "recruitment_category",
)

_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)")
_FRESH_RE = re.compile(r"应届|不限|无经验")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 纯函数区（可离线单测，不碰网络与 DB）──────────────────────────────────
def parse_min_years(text) -> float | None:
    """把 jobs.experience（'3-5年' / '5年+' / '应届/不限'）解析成年限下界。

    只认 normalizer.extract_experience 产出的那几种形态；解析不出返回 None（弃权，不猜 0）。
    """
    value = str(text or "").strip()
    if not value:
        return None
    if _FRESH_RE.search(value):
        return 0.0
    m = _YEARS_RE.search(value)
    return float(m.group(1)) if m else None


def parse_salary_mid_k(text) -> float | None:
    """把薪资文本解析成「月薪 K」中点。口径镜像 lib/insight-derive.ts parseSalaryText：
    只认明示区间；「万」有年/月歧义 → 一律弃权，宁可少一条也不进垃圾数据。"""
    raw = str(text or "")
    if not raw:
        return None
    s = re.sub(r"\s+", "", raw).lower()
    m = re.search(r"(\d+(?:\.\d+)?)(?:k|千)?[-~至到](\d+(?:\.\d+)?)(?:k|千)", s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return round((lo + hi) / 2, 1) if 0 < lo <= hi < 1000 else None
    m = re.search(r"(\d{4,6})[-~至到](\d{4,6})", s)
    if m:
        lo, hi = int(m.group(1)) / 1000, int(m.group(2)) / 1000
        return round((lo + hi) / 2, 1) if 0 < lo <= hi < 1000 else None
    return None


def distribution(values) -> list[dict]:
    """[(key, count, share%)]，按数量降序；share 保留一位小数。"""
    items = [str(v).strip() for v in values if str(v or "").strip()]
    total = len(items)
    if not total:
        return []
    return [
        {"key": key, "count": count, "share": round(count * 100 / total, 1)}
        for key, count in Counter(items).most_common()
    ]


def days_between(iso_value, now: datetime) -> float | None:
    if not iso_value:
        return None
    if isinstance(iso_value, datetime):
        moment = iso_value
    else:
        try:
            moment = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now - moment).total_seconds() / 86400.0


def _pct(value: float) -> str:
    """+12.5% / -8.0%：环比一律带符号，避免读成绝对值。"""
    return f"{value:+.1f}%"


def compute_metrics(jobs: list[dict], *, kind: str, subject_name: str,
                    now: datetime, bu_count: int | None = None,
                    functions: list | None = None) -> list[dict]:
    """一个主体的全部指标行（纯函数）。样本不足的指标直接不出现在返回值里。

    ``functions`` 与 ``jobs`` 等长；为 None 表示职能分类本轮弃权 → 不产出 function_share。
    """
    n = len(jobs)
    floor = MIN_BU if kind == "business_unit" else MIN_COMPANY
    if n < floor:
        return []

    day = now.date().isoformat()
    window = f"截至 {day} 的在招岗位"
    out: list[dict] = []

    def add(metric_key, value, unit, content, *, sample, dimension="hiring",
            scope=None, payload=None, title=None):
        out.append({
            "metric_key": metric_key,
            "metric_value": None if value is None else round(float(value), 2),
            "metric_unit": unit,
            "dimension": dimension,
            "title": title or subject_name,
            "content": content,
            "sample_size": int(sample),
            "scope": scope or {},
            "payload": {"sample_n": int(sample), "as_of": day, **(payload or {})},
            "time_window": window,
        })

    # 规模：业务线给自身岗位数，公司给识别出的业务线条数。
    if kind == "business_unit":
        add("bu_job_count", n, "个", f"{subject_name} 当前在招 {n} 个岗位。", sample=n)
    elif bu_count:
        add("bu_count", bu_count, "个",
            f"从在招岗位标题识别出 {bu_count} 条业务线（基于 {n} 个在招岗）。", sample=n)

    # 近 30 天新挂出且仍在招。这是观测量不是无偏新增量，正文写清口径。
    new_30 = sum(1 for jb in jobs
                 if (d := days_between(jb.get("first_seen_at"), now)) is not None and d <= 30)
    add("hiring_volume_30d", new_30, "个",
        f"近 30 天新挂出并仍在招的岗位 {new_30} 个（口径：按岗位首次被我们收录的时间计，"
        f"基于 {n} 个在招岗）。", sample=n)

    # 在架时长中位数：久招不到 = 缺人，这是「好不好进」的第一方代理指标。
    ages = [d for jb in jobs
            if (d := days_between(jb.get("first_seen_at"), now)) is not None]
    if len(ages) >= MIN_DIST:
        med = statistics.median(ages)
        add("open_age_days_median", med, "天",
            f"在招岗位已挂出时长的中位数为 {med:.0f} 天（基于 {len(ages)} 个在招岗）。",
            sample=len(ages))

    # 城市分布
    cities = [normalizer.normalize_city(str(jb.get("location") or "")) for jb in jobs]
    city_dist = distribution(cities)
    city_n = sum(item["count"] for item in city_dist)
    if city_dist and city_n >= MIN_DIST:
        top = city_dist[0]
        head = "、".join(f"{i['key']} {i['share']}%" for i in city_dist[:3])
        add("city_share", top["share"], "%",
            f"在招岗位的城市分布：{head}（基于 {city_n} 个写明地点的岗）。",
            sample=city_n, scope={"city": top["key"]},
            payload={"distribution": city_dist[:8]})

    # 职能分布（权威词表在 JS，隔进程调；分类弃权时整条不产出）
    if functions is not None:
        fn_dist = distribution(functions)
        fn_n = sum(item["count"] for item in fn_dist)
        if fn_dist and fn_n >= MIN_DIST:
            top = fn_dist[0]
            head = "、".join(f"{i['key']} {i['share']}%" for i in fn_dist[:3])
            add("function_share", top["share"], "%",
                f"在招岗位的职能分布：{head}（基于 {fn_n} 个岗）。",
                sample=fn_n, scope={"function": top["key"]},
                payload={"distribution": fn_dist[:8]})

    # 招聘类型分布：直接读物化列，不重判（判据的所有权在数据库，见 jobs-db/schema.sql）
    buckets = [jb.get("recruitment_category") for jb in jobs]
    bucket_dist = distribution(buckets)
    bucket_n = sum(item["count"] for item in bucket_dist)
    if bucket_dist and bucket_n >= MIN_DIST:
        top = bucket_dist[0]
        head = "、".join(f"{i['key']} {i['share']}%" for i in bucket_dist)
        add("bucket_share", top["share"], "%",
            f"在招岗位的招聘类型分布：{head}（基于 {bucket_n} 个已判定类型的岗）。",
            sample=bucket_n, scope={"bucket": top["key"]},
            payload={"distribution": bucket_dist})

    # 门槛：经验年限中位数 + 学历要求众数
    years = [y for jb in jobs if (y := parse_min_years(jb.get("experience"))) is not None]
    if len(years) >= MIN_DIST:
        med = statistics.median(years)
        add("exp_years_median", med, "年",
            f"写明经验要求的岗位，年限下限中位数为 {med:g} 年（基于 {len(years)} 个岗）。",
            sample=len(years))

    edu_dist = distribution([jb.get("education") for jb in jobs])
    edu_n = sum(item["count"] for item in edu_dist)
    if edu_dist and edu_n >= MIN_DIST:
        top = edu_dist[0]
        head = "、".join(f"{i['key']} {i['share']}%" for i in edu_dist[:4])
        add("edu_requirement_mode", top["share"], "%",
            f"写明学历要求的岗位以「{top['key']}」为主：{head}（基于 {edu_n} 个岗）。",
            sample=edu_n, scope={"education": top["key"]},
            payload={"distribution": edu_dist[:6]})

    # 薪资：覆盖率极低（全库 1.8%），因此必须写明「只统计明写薪资的岗」
    salaries = [s for jb in jobs if (s := parse_salary_mid_k(jb.get("salary_text"))) is not None]
    if len(salaries) >= MIN_SALARY:
        med = statistics.median(salaries)
        add("salary_range_k", med, "K",
            f"明写薪资的岗位月薪中点中位数为 {med:g}K（仅基于 {len(salaries)} 个明写薪资的岗，"
            f"占该范围在招岗的 {len(salaries) * 100 / n:.0f}%）。",
            sample=len(salaries), dimension="compensation_intensity",
            payload={"p25": round(statistics.quantiles(salaries, n=4)[0], 1) if len(salaries) >= 4 else None,
                     "p75": round(statistics.quantiles(salaries, n=4)[2], 1) if len(salaries) >= 4 else None,
                     "coverage_pct": round(len(salaries) * 100 / n, 1)})
    return out


def compute_trends(snapshots: list[dict], today_active: int, now: datetime) -> list[dict]:
    """由每日快照算环比。没有可比快照就返回空——不拿 first_seen_at 分窗口凑一个数。

    snapshots：该主体的历史行 [{day, active_count}]，任意顺序。
    """
    by_day = {}
    for row in snapshots or []:
        day = str(row.get("day") or "")[:10]
        count = row.get("active_count")
        if day and isinstance(count, int):
            by_day[day] = count
    out = []
    for days, key in ((30, "hiring_trend_30d_pct"), (90, "hiring_trend_90d_pct")):
        target = (now.date() - timedelta(days=days)).isoformat()
        # 允许 ±3 天误差（cron 可能某天没跑成），取最接近的一条。
        best = min(
            (d for d in by_day if abs((datetime.fromisoformat(d).date() - datetime.fromisoformat(target).date()).days) <= 3),
            key=lambda d: abs((datetime.fromisoformat(d).date() - datetime.fromisoformat(target).date()).days),
            default=None,
        )
        if not best:
            continue
        prev = by_day[best]
        if prev < MIN_TREND or today_active < MIN_TREND:
            continue
        pct = (today_active - prev) / prev * 100
        out.append({
            "metric_key": key,
            "metric_value": round(pct, 2),
            "metric_unit": "%",
            "dimension": "hiring",
            "content": (f"在招岗位数 {today_active} 个，{days} 天前为 {prev} 个，"
                        f"环比 {_pct(pct)}（两期各 {min(prev, today_active)} 个岗以上）。"),
            "sample_size": min(prev, today_active),
            "scope": {"window_days": days},
            "payload": {"sample_n": min(prev, today_active), "baseline_day": best,
                        "baseline_count": prev, "current_count": today_active},
            "time_window": f"{best} 至 {now.date().isoformat()}",
        })
    return out


# ── IO 区 ────────────────────────────────────────────────────────────────
def fetch_subjects(supabase) -> list[dict]:
    """所有非 rejected 的主体。rejected 是人工治理结论，不该被派生层复活。"""
    rows = db.fetch_all_rows(
        lambda: supabase.table("insight_subjects").select(
            "id,company_id,kind,name,job_count,status"
        )
    )
    return [r for r in rows if r.get("status") in ("active", "retired")]


def fetch_company_names(supabase) -> dict:
    """company_profiles.id → 用于匹配 jobs.company 的名字集合（正名 + 别名）。"""
    out = {}
    for row in db.fetch_all_rows(
        lambda: supabase.table("company_profiles").select("id,company,aliases")
    ):
        names = [str(row.get("company") or "").strip()]
        names += [str(a).strip() for a in (row.get("aliases") or [])]
        cleaned = [n for n in names if n]
        if row.get("id") and cleaned:
            out[row["id"]] = cleaned
    return out


def fetch_jobs_for_company(conn, names: list[str]) -> list[dict]:
    """一次取一家公司的在招岗位。按公司分批而不是一次拉全库：
    39 万行 × 7 列常驻内存没有必要，且一家公司出错不该拖垮整轮。"""
    sql = (
        f"select {', '.join(JOB_COLUMNS)} from jobs "
        "where status = 'active' and company = any(%s)"
    )
    return jobs_db.fetch_all(conn, sql, (names,))


def assign_jobs_to_subjects(jobs: list[dict], bu_keys: set[str]) -> dict[str, list[dict]]:
    """按 bu_extract 的同一套规则把岗位挂到业务线上。

    ⚠️ 归属规则必须与 bu_extract 逐字一致（都走 extract_candidates + normalize_bu），
    否则「主体卡上写 397 个岗」和「点进去列出的岗位数」会对不上。
    """
    buckets: dict[str, list[dict]] = {key: [] for key in bu_keys}
    if not bu_keys:
        return buckets
    for job in jobs:
        for candidate in bu_extract.extract_candidates(job.get("title") or ""):
            key = bu_extract.normalize_bu(candidate)
            if key in buckets:
                buckets[key].append(job)
    return buckets


def _item_row(subject, company_id, metric, now_iso, valid_days: int) -> dict:
    """把纯函数算出的指标包装成 insight_items 行。

    grade='fact' + assertion='signal'：来源就是我们自己的岗位库，可核验、无第三方转述；
    展示门为 signal 专设分支（lib/insight-verification.passesSignalGate），不要求外部来源。
    """
    valid_until = (datetime.now(timezone.utc) + timedelta(days=valid_days)).date().isoformat()
    return {
        "company_id": company_id,
        "subject_id": subject["id"],
        "dimension": metric["dimension"],
        "grade": "fact",
        "origin": "derived",
        "assertion": "signal",
        "title": metric.get("title") or subject["name"],
        "content": metric["content"],
        "sample_size": metric["sample_size"],
        "payload": metric["payload"],
        "metric_key": metric["metric_key"],
        "metric_value": metric["metric_value"],
        "metric_unit": metric["metric_unit"],
        "scope": metric["scope"],
        "time_window": metric["time_window"],
        # 派生条目每天重算。给 valid_until 是**故意的止损**：派生链一旦停跑，
        # 页面上的数字会自己过期下架，而不是把陈旧数字一直当新鲜的展示。
        "valid_until": valid_until,
        "deidentified": True,
        "status": "active",
        "last_verified_at": now_iso,
        "updated_at": now_iso,
    }


def write_subject_metrics(supabase, subject, company_id, metrics, existing_rows,
                          now_iso, valid_days) -> tuple[int, int, int]:
    """把一个主体的指标行写库：有则更新、无则插入、本轮算不出的退役。"""
    by_key = {row.get("metric_key"): row for row in existing_rows if row.get("metric_key")}
    inserted = updated = retired = 0
    fresh_keys = set()
    for metric in metrics:
        row = _item_row(subject, company_id, metric, now_iso, valid_days)
        fresh_keys.add(metric["metric_key"])
        old = by_key.get(metric["metric_key"])
        if old:
            supabase.table("insight_items").update(row).eq("id", old["id"]).execute()
            updated += 1
        else:
            supabase.table("insight_items").insert(row).execute()
            inserted += 1
    # 本轮样本不够或字段消失的指标：退役而不是删除，保住 id 与可追溯性。
    for key, row in by_key.items():
        if key not in fresh_keys and row.get("status") == "active":
            supabase.table("insight_items").update(
                {"status": "retired", "updated_at": now_iso}
            ).eq("id", row["id"]).execute()
            retired += 1
    return inserted, updated, retired


def record_snapshot(supabase, subject_id: str, active_count: int, new_30d: int, day: str) -> None:
    """当日快照。同日重跑覆盖（upsert），趋势的唯一诚实来源。"""
    supabase.table("insight_subject_daily").upsert({
        "subject_id": subject_id, "day": day,
        "active_count": int(active_count), "new_30d": int(new_30d),
    }, on_conflict="subject_id,day").execute()


def fetch_snapshots(supabase, subject_ids: list[str], since_day: str) -> dict[str, list[dict]]:
    if not subject_ids:
        return {}
    out: dict[str, list[dict]] = {}
    for start in range(0, len(subject_ids), 200):
        chunk = subject_ids[start:start + 200]
        rows = db.fetch_all_rows(
            lambda chunk=chunk: supabase.table("insight_subject_daily")
            .select("subject_id,day,active_count").in_("subject_id", chunk).gte("day", since_day)
        )
        for row in rows:
            out.setdefault(row["subject_id"], []).append(row)
    return out


def fetch_existing_items(supabase, subject_ids: list[str]) -> dict[str, list[dict]]:
    if not subject_ids:
        return {}
    out: dict[str, list[dict]] = {}
    for start in range(0, len(subject_ids), 200):
        chunk = subject_ids[start:start + 200]
        rows = db.fetch_all_rows(
            lambda chunk=chunk: supabase.table("insight_items")
            .select("id,subject_id,metric_key,status")
            .eq("origin", "derived").in_("subject_id", chunk)
        )
        for row in rows:
            out.setdefault(row["subject_id"], []).append(row)
    return out


def main():
    parser = argparse.ArgumentParser(description="按主体（公司 / 业务线）派生结构化 signal 洞察")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    parser.add_argument("--company", default="", help="只处理 company_profiles.company 精确等于该值的一家")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少家公司（0=全部）")
    parser.add_argument("--valid-days", type=int,
                        default=int(os.environ.get("BU_SIGNAL_VALID_DAYS", "14")),
                        help="派生条目多久后自动过期（派生链停跑时自动止损）")
    args = parser.parse_args()

    started_at = _now_iso()
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    supabase = db.get_supabase()

    subjects = fetch_subjects(supabase)
    names_by_company = fetch_company_names(supabase)
    by_company: dict[str, list[dict]] = {}
    for subject in subjects:
        by_company.setdefault(subject["company_id"], []).append(subject)

    company_ids = [cid for cid in by_company if cid in names_by_company]
    if args.company:
        wanted = args.company.strip()
        company_ids = [cid for cid in company_ids if names_by_company[cid][0] == wanted]
    company_ids.sort(key=lambda cid: names_by_company[cid][0])
    if args.limit:
        company_ids = company_ids[:args.limit]

    all_subject_ids = [s["id"] for cid in company_ids for s in by_company[cid]]
    existing_items = {} if args.dry_run else fetch_existing_items(supabase, all_subject_ids)
    since = (now - timedelta(days=100)).date().isoformat()
    snapshots = {} if args.dry_run else fetch_snapshots(supabase, all_subject_ids, since)

    metrics_count = {
        "companies_scanned": 0, "subjects_scanned": 0, "subjects_with_metrics": 0,
        "items_inserted": 0, "items_updated": 0, "items_retired": 0,
        "snapshots": 0, "failed": 0,
    }
    conn = jobs_db.get_conn()
    try:
        for company_id in company_ids:
            company_subjects = by_company[company_id]
            display = names_by_company[company_id][0]
            try:
                jobs = fetch_jobs_for_company(conn, names_by_company[company_id])
                metrics_count["companies_scanned"] += 1
                if not jobs:
                    continue
                fns = job_function.classify_titles([j.get("title") for j in jobs])
                fns = None if all(f is None for f in fns) else fns
                # 职能按「岗位行对象」索引一次，避免每个主体重建一遍映射。
                fn_by_job = None if fns is None else {id(j): fns[i] for i, j in enumerate(jobs)}

                bu_subjects = [s for s in company_subjects if s["kind"] == "business_unit"]
                bu_keys = {bu_extract.normalize_bu(s["name"]): s for s in bu_subjects}
                buckets = assign_jobs_to_subjects(jobs, set(bu_keys))
                eligible_bu = sum(1 for key, rows in buckets.items() if len(rows) >= MIN_BU)

                for subject in company_subjects:
                    metrics_count["subjects_scanned"] += 1
                    if subject["kind"] == "company":
                        subject_jobs = jobs
                        subject_fns = fns
                    else:
                        key = bu_extract.normalize_bu(subject["name"])
                        subject_jobs = buckets.get(key, [])
                        subject_fns = (None if fn_by_job is None
                                       else [fn_by_job[id(j)] for j in subject_jobs])
                    metrics = compute_metrics(
                        subject_jobs, kind=subject["kind"], subject_name=subject["name"],
                        now=now, bu_count=eligible_bu, functions=subject_fns,
                    )
                    if metrics:
                        metrics += compute_trends(
                            snapshots.get(subject["id"], []), len(subject_jobs), now
                        )
                        metrics_count["subjects_with_metrics"] += 1
                    if args.dry_run:
                        if metrics:
                            print(f"{display} / {subject['name']}（{subject['kind']}，"
                                  f"{len(subject_jobs)} 岗）→ {len(metrics)} 条指标")
                            for m in metrics:
                                print(f"    [{m['metric_key']}] {m['content']}")
                        continue
                    ins, upd, ret = write_subject_metrics(
                        supabase, subject, company_id, metrics,
                        existing_items.get(subject["id"], []), _now_iso(), args.valid_days,
                    )
                    metrics_count["items_inserted"] += ins
                    metrics_count["items_updated"] += upd
                    metrics_count["items_retired"] += ret
                    new_30 = sum(1 for jb in subject_jobs
                                 if (d := days_between(jb.get("first_seen_at"), now)) is not None
                                 and d <= 30)
                    record_snapshot(supabase, subject["id"], len(subject_jobs), new_30, day)
                    metrics_count["snapshots"] += 1
            except Exception as exc:  # noqa: BLE001 —— 一家公司失败不该让整轮没产出
                metrics_count["failed"] += 1
                print(f"⚠️ {display} 派生失败，跳过继续：{type(exc).__name__}: {exc}", flush=True)
    finally:
        conn.close()

    print("完成：" + "，".join(f"{k}={v}" for k, v in metrics_count.items()))
    if args.dry_run:
        return
    ops_runs.record_ops_run(
        supabase, "bu_signals", metrics_count,
        status=ops_runs.status_from_counts(
            metrics_count["subjects_with_metrics"], metrics_count["failed"]
        ),
        started_at=started_at, finished_at=_now_iso(),
    )


if __name__ == "__main__":
    main()
