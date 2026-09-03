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
    # ⚠️ 与 JS 逐字同口径（tests/company-industry-cross-lang.test.js 跨语言对拍守卫）。
    # 英文词一律带前词边界：不加会让 "express" 吃掉 American Express、"tech" 吃掉 BioNTech/Genentech、
    # "capital" 吃掉 CapitaLand。中文没有词边界概念，靠 COMPANY_OVERRIDES 的最长匹配兜。
    ("金融", re.compile(r"银行|证券|保险|基金|信托|期货|资管|财险|寿险|金融|支付|消费金融|小额贷|\bbank|\bsecurities\b|\binsurance\b|\bcapital\b", re.I)),
    ("医疗/医药", re.compile(r"医药|制药|药业|药品|生物医药|生物科技|医疗|医院|健康|基因|诊断|器械|\bpharma|\bbiotech\b|\bmedical\b|\bhealth", re.I)),
    ("汽车/出行", re.compile(r"汽车|整车|车业|新能源车|乘用车|商用车|车联网|出行|\bmotors\b|\bautomotive\b", re.I)),
    ("能源/化工", re.compile(r"能源|电力|电网|石油|石化|化工|化学|新能源|光伏|风电|储能|电池|燃气|煤业|核电|\benergy\b|\bpower\b|\bchemical|\bpetro", re.I)),
    ("物流/供应链", re.compile(r"物流|快递|供应链|仓储|货运|运输|冷链|\blogistics\b|\bexpress\b|\bsupply\s*chain\b", re.I)),
    ("地产/建筑", re.compile(r"地产|置业|房产|建筑|建设|建工|工程局|装饰|幕墙|\breal\s*estate\b|\bconstruction\b|\bpropert", re.I)),
    ("教育", re.compile(r"教育|学校|培训|学院|课程|留学|\beducation\b|\bacademy\b", re.I)),
    ("传媒/文娱", re.compile(r"传媒|影视|文化|娱乐|院线|音乐|动漫|文娱|出版|\bmedia\b|\bentertainment\b", re.I)),
    ("消费/零售", re.compile(r"食品|饮料|乳业|乳品|零售|商超|百货|便利店|美妆|化妆品|日化|服饰|服装|鞋业|家居|家电|餐饮|连锁|消费|快消|\bretail\b|\bconsumer\b|\bfoods?\b|\bbeverage\b", re.I)),
    ("制造/工业", re.compile(r"制造|机械|重工|工业|装备|设备|电子|半导体|芯片|集成电路|材料|钢铁|有色|精密|模具|纺织|轻工|\bmanufactur|\bindustrial\b|\belectronics\b|\bsemiconductor\b", re.I)),
    # ⚠️「科技」「智能」是中文公司名的通用后缀，各行各业都在用，拿它们判互联网 live 实测
    # 误判 162 家 / 10,757 个在招岗。已移除，判不出（None）走放行，不误杀。
    ("互联网/科技", re.compile(r"互联网|网络|信息技术|软件|数码|大数据|云计算|游戏|网游|人工智能|物联网|\btech\b|\bsoftware\b|\bdigital\b|\binternet\b|\bai\b|\bcloud\b", re.I)),
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


def _override_hits(text: str, key: str) -> bool:
    """override 单条是否命中。纯 ASCII 的 key 必须成词，中文 key 用 substring。
    与 JS overrideHits 同口径：不加词边界的话 "abb"(ABB) 会吃掉 "雅培 Abbott" 的单词内部。"""
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&-]*", key):
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(key), text, re.I) is not None
    return key in text


def classify_company_industry(company) -> Optional[str]:
    """公司 → 行业类目（或 None=判不出）。overrides 优先于关键词规则。

    ⚠️ overrides 取**最长**命中，不是第一个命中：短品牌名会吃掉带它的长公司名
    （"京东"吃"京东方"、"网易"吃"网易云音乐"、"腾讯"吃"腾讯音乐"）。与 JS classifyCompanyIndustry 同口径。
    """
    text = _normalize_company(company)
    if not text:
        return None
    best_key, best_cat = None, None
    for name, cat in COMPANY_OVERRIDES:
        key = _normalize_company(name)
        if not _override_hits(text, key):
            continue
        if best_key is None or len(key) > len(best_key):
            best_key, best_cat = key, cat
    if best_cat:
        return best_cat
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
