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
        if (
            isinstance(industry, str)
            and not industry.startswith("_")
            and isinstance(companies, list)
        )
    }


def version() -> str:
    """返回清单版本元数据；旧清单没有版本时保持可读。"""
    rows = _load_rows()
    value = rows.get("_version") if isinstance(rows, dict) else None
    return value if isinstance(value, str) and value.strip() else "unversioned"


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
        if (
            isinstance(industry, str)
            and not industry.startswith("_")
            and isinstance(companies, list)
        )
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


def resolve_owner(company_name: str, names) -> str:
    """`sources.company` 这一行**归属于必投清单里的哪一家**（最长名优先）。返回清单里的规范名，或 ""。

    为何不能用朴素子串：这个函数服务的是**事实接地**（拿公司自有官方域名去核校招日期），
    张冠李戴的代价是「把 A 公司的校招时间挂到 B 公司头上」——比覆盖统计错一格严重得多。
      ❌ `%京东%` 会把**京东方（BOE）** 也算成京东 → 用 boe.com 给京东的日期做接地。
      ❌ 现成的 `company_name_match.company_name_matches("京东方","京东")` 也返回 True
         （它防的是另一种坑：token 不在开头，如「北京华晋中通电力」≠ 中通）。
    规则：**清单名必须是库里名字的子串**，命中多个时**最长的清单名胜出**。
      京东方 同时命中「京东」「京东方」→ 判给京东方（不会去给京东做接地）
      「腾讯音乐 TME」同时命中「腾讯」「腾讯音乐」→ 判给腾讯音乐
      「中国工商银行」命中「工商银行」→ 判给工商银行
    ⚠️ **只认这一个方向**（清单名 ⊂ 库里名）。曾经写成双向包含，结果库里的「京东」
    被判给了更长的「京东科技」——反向那条既没用（实际错配全是库里名字更长）又有害。
    """
    low = str(company_name or "").strip().lower()
    if not low:
        return ""
    best = ""
    for raw in names or []:
        token = str(raw or "").strip()
        if token and token.lower() in low and len(token) > len(best):
            best = token
    return best


def sources_for(target: str, rows, names) -> list:
    """从 sources 行里挑出**确实属于 target 这家**的行（用 resolve_owner 判归属）。

    调用方给 `names` = 必投清单全部规范名（`by_industry()` 里的 name），这样「更长的那家」
    才有机会把行抢走。names 传不全 = 防不住张冠李戴，故设为必传。
    """
    out = []
    for row in rows or []:
        if resolve_owner((row or {}).get("company"), names) == target:
            out.append(row)
    return out


def all_names() -> list:
    """必投清单里全部公司规范名（国内 + 海外），供 resolve_owner / sources_for 用。"""
    seen, names = set(), []
    for bucket in (by_industry(), overseas_by_industry()):
        for _industry, entries in (bucket or {}).items():
            for entry in entries or []:
                name = (entry.get("name") or "").strip() if isinstance(entry, dict) else ""
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
    return names
