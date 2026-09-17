"""sources.industry 自由写法 → sources.industry_group 归一表。

唯一数据源是 `lib/industry-taxonomy.json`（前端 `lib/industry-taxonomy.ts` 读同一份文件），
两端一致性由 `tests/industry-taxonomy-cross-lang.test.js` 全量对拍守住（433 条全跑，不抽样）。
**改映射只改那个 JSON，不要在这里另写一份规则/表**——那正是 company-industry.js /
company_industry.py 两端各写一份、跑着跑着就漂了的坑（见 tests/company-industry-cross-lang.test.js
的门禁说明）。

设计取舍（详见 industry-taxonomy.json 的 `_boundaryNotes`）：
- `groups` 与 `lib/company-industry.js` 的 INDUSTRY_CATEGORIES / `lib/must-apply-list.json`
  的行业键同一空间（11 个），不新造分类体系。
- `mapping` 是逐条人工审定的显式表，不是运行时关键词猜测——sources.industry 出现一个
  表里没有的新写法时，`classify_industry` 返回 None（不是 'other'），调用方必须显式决定
  怎么处理，不会被静默分进某个桶。
- `sources.industry` 本身为 NULL/空 → 返回 None（不是 'other'）：'other' 表示「有标签但
  不属于这 11 个行业」，NULL 表示「压根没打标签」，两者语义不同，混为一谈会污染
  「按行业看校招覆盖」的分母。
"""
import json
from pathlib import Path

TAXONOMY_JSON = Path(__file__).resolve().parents[1] / "lib" / "industry-taxonomy.json"

_cache = None


def _load():
    global _cache
    if _cache is None:
        with TAXONOMY_JSON.open("r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def version() -> str:
    data = _load()
    value = data.get("_version")
    return value if isinstance(value, str) and value.strip() else "unversioned"


def groups() -> list:
    """11 个行业组，顺序与 lib/company-industry.js 的 INDUSTRY_CATEGORIES 一致。"""
    return list(_load().get("groups") or [])


def other_group() -> str:
    return _load().get("otherGroup", "other")


def mapping() -> dict:
    """{sources.industry 原始写法: industry_group}，433 条全量显式表。"""
    return dict(_load().get("mapping") or {})


def classify_industry(raw):
    """sources.industry 原始写法 → industry_group；查不到 / 空值一律返回 None。

    None 的两种成因调用方要分清：
    1. raw 本身为空 —— 这个 source 压根没打行业标签；
    2. raw 有值但不在 mapping 里 —— 出现了没见过的新写法，需要人工补录 mapping，
       **不许**在这里猜一个关键词规则自动兜底（历史上这类"顺手猜一下"最后都变成了
       两套互相打架的分类口径，见 crawler/company_industry.py 的教训）。
    """
    if not isinstance(raw, str):
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return mapping().get(trimmed)
