"""必投清单共享读取：Python 爬虫复用前端北极星清单，避免 TS/Python 双份口径漂移。"""
import json
import sys
from pathlib import Path

MUST_APPLY_JSON = Path(__file__).resolve().parents[1] / "lib" / "must-apply-list.json"


def patterns():
    """返回 jobs.company ILIKE 模式；读取失败时 fail-open，探活主流程不能被清单文件拖垮。"""
    try:
        with MUST_APPLY_JSON.open("r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        print(f"⚠️ [must_apply] 读取必投清单失败，已跳过优先倾斜：{e}", file=sys.stderr)
        return []
    return [r.get("pattern") for r in rows if isinstance(r, dict) and isinstance(r.get("pattern"), str)]


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
