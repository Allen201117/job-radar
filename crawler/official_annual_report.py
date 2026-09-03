#!/usr/bin/env python3
"""巨潮 A 股年报官方事实：员工构成与应付职工薪酬（T2）。

网络层只负责查询/下载；文本解析、指标推导和条目组装保持纯函数，方便用固定年报片段测试。
年报查询必须使用 searchkey，不能使用实测无结果的 stock 参数。
"""
import argparse
import io
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone

import httpx

import db
import official_cninfo as CN
import ops_runs
import wikidata


CNINFO_BASE = "http://www.cninfo.com.cn"
CNINFO_STATIC = "http://static.cninfo.com.cn"
SEARCH_PAGE = f"{CNINFO_BASE}/new/commonUrl/pageOfSearch?url=disclosure/list/search"
ANNOUNCEMENT_URL = f"{CNINFO_BASE}/new/hisAnnouncement/query"
UA = {"User-Agent": "JobRadar/1.0 (career-insights annual-report)"}
ORIGIN = "official_filing"
# v3 断言强度：年报是官方披露 → fact。与 insight_backlog.normalize_assertion 同口径，
# 改这里必须同步那边（两处都写库）。
ASSERTION = "fact"
SOURCE_KIND = "official_filing"
DEFAULT_LIMIT = 40

_NUMBER = r"([\d,，]+(?:\.\d+)?)"


def _now():
    return datetime.now(timezone.utc).isoformat()


def enabled():
    """本链路独立开关，默认开启，不改变 INSIGHT_CNINFO_ENABLED 的既有语义。"""
    return str(os.environ.get("INSIGHT_ANNUAL_REPORT_ENABLED", "true")).strip().lower() in (
        "1", "true", "yes", "on",
    )


def _response_date(value):
    """巨潮 announcementTime（毫秒）或日期字符串 → ISO 日期；不可用时空串。"""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value or "").strip()
    match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if match:
        return "-".join(match.groups())
    return ""


def list_annual_reports(client, company_short_name, sec_code):
    """按实测 searchkey 查询并过滤 A 股年报正文，按报告年度倒序返回。"""
    client.get(SEARCH_PAGE, headers=UA, timeout=30).raise_for_status()  # 先取匿名 JSESSIONID
    response = client.post(
        ANNOUNCEMENT_URL,
        data={
            "stock": "",
            "searchkey": f"{company_short_name}年度报告",
            "category": "category_ndbg_szsh",
            "pageNum": "1",
            "pageSize": "50",
            "column": "szse",
            "tabName": "fulltext",
            # seDate 不能传：实测日期参数会触发 500。
            "sortName": "",
            "sortType": "",
            "isHLtitle": "false",  # 关掉高亮：true 时标题带 <em> 标签，字面过滤会全部漏掉（2026-09-03 live 踩坑）
        },
        headers={
            **UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json() or {}
    out = []
    wanted = str(sec_code or "").strip()
    for announcement in data.get("announcements") or []:
        # 双保险：即使服务端仍返回高亮标签也剥掉，过滤只看纯文本。
        title = re.sub(r"<[^>]+>", "", str(announcement.get("announcementTitle") or "")).strip()
        if str(announcement.get("secCode") or "").strip() != wanted:
            continue
        if "年年度报告" not in title or any(word in title for word in ("摘要", "英文", "已取消")):
            continue
        year_match = re.search(r"(\d{4})年年度报告", title)
        adjunct_url = str(announcement.get("adjunctUrl") or "").strip()
        if not year_match or not adjunct_url:
            continue
        out.append({
            "year": int(year_match.group(1)),
            "adjunct_url": adjunct_url,
            "publish_date": _response_date(announcement.get("announcementTime") or announcement.get("publishDate")),
            "title": title,
        })
    return sorted(out, key=lambda report: report["year"], reverse=True)


def download_pdf(client, adjunct_url):
    """下载公开年报 PDF；慢链路每次间隔 5 秒，最多尝试 3 次。"""
    url = f"{CNINFO_STATIC}/{str(adjunct_url or '').lstrip('/')}"
    for attempt in range(3):
        try:
            response = client.get(url, headers=UA, timeout=120)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # 单份 PDF 失败不能中断整轮
            if attempt == 2:
                print(f"  [annual-report-download] {adjunct_url}: {type(exc).__name__}: {str(exc)[:120]}")
                return None
            time.sleep(5)
    return None


def _to_number(value):
    try:
        return int(float(str(value).replace(",", "").replace("，", "")))
    except (TypeError, ValueError):
        return None


def _extract_labeled_number(text, labels):
    for label in labels:
        # 标签后可能跟「（人）」「(人)」这类单位括注（2025 年报格式，live 踩坑），再跟冒号/空白。
        match = re.search(rf"{re.escape(label)}\s*(?:[（(][^（）()]{{0,6}}[）)])?\s*[：:]?\s*{_NUMBER}", text)
        if match:
            value = _to_number(match.group(1))
            if value is not None:
                return value
    return None


def extract_employee_fields(text):
    """从年报员工情况文本抽取人数；容忍常见学历别名。"""
    text = str(text or "")
    fields = {}
    mappings = {
        "employee_total": ("在职员工的数量合计",),
        "emp_production": ("生产人员",),
        "emp_sales": ("销售人员",),
        "emp_technical": ("技术人员",),
        "emp_finance": ("财务人员",),
        "emp_admin": ("行政人员",),
        "edu_phd": ("博士",),
        # 银行/国企年报常写「硕士及以上」「研究生」，长标签放前面优先命中。
        "edu_master": ("硕士及以上", "硕士研究生", "研究生及以上", "硕士", "研究生"),
        "edu_below_bachelor": ("大专及以下", "专科及以下", "本科以下", "大专", "专科"),
    }
    for key, labels in mappings.items():
        value = _extract_labeled_number(text, labels)
        if value is not None:
            fields[key] = value
    # “本科以下”是低学历档，不能被宽泛的“本科”正则重复算进本科及以上。
    bachelor = re.search(rf"本科(?!以下)\s*[：:]?\s*{_NUMBER}", text)
    if bachelor:
        value = _to_number(bachelor.group(1))
        if value is not None:
            fields["edu_bachelor"] = value
    return fields


def _unit_multiplier(unit_hint):
    hint = str(unit_hint or "").replace(" ", "")
    if "千元" in hint:
        return 1000
    # “万元”不是实测标准表头，但识别到时按明确单位换算，避免悄悄失真。
    if "万元" in hint:
        return 10000
    if re.search(r"单位[：:]?人民币?元|单位[：:]?元", hint):
        return 1
    return None


def extract_compensation_fields(text, unit_hint):
    """提取短期（职工）薪酬行的第二列“本期增加”，统一换算为元。"""
    multiplier = _unit_multiplier(unit_hint)
    if multiplier is None:
        return {}
    # 一、短期薪酬（合计） 期初 本期增加 本期减少 期末；名称可写“短期职工薪酬”。
    pattern = rf"短期(?:职工)?薪酬[^\n\d]*{_NUMBER}\s+{_NUMBER}"
    match = re.search(pattern, str(text or ""))
    if not match:
        return {}
    reported = _to_number(match.group(2))
    if reported is None:
        return {}
    return {
        "compensation_current_year_added_reported": reported,
        "compensation_unit": "元" if multiplier == 1 else "千元" if multiplier == 1000 else "万元",
        "compensation_current_year_added_cny": reported * multiplier,
    }


def _excerpt(text, markers):
    lines = []
    for line in str(text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned and any(marker in cleaned for marker in markers):
            lines.append(cleaned)
    return " ".join(lines)[:300]


def parse_employee_section(pdf_bytes):
    """从 PDF 找员工页和薪酬附注页；扫描版/缺章节返回可观测错误而不抛出。"""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texts = [(page.extract_text() or "") for page in pdf.pages]
    except Exception:
        return {"parse_error": "scanned_pdf"}

    employee_index = next((i for i, text in enumerate(texts) if "在职员工的数量合计" in text), None)
    if employee_index is None:
        return {"parse_error": "employee_section_not_found"}
    employee_text = "\n".join(texts[max(0, employee_index - 1):employee_index + 2])
    fields = extract_employee_fields(employee_text)
    fields["employee_excerpt"] = _excerpt(
        employee_text,
        ("在职员工的数量合计", "生产人员", "销售人员", "技术人员", "财务人员", "行政人员", "博士", "硕士", "本科", "大专", "专科"),
    )

    for text in texts:
        if "应付职工薪酬" not in text or "本期增加" not in text:
            continue
        compensation = extract_compensation_fields(text, text)
        if compensation:
            fields.update(compensation)
            fields["compensation_excerpt"] = _excerpt(text, ("单位", "短期薪酬", "短期职工薪酬", "本期增加"))
            break
    return fields


def _ratio(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 4)


def derive_metrics(fields):
    """把会计/人数原字段变成面向求职者的比例与人均量级。"""
    fields = fields or {}
    total = _to_number(fields.get("employee_total"))
    education = {
        "phd": _to_number(fields.get("edu_phd")),
        "master": _to_number(fields.get("edu_master")),
        "bachelor": _to_number(fields.get("edu_bachelor")),
    }
    metrics = {"technical_ratio": _ratio(_to_number(fields.get("emp_technical")), total)}
    if all(value is not None for value in education.values()):
        metrics["bachelor_or_above_ratio"] = _ratio(sum(education.values()), total)
    if education["phd"] is not None and education["master"] is not None:
        metrics["master_or_above_ratio"] = _ratio(education["phd"] + education["master"], total)
    compensation = _to_number(fields.get("compensation_current_year_added_cny"))
    if total is not None and total >= 50 and compensation is not None:
        metrics["avg_compensation_cny_approx"] = ((compensation // total + 500) // 1000) * 1000
    return {key: value for key, value in metrics.items() if value is not None}


def _pct(value):
    return f"{round(value * 100):.0f}%"


def _report_url(report):
    return f"{CNINFO_STATIC}/{str(report.get('adjunct_url') or '').lstrip('/')}"


def build_fact_items(company_profile, report, fields, metrics):
    """组装 hiring 与 compensation_intensity 两条 T2 官方 fact；不做数据库 IO。"""
    year = int(report["year"])
    valid_until = f"{year + 2}-12-31"
    report_url = _report_url(report)
    payload = {**(fields or {}), **(metrics or {}), "report_url": report_url, "report_year": year}
    total = _to_number((fields or {}).get("employee_total"))
    items = []
    if total is not None:
        clauses = [f"在职员工 {total:,} 人"]
        if metrics.get("technical_ratio") is not None:
            clauses.append(f"技术人员占 {_pct(metrics['technical_ratio'])}")
        if metrics.get("bachelor_or_above_ratio") is not None:
            clauses.append(f"本科及以上占 {_pct(metrics['bachelor_or_above_ratio'])}")
        items.append({
            "dimension": "hiring", "grade": "fact", "origin": ORIGIN, "assertion": ASSERTION,
            "title": f"员工规模与构成 · 据 {year} 年年报",
            "content": f"据 {year} 年年报，" + "；".join(clauses) + "。",
            "payload": payload, "deidentified": True, "status": "active",
            "time_window": f"{year} 年年报口径", "valid_until": valid_until,
            "source": {"url": report_url, "publisher": "巨潮资讯网", "source_kind": SOURCE_KIND,
                       "excerpt": str((fields or {}).get("employee_excerpt") or "")[:300], "deidentified": True},
        })
    compensation = metrics.get("avg_compensation_cny_approx")
    if compensation is not None:
        amount_wan = f"{compensation / 10000:.1f}".rstrip("0").rstrip(".")
        items.append({
            "dimension": "compensation_intensity", "grade": "fact", "origin": ORIGIN, "assertion": ASSERTION,
            "title": f"人均薪酬（年报口径）· 据 {year} 年年报",
            "content": f"据 {year} 年年报应付职工薪酬倒推，人均约 {amount_wan} 万元/年（含公司承担的社保公积金，为会计计提口径，仅供量级参考）。",
            "payload": payload, "deidentified": True, "status": "active",
            "time_window": f"{year} 年年报口径", "valid_until": valid_until,
            "source": {"url": report_url, "publisher": "巨潮资讯网", "source_kind": SOURCE_KIND,
                       "excerpt": str((fields or {}).get("compensation_excerpt") or "")[:300], "deidentified": True},
        })
    return items


def existing_report_years(sb, company_id):
    """分页取已有年报条目，避免表增长后 PostgREST 静默截断。"""
    rows = db.fetch_all_rows(
        lambda: (sb.table("insight_items").select("id,payload")
                 .eq("company_id", company_id).eq("origin", ORIGIN)))
    years = set()
    for row in rows:
        payload = row.get("payload") or {}
        try:
            years.add(int(payload.get("report_year")))
        except (TypeError, ValueError):
            pass
    return years


def choose_latest_unseen_report(reports, seen_years):
    """最新可得年报若已写过则整家公司跳过；不回退下载旧年报。"""
    if not reports:
        return None
    latest = reports[0]
    return None if latest.get("year") in set(seen_years or ()) else latest


def _existing_item(sb, company_id, dimension):
    rows = db.fetch_all_rows(
        lambda: (sb.table("insight_items").select("id")
                 .eq("company_id", company_id).eq("dimension", dimension).eq("origin", ORIGIN)))
    return rows[0].get("id") if rows else None


def _write_source(sb, item_id, source):
    links = db.fetch_all_rows(
        lambda: sb.table("insight_item_sources").select("source_id").eq("item_id", item_id),
        order_key="source_id")
    if links:
        sb.table("insight_sources").update(source).eq("id", links[0]["source_id"]).execute()
        return
    source_id = str(uuid.uuid4())
    sb.table("insight_sources").insert({"id": source_id, **source}).execute()
    sb.table("insight_item_sources").insert({"item_id": item_id, "source_id": source_id}).execute()


def write_fact_items(sb, company_profile, items):
    """同公司/维度/origin 原地升级，且把年报来源行写入（或更新）关联来源。"""
    written = 0
    for fact in items:
        source = fact["source"]
        row = {key: value for key, value in fact.items() if key != "source"}
        row.update({"company_id": company_profile["id"], "last_verified_at": _now()})
        item_id = _existing_item(sb, company_profile["id"], fact["dimension"])
        if item_id:
            sb.table("insight_items").update(row).eq("id", item_id).execute()
        else:
            item_id = str(uuid.uuid4())
            sb.table("insight_items").insert({"id": item_id, **row}).execute()
        _write_source(sb, item_id, source)
        written += 1

    if not company_profile.get("headcount_band"):
        total = _to_number((items[0].get("payload") or {}).get("employee_total")) if items else None
        band = wikidata.headcount_band(total)
        if band:
            sb.table("company_profiles").update({"headcount_band": band}).eq("id", company_profile["id"]).execute()
    return written


def fetch_profiles(sb, company=""):
    rows = db.fetch_all_rows(
        lambda: sb.table("company_profiles").select("id,company,aliases,headcount_band"))
    if company:
        wanted = company.strip()
        rows = [row for row in rows if row.get("company") == wanted or wanted in (row.get("aliases") or [])]
    return rows


def fetch_stock_list(client):
    response = client.get(CN.SZSE_STOCK_URL, headers=UA, timeout=30)
    response.raise_for_status()
    data = response.json() or {}
    return data.get("stockList") if isinstance(data, dict) else []


def process_company(sb, client, profile, stock, dry_run=False):
    """单家公司至多查一次公告、下载一份最新 PDF；返回结果类别和实际写入数。"""
    reports = list_annual_reports(client, stock["zwjc"], stock["code"])
    if not reports:
        # 「查不到年报」与「最新年报已写过」必须分开计数：前者是接口/过滤出了问题，后者才是正常跳过。
        return "no_reports", 0
    report = choose_latest_unseen_report(reports, existing_report_years(sb, profile["id"]))
    if report is None:
        return "already_latest", 0
    pdf = download_pdf(client, report["adjunct_url"])
    if not pdf:
        return "failed", 0
    fields = parse_employee_section(pdf)
    if fields.get("parse_error") == "scanned_pdf":
        return "scanned_pdf", 0
    if fields.get("parse_error") == "employee_section_not_found":
        return "section_not_found", 0
    items = build_fact_items(profile, report, fields, derive_metrics(fields))
    if not items:
        return "section_not_found", 0
    return "parsed", 0 if dry_run else write_fact_items(sb, profile, items)


def main():
    parser = argparse.ArgumentParser(description="巨潮 A 股年报员工/薪酬官方事实")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--company", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not enabled():
        print("INSIGHT_ANNUAL_REPORT_ENABLED 未开启，跳过。")
        return

    started_at = _now()
    stat = {"checked": 0, "parsed": 0, "written": 0, "section_not_found": 0, "scanned_pdf": 0, "failed": 0, "no_reports": 0, "already_latest": 0}
    sb = db.get_supabase()
    with httpx.Client(headers=UA, follow_redirects=True, timeout=30) as client:
        try:
            stocks = fetch_stock_list(client)
        except Exception as exc:
            print(f"[annual-report] 股票列表失败: {type(exc).__name__}: {str(exc)[:140]}")
            stat["failed"] += 1
            stocks = []
        candidates = []
        for profile in fetch_profiles(sb, args.company):
            stock = CN.find_stock(stocks, profile.get("company"), profile.get("aliases"))
            if stock:
                candidates.append((profile, stock))
        candidates = candidates[:max(0, args.limit)]
        print(f"[annual-report] A 股候选 {len(candidates)} 家，dry_run={args.dry_run}")
        for index, (profile, stock) in enumerate(candidates):
            stat["checked"] += 1
            try:
                result, written = process_company(sb, client, profile, stock, args.dry_run)
                if result == "parsed":
                    stat["parsed"] += 1
                    stat["written"] += written
                elif result in stat:
                    stat[result] += 1
            except Exception as exc:  # 单家公司失败不拖垮整轮
                stat["failed"] += 1
                print(f"  [annual-report-err] {profile.get('company')}: {type(exc).__name__}: {str(exc)[:140]}")
            if index < len(candidates) - 1:
                time.sleep(random.uniform(1, 2))
    ops_runs.record_ops_run(
        sb, "annual_report", stat,
        status=ops_runs.status_from_counts(stat["checked"], stat["failed"]),
        started_at=started_at, finished_at=_now(),
    )
    print(f"[annual-report] {stat}")


if __name__ == "__main__":
    main()
