"""必投清单共享读取：Python 爬虫复用前端北极星清单，避免 TS/Python 双份口径漂移。"""
import json
import sys
from pathlib import Path

MUST_APPLY_JSON = Path(__file__).resolve().parents[1] / "lib" / "must-apply-list.json"
OVERSEAS_MUST_APPLY_JSON = Path(__file__).resolve().parents[1] / "lib" / "must-apply-list-overseas.json"


def _load_rows():
    """读取必投清单；读取失败时 fail-open，探活主流程不能被清单文件拖垮。"""
    try:
        with MUST_APPLY_JSON.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ [must_apply] 读取必投清单失败，已跳过优先倾斜：{e}", file=sys.stderr)
        return None


def _load_overseas_rows():
    """读取海外必投清单；失败时不影响国内探活路径。"""
    try:
        with OVERSEAS_MUST_APPLY_JSON.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ [must_apply] 读取海外必投清单失败，已跳过海外优先倾斜：{e}", file=sys.stderr)
        return None


def _unique_patterns(rows):
    """按首次出现顺序提取有效 ILIKE 模式。"""
    out, seen = [], set()
    for row in rows:
        pattern = row.get("pattern") if isinstance(row, dict) else None
        if isinstance(pattern, str) and pattern not in seen:
            seen.add(pattern)
            out.append(pattern)
    return out


def by_industry() -> dict[str, list[dict]]:
    """按行业返回必投公司；旧数组清单或读取失败时返回空字典。"""
    rows = _load_rows()
    if not isinstance(rows, dict):
        return {}
    return {
        industry: [row for row in companies if isinstance(row, dict)]
        for industry, companies in rows.items()
        if isinstance(industry, str) and isinstance(companies, list)
    }


def patterns_for_industries(industries) -> list[str]:
    """返回指定行业并集的 ILIKE 模式；空值等价于全行业。"""
    grouped = by_industry()
    if not industries:
        selected = grouped.values()
    else:
        wanted = {industries} if isinstance(industries, str) else set(industries)
        selected = (companies for industry, companies in grouped.items() if industry in wanted)
    return _unique_patterns(row for companies in selected for row in companies)


def patterns():
    """返回全行业 jobs.company ILIKE 模式；兼容旧数组清单。"""
    rows = _load_rows()
    if isinstance(rows, list):
        return _unique_patterns(rows)
    if not isinstance(rows, dict):
        return []
    return _unique_patterns(row for companies in rows.values() if isinstance(companies, list)
                            for row in companies)


def overseas_by_industry() -> dict[str, list[dict]]:
    """按行业返回海外必投公司（含 name/pattern）；读取失败或旧数组形状时返回空字典。"""
    rows = _load_overseas_rows()
    if not isinstance(rows, dict):
        return {}
    return {
        industry: [row for row in companies if isinstance(row, dict)]
        for industry, companies in rows.items()
        if isinstance(industry, str) and isinstance(companies, list)
    }


def overseas_patterns():
    """返回海外必投清单全行业 ILIKE 模式；读取失败时 fail-open。"""
    rows = _load_overseas_rows()
    if isinstance(rows, list):
        return _unique_patterns(rows)
    if not isinstance(rows, dict):
        return []
    return _unique_patterns(row for companies in rows.values() if isinstance(companies, list)
                            for row in companies)


def all_patterns():
    """返回国内与海外必投模式的并集，保留首次出现顺序。"""
    return _unique_patterns([{"pattern": pattern} for pattern in patterns() + overseas_patterns()])


def match_company_against_patterns(name: str, pats) -> bool:
    if not name:
        return False
    low = str(name).lower()
    for pattern in pats or []:
        token = str(pattern).replace("%", "").strip().lower()
        if token and token in low:
            return True
    return False


def match_company(name: str) -> bool:
    return match_company_against_patterns(name, patterns())
