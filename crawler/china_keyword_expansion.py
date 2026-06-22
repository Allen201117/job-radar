"""中文↔英文求职关键词双语扩展 + 匹配（crawler 端）。

这是 lib/china-keyword-expansion.js 同义词组逻辑的 Python 移植，目的是让**发现端**
(discovery.filter_raw_jobs) 的关键词匹配与**前端看板** (jobMatchesChinaKeyword) 同口径：
中文发现关键词（如「算法」）也能命中英文外企岗（"Machine Learning Engineer"），反之亦然。

两边逻辑必须保持一致：改这里时同步 lib/china-keyword-expansion.js（及其单测）。
"""
import re
from typing import List

# 与 lib/china-keyword-expansion.js 的 CHINA_KEYWORD_GROUPS 一一对应（21 组）。
CHINA_KEYWORD_GROUPS: List[List[str]] = [
    ["算法", "机器学习", "深度学习", "人工智能", "AI", "artificial intelligence",
     "machine learning", "deep learning", "algorithm", "ml", "llm", "大模型",
     "nlp", "自然语言处理", "computer vision", "cv", "计算机视觉"],
    ["数据分析", "商业分析", "数据运营", "数据科学", "BI", "SQL", "Python",
     "data analyst", "data scientist", "business analyst", "analytics"],
    ["数据工程", "大数据", "data engineer", "data engineering", "etl", "data platform"],
    ["产品经理", "产品", "AI 产品", "数据产品", "策略产品", "product manager",
     "product", "PM", "AI product", "po"],
    ["前端", "web 前端", "frontend", "front end", "front-end", "react", "vue",
     "javascript", "客户端", "ios", "android", "客户端开发"],
    ["后端", "服务端", "backend", "back end", "back-end", "服务器开发", "java",
     "golang", "go 开发", "全栈", "full stack", "fullstack"],
    ["测试", "质量", "qa", "test engineer", "quality assurance", "测试开发",
     "sdet", "自动化测试"],
    ["运维", "sre", "devops", "site reliability", "基础架构", "infrastructure",
     "平台工程", "platform engineer"],
    ["安全", "信息安全", "网络安全", "security", "cybersecurity", "security engineer"],
    ["设计", "ui", "ux", "交互设计", "视觉设计", "designer", "ui designer",
     "ux designer", "product designer"],
    ["运营", "用户运营", "内容运营", "增长", "operations", "growth", "user operations"],
    ["市场", "营销", "品牌", "marketing", "brand", "growth marketing", "市场营销"],
    ["销售", "商务", "bd", "sales", "business development", "account manager", "客户经理"],
    ["财务", "会计", "审计", "finance", "accounting", "audit", "financial analyst", "财务分析"],
    ["人力", "人力资源", "招聘", "hr", "human resources", "recruiter", "recruiting", "talent"],
    ["法务", "法律", "合规", "legal", "compliance", "counsel"],
    ["供应链", "采购", "物流", "supply chain", "procurement", "logistics", "operations manager"],
    ["硬件", "嵌入式", "芯片", "电子", "hardware", "embedded", "firmware", "chip", "asic", "fpga"],
    ["投研", "行业研究", "股票研究", "固收", "量化", "investment research",
     "equity research", "quant"],
    ["管培生", "管理培训生", "校招", "应届", "graduate program", "campus recruitment",
     "new grad", "graduate"],
    ["实习", "暑期实习", "日常实习", "intern", "internship"],
]

_SPLIT_RE = re.compile(r"[\s,，、/|;；]+")
_SHORT_LATIN_RE = re.compile(r"[a-z0-9.+#-]{1,3}")


def normalize_for_match(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def split_keyword_terms(value) -> List[str]:
    raw = str(value or "").strip()
    parts = [p for p in (t.strip() for t in _SPLIT_RE.split(raw)) if p]
    return [raw, *parts]


def contains_term(haystack, term: str) -> bool:
    """短的纯拉丁缩写（≤3，如 ai/ml/pm/ui/hr）用词边界匹配，避免 maintain→ai、google→go
    这类误匹配；其余（CJK 或较长词）走普通子串包含。haystack 视为已 normalize_for_match。"""
    h = str(haystack or "")
    t = normalize_for_match(term)
    if not t:
        return False
    if _SHORT_LATIN_RE.fullmatch(t):
        escaped = re.escape(t)
        return re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", h) is not None
    return t in h


def expand_china_keyword_terms(query) -> List[str]:
    """把查询扩展成同义词集合：命中某同义词组则纳入该组全部词（中英双语）。空查询返回 []。"""
    raw = str(query or "").strip()
    if not raw:
        return []
    normalized = normalize_for_match(raw)
    terms = set(split_keyword_terms(raw))
    for group in CHINA_KEYWORD_GROUPS:
        if any(contains_term(normalized, term) for term in group):
            for term in group:
                terms.add(term)
                terms.add(normalize_for_match(term))
    return [t for t in (str(x).strip() for x in terms) if t]


def query_matches(haystack, query) -> bool:
    """haystack（任意可搜索文本）是否命中查询的双语扩展。空查询视为命中。
    注意：这是宽 OR 的旧口径（不区分字段/职能）。发现端精准过滤请用 job_matches()。"""
    terms = [normalize_for_match(t) for t in expand_china_keyword_terms(query)]
    if not terms:
        return True
    h = normalize_for_match(haystack)
    return any(contains_term(h, term) for term in terms)


# ---------------------------------------------------------------------------
# 字段感知 + 职能门匹配（与 lib/china-keyword-expansion.js jobMatchesChinaKeyword 同口径）
# 治「pm→算法」跨职能污染：拿同义词撞整段 JD 正文 → 裸泛词"产品"几乎每篇研发岗 JD 都有 → 误召。
# 修法：标题命中始终算；正文命中须过「职能门」（岗位职能 ∈ 查询职能）；工程师/软件 这类泛词只匹配标题。
# 改这里时同步 lib/china-keyword-expansion.js。
# ---------------------------------------------------------------------------

# 各组（按索引，对应上面 21 组）→ 职能桶；None = 无干净职能（招聘类型/投研），不参与职能门。
KEYWORD_GROUP_FUNCTIONS = [
    "研发",   # 0  算法/AI
    "数据",   # 1  数据分析
    "数据",   # 2  数据工程
    "产品",   # 3  产品
    "研发",   # 4  前端
    "研发",   # 5  后端
    "研发",   # 6  测试
    "研发",   # 7  运维
    "研发",   # 8  安全
    "设计",   # 9  设计
    "运营",   # 10 运营
    "市场",   # 11 市场
    "销售",   # 12 销售
    "职能",   # 13 财务
    "职能",   # 14 人力
    "职能",   # 15 法务
    "供应链",  # 16 供应链
    "研发",   # 17 硬件
    None,     # 18 投研
    None,     # 19 管培/校招
    None,     # 20 实习
]

# 职能粗分类规则（与 JS JOB_FUNCTION_RULES 同口径，顺序敏感：产品经理优先于"含算法字样"）。
_JOB_FUNCTION_RULES = [
    ("产品", re.compile(r"产品经理|产品运营|产品策划|产品负责人|产品总监|产品专家|product\s*manager|product\s*owner|\bpm\b|\bpo\b", re.I)),
    ("设计", re.compile(r"视觉设计|交互设计|ui\s*设计|ux|平面设计|设计师|designer", re.I)),
    ("数据", re.compile(r"数据分析|数据科学|数据工程|大数据|数据挖掘|data\s*(analyst|scien|engineer)|\bbi\b|商业分析", re.I)),
    ("研发", re.compile(r"工程师|研发|开发|算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|engineer|developer|\bsde\b|\bsre\b|programmer|software|技术", re.I)),
    ("运营", re.compile(r"用户运营|内容运营|运营|增长|operations|growth", re.I)),
    ("市场", re.compile(r"市场|营销|品牌|公关|marketing|brand|\bpr\b", re.I)),
    ("销售", re.compile(r"销售|商务拓展|\bbd\b|sales|客户经理|business\s*development", re.I)),
    ("供应链", re.compile(r"供应链|采购|物流|仓储|supply\s*chain|procurement|logistics", re.I)),
    ("职能", re.compile(r"人力资源|招聘|\bhr\b|财务|会计|审计|法务|法律|合规|行政|finance|legal|recruit|human\s*resources", re.I)),
]

# function=null 的跨语言泛锚点：只在标题命中才算，绝不撞正文（职能门覆盖不到这类）。
TITLE_ONLY_ANCHORS = {normalize_for_match(t) for t in
                      ["工程师", "engineer", "研发", "developer", "软件", "software"]}

# 非软件「工程/工业」领域硬标记（与 JS NON_SOFTWARE_ENG_DOMAIN 同口径）：机械/工艺/化工/材料/土木…
# 这些岗常含「开发/技术/工程师」等泛词，会被研发规则吃进「软件研发」桶，但属制造/工业工程领域，
# 不是软件研发。不隔离则被「算法/AI/数据」等映射到研发职能的查询经职能门/相关层误召。
_NON_SOFTWARE_ENG_DOMAIN = re.compile(
    r"机械|机电|机加|钣金|工艺|化工|化学|材料|冶金|铸造|锻造|焊接|焊工|模具|注塑|液压|气动|数控|机床|刀具|"
    r"工装|夹具|热处理|土木|结构工程|岩土|暖通|给排水|管道|强电|工业工程|生产工艺|制造工艺|工艺技术|纺织|"
    r"印染|涂装|总装|冲压|车身|底盘|发动机|动力总成|整车|工业自动化|机械自动化"
)
# 软件/IT/算法信号（与 JS SOFTWARE_ENG_SIGNAL 同口径）：命中其一则即使带工业标记仍判软件研发
#（机器人/自动驾驶/嵌入式软件等交叉岗）。故意排除泛词 研发/开发/技术/工程师 及过常见的「数据」。
_SOFTWARE_ENG_SIGNAL = re.compile(
    r"软件|software|算法|algorithm|前端|frontend|front[\s-]?end|后端|backend|back[\s-]?end|全栈|"
    r"full[\s-]?stack|客户端|服务端|嵌入式|固件|firmware|测试开发|自动化测试|sdet|运维|sre|devops|"
    r"架构师|代码|编程|程序员|programmer|\bjava\b|python|golang|c\+\+|c#|\.net|javascript|typescript|"
    r"\breact\b|\bvue\b|机器学习|machine\s*learning|深度学习|deep\s*learning|\bml\b|\bnlp\b|大模型|"
    r"\bllm\b|\bai\b|人工智能|计算机视觉|\bcv\b|系统开发|平台开发|web|\bapp\b|小程序|数据库|database|"
    r"\bsql\b|云计算|区块链",
    re.I,
)


def classify_job_function(title="", job_type="", summary="") -> str:
    text = normalize_for_match(" ".join(str(x) for x in (title, job_type, summary) if x))
    if not text:
        return "其他"
    for name, rule in _JOB_FUNCTION_RULES:
        if rule.search(text):
            # 领域降级门：仅靠泛词落入「研发」、却带非软件工业领域硬标记、且无软件信号 → 归「其他」，
            # 不塌进软件研发桶（杜绝「算法/AI/数据」类查询经职能门误召，与 JS 同口径）。
            if (name == "研发"
                    and _NON_SOFTWARE_ENG_DOMAIN.search(text)
                    and not _SOFTWARE_ENG_SIGNAL.search(text)):
                continue
            return name
    return "其他"


def _matched_group_indexes(query) -> List[int]:
    normalized = normalize_for_match(query)
    return [i for i, group in enumerate(CHINA_KEYWORD_GROUPS)
            if any(contains_term(normalized, term) for term in group)]


def query_functions(query) -> set:
    """查询命中的概念组对应职能集合（去掉 None）。"""
    return {KEYWORD_GROUP_FUNCTIONS[i] for i in _matched_group_indexes(query)
            if KEYWORD_GROUP_FUNCTIONS[i]}


def keyword_match_units(query) -> List[List[str]]:
    """把查询拆成概念单元：命中的同义词组各成一单元（OR），散词各自成单元；单元间 AND。"""
    raw = str(query or "").strip()
    if not raw:
        return []
    normalized = normalize_for_match(raw)
    units: List[List[str]] = []
    for group in CHINA_KEYWORD_GROUPS:
        if any(contains_term(normalized, term) for term in group):
            units.append([normalize_for_match(t) for t in group])
    for lit in (normalize_for_match(t) for t in split_keyword_terms(raw)[1:]):
        if not lit:
            continue
        covered = any(any(lit in t or t in lit for t in u) for u in units)
        if not covered:
            units.append([lit])
    return units


def job_matches(title, body, query) -> bool:
    """岗位是否命中关键词（字段感知 + 职能门）。空查询视为命中。
    title = 岗位标题（权威信号）；body = 标题外可搜索文本（公司/地点/类型/摘要/薪资）。
    标题命中始终算；正文命中须 非泛锚点 且 过职能门（岗位职能 ∈ 查询职能，查询无职能则放行）。"""
    units = keyword_match_units(query)
    if not units:
        return True
    title_text = normalize_for_match(title)
    body_text = normalize_for_match(body)
    q_fns = query_functions(query)
    body_allowed = (not q_fns) or (classify_job_function(title_text, "", body_text) in q_fns)
    for unit in units:
        if not any(
            contains_term(title_text, term)
            or (body_allowed and term not in TITLE_ONLY_ANCHORS and contains_term(body_text, term))
            for term in unit
        ):
            return False
    return True
