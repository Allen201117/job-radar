"""公司 → 行业 确定性分类器（与 lib/company-industry.js 同口径）。

爬虫端「行业-公司-岗位」跨行业门用：发现/刷新时按用户目标行业收窄，丢弃跨行业岗。
- 公司表（COMPANY_OVERRIDES）是**唯一数据源**，活在 JS（lib/company-industry.js），
  本模块读其生成产物 lib/data/company-industry-overrides.json（避免两份漂移；
  改 JS 后跑 `node scripts/gen-company-overrides-json.js` 重生成，sync 测试守卫）。
- 关键词规则 / 用户行业别名 / 门逻辑 按 china_keyword_expansion.py 惯例手镜像 JS（小、低频）。
"""
import json
import os
import re
from typing import List, Optional, Set

_OVERRIDES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "lib", "data", "company-industry-overrides.json"
)

# 须与 lib/industries.ts 的 INDUSTRIES 真行业部分同口径（不含 央国企/其他）。
INDUSTRY_CATEGORIES = [
    "互联网/科技", "金融", "消费/零售", "制造/工业", "汽车/出行",
    "医疗/医药", "能源/化工", "地产/建筑", "物流/供应链", "传媒/文娱", "教育",
]


def _load_overrides():
    try:
        with open(_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            return [(str(name), str(cat)) for name, cat in json.load(f)]
    except (OSError, ValueError):
        return []


COMPANY_OVERRIDES = _load_overrides()

# 行业关键词规则（公司名含该词 → 行业）。顺序敏感，与 JS INDUSTRY_KEYWORD_RULES 同口径。
_INDUSTRY_KEYWORD_RULES = [
    ("金融", re.compile(r"银行|证券|保险|基金|信托|期货|资管|财险|寿险|金融|支付|消费金融|小额贷|bank|securities|insurance|capital", re.I)),
    ("医疗/医药", re.compile(r"医药|制药|药业|药品|生物医药|生物科技|医疗|医院|健康|基因|诊断|器械|pharma|biotech|medical|health", re.I)),
    ("汽车/出行", re.compile(r"汽车|整车|车业|新能源车|乘用车|商用车|车联网|出行|motors|automotive", re.I)),
    ("能源/化工", re.compile(r"能源|电力|电网|石油|石化|化工|化学|新能源|光伏|风电|储能|电池|燃气|煤业|核电|energy|power|chemical|petro", re.I)),
    ("物流/供应链", re.compile(r"物流|快递|供应链|仓储|货运|运输|冷链|logistics|express|supply\s*chain", re.I)),
    ("地产/建筑", re.compile(r"地产|置业|房产|建筑|建设|建工|工程局|装饰|幕墙|real\s*estate|construction|properties", re.I)),
    ("教育", re.compile(r"教育|学校|培训|学院|课程|留学|education|academy", re.I)),
    ("传媒/文娱", re.compile(r"传媒|影视|文化|娱乐|院线|音乐|动漫|文娱|出版|media|entertainment", re.I)),
    ("消费/零售", re.compile(r"食品|饮料|乳业|乳品|零售|商超|百货|便利店|美妆|化妆品|日化|服饰|服装|鞋业|家居|家电|餐饮|连锁|消费|快消|retail|consumer|foods?|beverage", re.I)),
    ("制造/工业", re.compile(r"制造|机械|重工|工业|装备|设备|电子|半导体|芯片|集成电路|材料|钢铁|有色|精密|模具|纺织|轻工|manufactur|industrial|electronics|semiconductor", re.I)),
    ("互联网/科技", re.compile(r"互联网|科技|网络|信息技术|软件|数码|智能|大数据|云计算|游戏|网游|人工智能|物联网|tech|software|digital|internet|\bai\b|cloud", re.I)),
]

# 用户自填行业（自由文本）→ 规范类目。与 JS USER_INDUSTRY_ALIASES 同口径。
_USER_INDUSTRY_ALIASES = [
    ("互联网/科技", re.compile(r"互联网|科技|信息技术|软件|计算机|it|tech|游戏|人工智能|\bai\b|大数据|云", re.I)),
    ("金融", re.compile(r"金融|银行|证券|保险|基金|投资|fintech|finance", re.I)),
    ("消费/零售", re.compile(r"消费|零售|快消|fmcg|电商|食品|饮料|美妆|服装|retail|consumer", re.I)),
    ("制造/工业", re.compile(r"制造|工业|机械|电子|半导体|芯片|材料|硬件|manufactur|industrial", re.I)),
    ("汽车/出行", re.compile(r"汽车|车|出行|新能源车|automotive", re.I)),
    ("医疗/医药", re.compile(r"医疗|医药|生物|制药|健康|器械|pharma|bio|medical|health", re.I)),
    ("能源/化工", re.compile(r"能源|电力|化工|化学|新能源|光伏|电池|energy|chemical", re.I)),
    ("地产/建筑", re.compile(r"地产|房地产|建筑|建设|工程|real\s*estate|construction", re.I)),
    ("物流/供应链", re.compile(r"物流|供应链|快递|运输|logistics|supply", re.I)),
    ("传媒/文娱", re.compile(r"传媒|文娱|影视|文化|娱乐|内容|media|entertainment", re.I)),
    ("教育", re.compile(r"教育|培训|edu", re.I)),
]


def _normalize_company(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def classify_company_industry(company) -> Optional[str]:
    """公司 → 行业类目（或 None=判不出）。overrides(substring) 优先于关键词规则。"""
    text = _normalize_company(company)
    if not text:
        return None
    for name, cat in COMPANY_OVERRIDES:
        if _normalize_company(name) in text:
            return cat
    for cat, rule in _INDUSTRY_KEYWORD_RULES:
        if rule.search(text):
            return cat
    return None


def canonicalize_user_industry(value) -> Optional[str]:
    text = _normalize_company(value)
    if not text:
        return None
    if value in INDUSTRY_CATEGORIES:
        return value
    for cat, rule in _USER_INDUSTRY_ALIASES:
        if rule.search(text):
            return cat
    return None


def user_target_industry_categories(industries) -> Set[str]:
    out: Set[str] = set()
    for raw in industries or []:
        cat = canonicalize_user_industry(raw)
        if cat:
            out.add(cat)
    return out


def job_industry_allowed(company, industries) -> bool:
    """跨行业门：放行当 用户没填可识别行业 / 岗位行业判不出 / 行业 ∈ 用户目标集合；
    拦截仅当 用户有明确目标行业 且 岗位行业已知 且 不在目标集合内。与 JS jobIndustryAllowed 同口径。"""
    targets = user_target_industry_categories(industries)
    if not targets:
        return True
    job_cat = classify_company_industry(company)
    if not job_cat:
        return True
    return job_cat in targets
