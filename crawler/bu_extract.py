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
    # 第二轮（全库跑完抽检 100 条）：社会招聘(172)/内部招聘(91)/培训生(162)/CRC Intern(111)
    # 都进了库，说明只写「社招/实习」这类简称挡不住全称与英文写法。
    r"\d{2,4}\s*届|校招|秋招|春招|社招|实习生?招聘|\d{4}(?:校园|招聘)|内推|热招|急招"
    r"|实习|转正|(?:计划|专项|项目)$|^plan\s|培养生|管培"
    r"|社会招聘|内部招聘|校园招聘|公开招聘|招聘$|培训生|储备生|见习"
    r"|\bintern(?:ship)?\b|\btrainee\b|\bcampus\b|\bgraduate\b",
    re.IGNORECASE,
)
_JOB_ROLE_RE = re.compile(
    # 2026-09-03 live：跑到外企源上才暴露——Apple 抽出 manager(30)/genius(23)。
    # 英文岗位名同样要挡，且英文里岗位名常在**开头**（"Manager - Retail"），故不锚定结尾。
    # 第二轮补一线岗位名：店员(98)/维修技师(83)/区域业代(119) 也被当成了业务线。
    r"(?:工程师|专家|经理|实习生|顾问|设计师|架构师|策划|运营|开发|分析师|主管|总监|BP|HRBP|助理|专员"
    r"|店员|店长|技师|业代|导购|司机|操作工|文员|销售|客服|收银|保安|厨师|服务员|护士|药师|教师"
    r"|研究员|科学家|岗)$"
    r"|^(?:manager|engineer|specialist|analyst|director|lead|intern|associate|consultant"
    r"|designer|developer|scientist|architect|coordinator|representative|technician"
    r"|supervisor|advisor|expert|officer|recruiter|genius|advisor)s?$",
    re.IGNORECASE,
)
_PURE_SYMBOL_RE = re.compile(r"^[^\w\u4e00-\u9fff]+$", re.UNICODE)
# 过泛词：单独出现时不构成业务线（live 实测：字节 data(335)/国际化(190)、网易 平台(24)）。
# ⚠️ 只做**全等**判断，不做包含——「数据平台」「国际化电商」是真业务线，不能误杀。
_GENERIC_TERMS = {
    "data", "平台", "中台", "国际化", "技术", "业务", "方向", "项目", "中心", "部门",
    "研发", "产品", "运营", "职能", "总部", "海外", "国内", "集团", "公司", "其他",
    # 第二轮 live：「中国(111)」被当成了业务线；它是区域不是业务线。
    "中国", "中国区", "大中华区", "亚太", "全球", "本部", "分部",
    # 大区名：只做**全等**判断，所以「外运华东」这类真子公司不受影响。
    "华东", "华南", "华北", "华中", "西南", "西北", "东北", "华西",
}
# 国家 / 地区（live 实测：蚂蚁 malaysia(42)）。城市走 _CITY_TERMS，这里补国家。
_COUNTRY_TERMS = {
    "malaysia", "singapore", "japan", "korea", "usa", "uk", "india", "indonesia",
    "thailand", "vietnam", "philippines", "brazil", "mexico", "germany", "france",
    # 地区缩写（live：Apple 抽出 us(162)）。都是地点不是业务线。
    "us", "eu", "emea", "apac", "amer", "latam", "anz", "na", "row",
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


_OPEN_TO_CLOSE = {"（": "）", "(": ")", "【": "】", "[": "]", "《": "》"}
_CLOSERS = set(_OPEN_TO_CLOSE.values())


def _strip_unbalanced(value: str) -> str:
    """去掉首尾**没有配对**的括号。

    live 实测：源标题形如「（基石产品线）-高级研究员」，按连字符切出的碎片是
    「基石产品线）」——它作为业务线名直接展示给用户就是个错字。
    只去首尾不配对的那一个，不动内部括号（「剪映CapCut（国际）」保持原样，
    由停用词与阈值处理）。
    """
    text = value
    while text and text[-1] in _CLOSERS:
        closer = text[-1]
        opener = next(o for o, c in _OPEN_TO_CLOSE.items() if c == closer)
        if text.count(closer) <= text.count(opener):
            break
        text = text[:-1].strip()
    while text and text[0] in _OPEN_TO_CLOSE:
        if text.count(text[0]) <= text.count(_OPEN_TO_CLOSE[text[0]]):
            break
        text = text[1:].strip()
    return text


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
    # ⚠️ 「前缀 X-」「后缀 -X」是**中文招聘站的书写约定**（腾讯云-后端工程师 / 快手【主站】），
    # 本抽取器也只在 38,491 条中文标题上验证过。英文标题里连字符是**构词符**
    # （Multi-Channel / Pre-Sales / Mixed-Signal），照搬会把词根当业务线——
    # 2026-09-03 live 实测：Amazon 抽出 multi(33)/pre(22)、Apple 抽出 us(162)/mixed(20)。
    # 所以纯英文标题只走 【X】 括号形态，不走连字符。宁可漏抽，不可错抽。
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))

    def add(value):
        value = _strip_unbalanced(str(value or "").strip())
        key = normalize_bu(value)
        if value and key and key not in normalized_seen:
            out.append(value)
            normalized_seen.add(key)

    for match in _BRACKET_RE.finditer(text):
        add(match.group(1) or match.group(2))

    if not has_cjk:
        return out

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


def pick_display(variants: Counter, fallback: str) -> str:
    """归一键 → 展示名：取出现最多的原始写法，同频取更长的（保住大小写与空格更完整那份）。

    存在的理由：counts 的键是 casefold 过的归一键（「tiktok shop」），它是**身份**；
    页面要展示的是**原文**（「TikTok Shop」）。两者分开，改展示不会动身份。
    """
    if not variants:
        return fallback
    return max(variants.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


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
    unmatched_companies = Counter()
    for row in job_rows or []:
        company = str((row or {}).get("company") or "").strip()
        profile = resolve_profile(company, exact, normalized)
        if not profile:
            if company:
                unmatched_companies[company] += 1
            continue
        profile_id = profile["id"]
        item = data.setdefault(profile_id, {
            "company_id": profile_id,
            "company": str(profile.get("company") or company),
            "job_count": 0,
            "candidate_total": 0,
            "counts": Counter(),
            "display": defaultdict(Counter),
        })
        item["job_count"] += 1
        for candidate in extract_candidates(row.get("title") or ""):
            item["candidate_total"] += 1
            normalized_candidate = normalize_bu(candidate)
            if normalized_candidate and not is_noise(normalized_candidate, item["company"]):
                item["counts"][normalized_candidate] += 1
                # 归一键用于计数与去重；展示名另记，否则「TikTok Shop」会以 casefold 后的
                # 「tiktok shop」出现在洞察库页面上。见 pick_display。
                item["display"][normalized_candidate][candidate.strip()] += 1
    for item in data.values():
        item["kept"] = eligible_counts(item["counts"], min_jobs)
    return data, unmatched_companies


def plan_subject_changes(company_data: dict, existing_rows: list[dict]):
    """把当前抽取结果与已有 subject 对账，返回 insert/update/retire 的可测试计划。"""
    # ⚠️ 已有行按**归一键**索引，不按 name：name 是展示名（「TikTok Shop」），
    # 展示名的大小写/空格可能随抓到的标题变化；身份必须是稳定的归一键，
    # 否则同一条业务线会因为一次大小写变化被当成新主体再插一行。
    existing = {
        (row.get("company_id"), normalize_bu(row.get("name"))): row
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
        for (existing_company_id, key), row in existing.items():
            if (existing_company_id == company_id and row.get("kind") == "business_unit"
                    and row.get("status") == "active" and key in raw_counts):
                candidates[key] = raw_counts[key]
        # 公司本身也是统一的 subject。业务线来自标题，但这里的公司岗位总数同样是自有 jobs 信号。
        company_key = normalize_bu(item["company"])
        candidates[company_key] = int(item.get("job_count") or 0)
        display_variants = item.get("display") or {}
        for key, job_count in candidates.items():
            is_company = key == company_key
            kind = "company" if is_company else "business_unit"
            name = item["company"] if is_company else pick_display(
                display_variants.get(key) or Counter(), key
            )
            row = existing.get((company_id, key))
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
                plan["update"].append({**payload, "id": row.get("id")})
            else:
                plan["insert"].append(payload)

        # 只退役本轮真正扫描到公司的 title-derived 业务线；company subject 不在此治理范围。
        candidate_names = set(raw_counts)
        for (existing_company_id, key), row in existing.items():
            if existing_company_id != company_id:
                continue
            if (row.get("kind") == "business_unit" and row.get("origin") == "derived_title"
                    and row.get("status") == "active" and key not in candidate_names):
                plan["retire"].append({"id": row.get("id"), "company_id": company_id,
                                       "name": row.get("name")})
    return plan


def plan_new_profiles(unmatched: set, min_jobs: int, counts: dict) -> list[dict]:
    """给「有足够在招岗但还没有画像」的公司准备画像行（纯函数，便于单测）。

    ⚠️ 为什么必须建：company_profiles 是 insight_subjects 的外键父表，没有画像的公司
    **整家被挡在洞察库外**。live 实测 1,985 家有在招岗的公司里只有 976 家有画像，
    而恰恰是缺画像的那批（国聘上的央企子公司）才写明了薪资——洞察库里
    salary_range_k 一条都出不来，根因就是这个，不是解析器不行。

    ⚠️ 新画像一律带 insight_checked_at=now()：富化队列按 `insight_checked_at nulls first`
    取活，留空会让这 1,000 家长尾**插到用户真正关心的公司前面**去花 LLM/搜索预算。
    覆盖率要补，富化优先级不能动。
    """
    now = _now_iso()
    return [
        {"company": name, "insight_checked_at": now}
        for name in sorted(unmatched)
        if int(counts.get(name, 0)) >= int(min_jobs)
    ]


def create_profiles(supabase, rows: list[dict], batch: int = 200) -> int:
    """按批插画像。company 上有唯一约束，并发/重跑时靠 ignore_duplicates 幂等。"""
    created = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        supabase.table("company_profiles").upsert(
            chunk, on_conflict="company", ignore_duplicates=True
        ).execute()
        created += len(chunk)
    return created


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
        # 按 id 定位：展示名会随抓到的标题写法变化，按 name 定位会更新不到（或更新错行）。
        supabase.table("insight_subjects").update({
            "kind": payload["kind"], "name": payload["name"], "origin": "derived_title",
            "job_count": payload["job_count"],
            "status": "active", "last_seen_at": now, "updated_at": now,
        }).eq("id", payload["id"]).execute()
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
    parser.add_argument("--create-profiles", action="store_true",
                        help="给「有足够在招岗却没有画像」的公司补建 company_profiles")
    parser.add_argument("--profile-min-jobs", type=int, default=None,
                        help="补建画像的最小在招岗数（默认 10，与公司级统计门槛一致）")
    args = parser.parse_args()
    create_profiles_enabled = args.create_profiles or os.environ.get(
        "BU_CREATE_PROFILES", "").lower() in ("1", "true", "yes")
    profile_min_jobs = args.profile_min_jobs if args.profile_min_jobs is not None else int(
        os.environ.get("BU_PROFILE_MIN_JOBS", "10"))
    min_jobs = args.min_jobs if args.min_jobs is not None else int(os.environ.get("BU_MIN_JOBS", DEFAULT_MIN_JOBS))
    if min_jobs < 1:
        parser.error("--min-jobs 必须 >= 1")

    started_at = _now_iso()
    supabase = db.get_supabase()
    profiles = db.fetch_all_rows(lambda: supabase.table("company_profiles").select("id,company,aliases"))
    profile_index = build_profile_index(profiles)
    job_rows = fetch_active_jobs(args.company)
    company_data, unmatched = collect_company_data(job_rows, profile_index, min_jobs)

    # 先给「有足够在招岗却没有画像」的公司补画像，再用新画像重算一次归属，
    # 否则这些公司这一轮仍然进不了洞察库（下一轮才生效，白等一天）。
    if create_profiles_enabled and not args.dry_run and unmatched:
        new_profiles = plan_new_profiles(set(unmatched), profile_min_jobs, unmatched)
        if new_profiles:
            created = create_profiles(supabase, new_profiles)
            print(f"补建 {created} 家公司画像（在招岗 >= {profile_min_jobs} 且此前无画像）。")
            profiles = db.fetch_all_rows(
                lambda: supabase.table("company_profiles").select("id,company,aliases"))
            profile_index = build_profile_index(profiles)
            company_data, unmatched = collect_company_data(job_rows, profile_index, min_jobs)
    if args.limit:
        selected = sorted(company_data, key=lambda key: company_data[key]["company"])[:args.limit]
        company_data = {key: company_data[key] for key in selected}

    for item in sorted(company_data.values(), key=lambda row: row["company"]):
        _print_company(item)
    if unmatched:
        print(f"跳过 {len(unmatched)} 家未匹配 company_profiles 的公司"
              f"（在招岗 < {profile_min_jobs}，不值得单独建画像）。")
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
