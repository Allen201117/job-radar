#!/usr/bin/env python3
"""从自有岗位标题抽取可治理的业务线 subject。

只使用香港 jobs 库的 ``company`` 与 ``title``，因此本轮只能写
``origin='derived_title'``。jobs 目前没有原始部门列；等 adapter 回填部门字段后，
再单独增加 ``derived_dept`` 路径，不能在这里把标题猜测伪装成部门事实。

抽取结果先经过停用词、频次阈值和 ``insight_subjects.status='rejected'`` 的人工
治理回路。宁可漏抽，也不把岗位名、届别或地点展示成业务线。
"""
import argparse
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

import db
import jobs_db
import normalizer
import ops_runs


DEFAULT_MIN_JOBS = 20
_WRAPPERS = "【】[]《》"
_JOB_ID_RE = re.compile(r"[（(]\s*J\d+\s*[）)]", re.IGNORECASE)
_BRACKET_RE = re.compile(r"【([^】]{2,12})】|\[([^\]]{2,12})\]")
_DASH_RE = re.compile(r"[-—–]")
_RECRUITMENT_RE = re.compile(
    # 2026-09-03 live 实测补：美团「北斗实习/大模型北斗实习/转正实习」、腾讯「新星引力计划」、
    # 蚂蚁「Plan A」都被抽成了业务线。它们是招聘项目/培养计划，不是业务线。
    # ⚠️ 只在**整词或结尾**匹配「计划/专项」，否则会误杀真业务线（如「计划财务部」不受影响，
    #    但「可灵AI专项」会被剔——它与「可灵AI」重复，剔掉正好去重）。
    r"\d{2,4}\s*届|校招|秋招|春招|社招|实习生?招聘|\d{4}(?:校园|招聘)|内推|热招|急招"
    r"|实习|转正|(?:计划|专项|项目)$|^plan\s|培养生|管培",
    re.IGNORECASE,
)
_JOB_ROLE_RE = re.compile(
    r"(?:工程师|专家|经理|实习生|顾问|设计师|架构师|策划|运营|开发|分析师|主管|总监|BP|HRBP|助理|专员)$",
    re.IGNORECASE,
)
_PURE_SYMBOL_RE = re.compile(r"^[^\w\u4e00-\u9fff]+$", re.UNICODE)
# 过泛词：单独出现时不构成业务线（live 实测：字节 data(335)/国际化(190)、网易 平台(24)）。
# ⚠️ 只做**全等**判断，不做包含——「数据平台」「国际化电商」是真业务线，不能误杀。
_GENERIC_TERMS = {
    "data", "平台", "中台", "国际化", "技术", "业务", "方向", "项目", "中心", "部门",
    "研发", "产品", "运营", "职能", "总部", "海外", "国内", "集团", "公司", "其他",
}
# 国家 / 地区（live 实测：蚂蚁 malaysia(42)）。城市走 _CITY_TERMS，这里补国家。
_COUNTRY_TERMS = {
    "malaysia", "singapore", "japan", "korea", "usa", "uk", "india", "indonesia",
    "thailand", "vietnam", "philippines", "brazil", "mexico", "germany", "france",
    "马来西亚", "新加坡", "日本", "韩国", "美国", "英国", "印度", "印尼", "泰国", "越南",
}
# 纯项目代号：J3 / A1 / UE5 之类（live 实测：腾讯 J3(36)）。
_CODE_RE = re.compile(r"^[a-z]{1,3}\d{1,3}$", re.IGNORECASE)
_COMPANY_SUFFIXES = ("股份有限公司", "有限公司", "集团", "控股", "中国", "china")

# 复用 crawler/normalizer.py 的城市别名；它覆盖当前岗位入库口径。这里补的是 spec
# 要求的常见海外城市与地区词，避免把地点后缀当作业务线。
_CITY_TERMS = {
    str(city).casefold() for city in normalizer.CITY_ALIASES
} | {
    str(city).casefold() for city in normalizer.CITY_ALIASES.values()
} | {
    "天津", "重庆", "苏州", "南京", "长沙", "郑州", "厦门", "青岛", "大连", "宁波",
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "香港", "澳门",
    "东京", "大阪", "首尔", "纽约", "旧金山", "西雅图", "洛杉矶", "伦敦", "巴黎", "柏林",
    "悉尼", "墨尔本", "多伦多", "温哥华", "新加坡", "beijing", "shanghai", "shenzhen",
    "guangzhou", "hangzhou", "chengdu", "wuhan", "xian", "hong kong", "singapore",
    "tokyo", "new york", "san francisco", "seattle", "london", "paris", "berlin",
}
_CITY_TERMS.discard("")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_bu(token: str) -> str:
    """业务线计数键：NFKC、英文大小写和包裹符归一，保留真实 BU 后缀。"""
    value = unicodedata.normalize("NFKC", str(token or "")).strip()
    while len(value) >= 2 and value[0] in _WRAPPERS and value[-1] in _WRAPPERS:
        value = value[1:-1].strip()
    return re.sub(r"\s+", " ", value).casefold()


def normalize_company(value: str) -> str:
    """镜像 lib/company-normalize.ts，供 company_profiles 对账，不做模糊合并。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(r"\s+", "", text)
    changed = True
    while changed:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            if len(text) > len(suffix) and text.endswith(suffix):
                text = text[:-len(suffix)]
                changed = True
    return text


def extract_candidates(title: str) -> list[str]:
    """从一个岗位标题抽三种业务线候选，保留首次出现顺序。

    对连续 ``-`` 仅取最末尾一段：``...-Data-抖音/直播/电商/剪映`` 的 suffix 是
    ``抖音/直播/电商/剪映``。中间段不符合 spec 的「结尾 -X」定义，不能凭频次把
    ``Data`` 之类的岗位描述误当业务线。
    """
    text = _JOB_ID_RE.sub("", str(title or "")).strip()
    if not text:
        return []
    out = []
    normalized_seen = set()

    def add(value):
        value = str(value or "").strip()
        key = normalize_bu(value)
        if value and key and key not in normalized_seen:
            out.append(value)
            normalized_seen.add(key)

    for match in _BRACKET_RE.finditer(text):
        add(match.group(1) or match.group(2))

    # prefix：开头 X-。后续的岗位名/方向仍由 is_noise 与频次门过滤。
    first_dash = _DASH_RE.search(text)
    if first_dash:
        prefix = text[:first_dash.start()].strip()
        if 2 <= len(prefix) <= 12 and "(" not in prefix and "（" not in prefix:
            add(prefix)

    # suffix：只取最后一个分隔符后的结尾 X，严格遵守 spec 的「结尾 -X」。
    dashes = list(_DASH_RE.finditer(text))
    if dashes:
        suffix = text[dashes[-1].end():].strip()
        if 2 <= len(suffix) <= 14 and "(" not in suffix and "（" not in suffix:
            add(suffix)
    return out


def is_noise(token: str, company: str = "") -> bool:
    """停用词门。company 参数是可选的，保持该函数离线、可单测。"""
    value = normalize_bu(token)
    if len(value) < 2 or (len(value) == 1 and value.isascii() and value.isalpha()):
        return True
    if value.isdigit() or _PURE_SYMBOL_RE.fullmatch(value):
        return True
    if _RECRUITMENT_RE.search(value) or _JOB_ROLE_RE.search(value):
        return True
    if "大区" in value or "地区" in value or "分公司" in value or "事业部所在地" in value:
        return True
    if any(city in value for city in _CITY_TERMS):
        return True

    if value in _GENERIC_TERMS or value in _COUNTRY_TERMS or _CODE_RE.fullmatch(value):
        return True

    company_value = normalize_bu(company)
    if company_value and (value == company_value or (
        value in company_value and len(value) >= max(2, len(company_value) - 2)
    )):
        return True
    return False


def eligible_counts(counts: Counter, min_jobs: int) -> dict[str, int]:
    """阈值门：只留下达到下限的业务线及其当前岗位数。"""
    return {name: int(count) for name, count in counts.items() if int(count) >= int(min_jobs)}


def build_profile_index(profiles: list[dict]):
    """画像精确名优先、归一名仅在唯一时命中，避免不同公司被自动并到一起。"""
    exact, normalized = {}, defaultdict(list)
    by_id = {}
    usable = []
    for profile in profiles or []:
        profile_id = profile.get("id")
        company = str(profile.get("company") or "").strip()
        if not profile_id or not company:
            continue
        by_id[profile_id] = profile
        usable.append((profile, company))

    # 正式 company 的精确相等优先级高于任意别名，不能因 profiles 的分页顺序反过来。
    for profile, company in usable:
        exact.setdefault(company, profile)
    for profile, company in usable:
        for value in [company, *(profile.get("aliases") or [])]:
            name = str(value or "").strip()
            if not name:
                continue
            if name != company:
                exact.setdefault(name, profile)
            key = normalize_company(name)
            if key:
                normalized[key].append(profile)
    unique_normalized = {
        key: rows[0] for key, rows in normalized.items()
        if len({row["id"] for row in rows}) == 1
    }
    return exact, unique_normalized, by_id


def resolve_profile(company: str, exact: dict, normalized: dict):
    name = str(company or "").strip()
    return exact.get(name) or normalized.get(normalize_company(name))


def collect_company_data(job_rows: list[dict], profile_index, min_jobs: int):
    """jobs 行按画像公司聚合，返回 subject 写入前的纯数据。"""
    exact, normalized, _ = profile_index
    data = {}
    unmatched_companies = set()
    for row in job_rows or []:
        company = str((row or {}).get("company") or "").strip()
        profile = resolve_profile(company, exact, normalized)
        if not profile:
            if company:
                unmatched_companies.add(company)
            continue
        profile_id = profile["id"]
        item = data.setdefault(profile_id, {
            "company_id": profile_id,
            "company": str(profile.get("company") or company),
            "job_count": 0,
            "candidate_total": 0,
            "counts": Counter(),
        })
        item["job_count"] += 1
        for candidate in extract_candidates(row.get("title") or ""):
            item["candidate_total"] += 1
            normalized_candidate = normalize_bu(candidate)
            if normalized_candidate and not is_noise(normalized_candidate, item["company"]):
                item["counts"][normalized_candidate] += 1
    for item in data.values():
        item["kept"] = eligible_counts(item["counts"], min_jobs)
    return data, unmatched_companies


def plan_subject_changes(company_data: dict, existing_rows: list[dict]):
    """把当前抽取结果与已有 subject 对账，返回 insert/update/retire 的可测试计划。"""
    existing = {
        (row.get("company_id"), row.get("name")): row
        for row in (existing_rows or [])
        if row.get("company_id") and row.get("name")
    }
    plan = {"insert": [], "update": [], "retire": [], "rejected_skipped": 0}
    for company_id, item in company_data.items():
        kept = dict(item.get("kept") or {})
        raw_counts = {name: int(count) for name, count in (item.get("counts") or {}).items()}
        candidates = dict(kept)
        # 阈值只控制「新发现/复活」的候选。已治理过且仍在招的 active subject 即使暂时
        # 降到阈值以下，也应回写真实 job_count；spec 规定的是归零才 retired，不是 < min 就下架。
        for (existing_company_id, name), row in existing.items():
            if (existing_company_id == company_id and row.get("kind") == "business_unit"
                    and row.get("status") == "active" and name in raw_counts):
                candidates[name] = raw_counts[name]
        # 公司本身也是统一的 subject。业务线来自标题，但这里的公司岗位总数同样是自有 jobs 信号。
        candidates[item["company"]] = int(item.get("job_count") or 0)
        for name, job_count in candidates.items():
            kind = "company" if name == item["company"] else "business_unit"
            row = existing.get((company_id, name))
            if row and row.get("status") == "rejected":
                plan["rejected_skipped"] += 1
                continue
            payload = {
                "company_id": company_id,
                "kind": kind,
                "name": name,
                "origin": "derived_title",
                "job_count": job_count,
                "status": "active",
            }
            if row:
                plan["update"].append(payload)
            else:
                plan["insert"].append(payload)

        # 只退役本轮真正扫描到公司的 title-derived 业务线；company subject 不在此治理范围。
        candidate_names = set(raw_counts)
        for (existing_company_id, name), row in existing.items():
            if existing_company_id != company_id:
                continue
            if (row.get("kind") == "business_unit" and row.get("origin") == "derived_title"
                    and row.get("status") == "active" and name not in candidate_names):
                plan["retire"].append({"id": row.get("id"), "company_id": company_id, "name": name})
    return plan


def fetch_active_jobs(company: str = "") -> list[dict]:
    conn = jobs_db.get_conn()
    try:
        sql = "select company, title from jobs where status = 'active'"
        params = ()
        if company:
            sql += " and company = %s"
            params = (company,)
        return jobs_db.fetch_all(conn, sql, params)
    finally:
        conn.close()


def fetch_existing_subjects(supabase):
    return db.fetch_all_rows(
        lambda: supabase.table("insight_subjects").select(
            "id,company_id,kind,name,origin,job_count,status"
        )
    )


def apply_plan(supabase, plan: dict, now: str):
    """按计划写 Supabase；调用方逐公司隔离异常，避免一个公司拖垮整轮。"""
    inserted = updated = retired = 0
    for payload in plan["insert"]:
        supabase.table("insight_subjects").insert({
            **payload, "first_seen_at": now, "last_seen_at": now, "updated_at": now,
        }).execute()
        inserted += 1
    for payload in plan["update"]:
        supabase.table("insight_subjects").update({
            "kind": payload["kind"], "origin": "derived_title", "job_count": payload["job_count"],
            "status": "active", "last_seen_at": now, "updated_at": now,
        }).eq("company_id", payload["company_id"]).eq("name", payload["name"]).execute()
        updated += 1
    for payload in plan["retire"]:
        supabase.table("insight_subjects").update({
            "status": "retired", "job_count": 0, "updated_at": now,
        }).eq("id", payload["id"]).execute()
        retired += 1
    return inserted, updated, retired


def _print_company(item):
    pairs = sorted((item.get("kept") or {}).items(), key=lambda pair: (-pair[1], pair[0]))
    print(f"{item['company']}：active={item['job_count']} candidates={item['candidate_total']} kept={len(pairs)}")
    print("  " + ("；".join(f"{name} ({count})" for name, count in pairs) if pairs else "（无达到阈值的业务线）"))


def main():
    parser = argparse.ArgumentParser(description="从 active jobs 标题抽取业务线 insight subjects")
    parser.add_argument("--dry-run", action="store_true", help="只打印抽取结果，不写 insight_subjects / ops_runs")
    parser.add_argument("--company", default="", help="只处理 jobs.company 精确等于该值的一家公司")
    parser.add_argument("--min-jobs", type=int, default=None, help="业务线入库的最小 active 岗位数")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个已匹配画像的公司（0=全部）")
    args = parser.parse_args()
    min_jobs = args.min_jobs if args.min_jobs is not None else int(os.environ.get("BU_MIN_JOBS", DEFAULT_MIN_JOBS))
    if min_jobs < 1:
        parser.error("--min-jobs 必须 >= 1")

    started_at = _now_iso()
    supabase = db.get_supabase()
    profiles = db.fetch_all_rows(lambda: supabase.table("company_profiles").select("id,company,aliases"))
    profile_index = build_profile_index(profiles)
    job_rows = fetch_active_jobs(args.company)
    company_data, unmatched = collect_company_data(job_rows, profile_index, min_jobs)
    if args.limit:
        selected = sorted(company_data, key=lambda key: company_data[key]["company"])[:args.limit]
        company_data = {key: company_data[key] for key in selected}

    for item in sorted(company_data.values(), key=lambda row: row["company"]):
        _print_company(item)
    if unmatched:
        print(f"跳过 {len(unmatched)} 家未匹配 company_profiles 的公司（不新建画像）。")
    if args.dry_run:
        print("dry-run：未写 insight_subjects 或 ops_runs。")
        return

    existing = fetch_existing_subjects(supabase)
    metrics = {
        "companies_scanned": 0,
        "candidates_total": 0,
        "kept": 0,
        "inserted": 0,
        "updated": 0,
        "retired": 0,
        "rejected_skipped": 0,
        "failed": 0,
    }
    now = _now_iso()
    for company_id, item in sorted(company_data.items(), key=lambda pair: pair[1]["company"]):
        metrics["companies_scanned"] += 1
        metrics["candidates_total"] += item["candidate_total"]
        metrics["kept"] += len(item["kept"])
        try:
            company_existing = [row for row in existing if row.get("company_id") == company_id]
            plan = plan_subject_changes({company_id: item}, company_existing)
            inserted, updated, retired = apply_plan(supabase, plan, now)
            metrics["inserted"] += inserted
            metrics["updated"] += updated
            metrics["retired"] += retired
            metrics["rejected_skipped"] += plan["rejected_skipped"]
        except Exception as exc:  # 单公司错误不能让其它 subject 不对账。
            metrics["failed"] += 1
            print(f"⚠️ {item['company']} 写入失败，已跳过继续：{type(exc).__name__}")

    ops_runs.record_ops_run(
        supabase, "bu_extract", metrics,
        status=ops_runs.status_from_counts(metrics["companies_scanned"], metrics["failed"]),
        started_at=started_at, finished_at=_now_iso(),
    )
    print("完成：" + "，".join(f"{key}={value}" for key, value in metrics.items()))


if __name__ == "__main__":
    main()
