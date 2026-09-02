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
    ("产品", re.compile(r"产品经理|产品策划|产品负责人|产品总监|产品专家|product\s*manager|product\s*owner", re.I)),
    # PM/PO 在英文标题里还会表示上午下午、预防性保养等，故意不收裸 \bpm\b；也不收「工程项目」等泛词。
    ("项目管理", re.compile(r"项目经理|项目管理|项目主管|项目总监|项目负责人|交付经理|交付总监|\bpmo\b|project\s*manager|program\s*manager|delivery\s*manager|technical\s*program\s*manager|\btpm\b", re.I)),
    ("设计", re.compile(r"视觉设计|交互设计|ui\s*设计|ux|平面设计|设计师|designer", re.I)),
    ("数据", re.compile(r"数据分析|数据科学|数据工程|大数据|数据挖掘|data\s*(analyst|scien|engineer)|\bbi\b|商业分析", re.I)),
    ("研发", re.compile(r"算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|\bsde\b|\bsre\b|programmer|software|软件", re.I)),
    # 泛工程后缀：与 JS 一样只在没有具体职能词时才兜底，避免「Data Engineer」被工程师抢成研发。
    ("研发", re.compile(r"工程师|研发|开发|技术|engineer|developer", re.I), True),
    ("运营", re.compile(r"用户运营|内容运营|运营|增长|operations|growth", re.I)),
    ("市场", re.compile(r"市场|营销|品牌|公关|marketing|brand|\bpr\b", re.I)),
    ("销售", re.compile(r"销售|商务拓展|\bbd\b|sales|客户经理|business\s*development", re.I)),
    ("供应链", re.compile(r"供应链|采购|物流|仓储|supply\s*chain|procurement|logistics", re.I)),
    ("职能", re.compile(r"人力资源|招聘|\bhr\b|财务|会计|审计|法务|法律|合规|行政|finance|legal|recruit|human\s*resources", re.I)),
]

# 与 JS BODY_FALLBACK_BLOCKED 对齐：研发的「技术/开发」、项目管理的「项目管理经验」在 JD 正文里
# 都是万能套话。正文判出它们等于没判，必须退回标题结论，不能把标题未说明职能的岗批量误标。
_BODY_FALLBACK_BLOCKED = {"研发", "项目管理"}

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


def _run_function_rules(text, prefer_last, use_generic):
    """跑一轮具体词或泛工程词；标题取最靠后命中，正文按规则表顺序。"""
    best = None
    for index, item in enumerate(_JOB_FUNCTION_RULES):
        name, rule = item[:2]
        is_generic = bool(item[2]) if len(item) > 2 else False
        if is_generic != use_generic:
            continue
        # 领域降级门：仅靠泛词落入「研发」、却带非软件工业领域硬标记、且无软件信号 → 归「其他」，
        # 不塌进软件研发桶（杜绝「算法/AI/数据」类查询经职能门误召，与 JS 同口径）。
        if (name == "研发"
                and _NON_SOFTWARE_ENG_DOMAIN.search(text)
                and not _SOFTWARE_ENG_SIGNAL.search(text)):
            continue
        if not prefer_last:
            if rule.search(text):
                return name
            continue
        matches = list(rule.finditer(text))
        if not matches:
            continue
        match = matches[-1]
        candidate = (match.end(), len(match.group(0)), index, name)
        # 结束位置靠后优先；同位置取更长；再同长才保留规则表更靠前的规则。
        if (best is None
                or candidate[0] > best[0]
                or (candidate[0] == best[0] and candidate[1] > best[1])):
            best = candidate
    return best[3] if best else None


def _classify_function_text(text, prefer_last=False) -> str:
    """对一段已 normalize 的文本跑职能规则（含非软件工业领域降级门）。判不出返回 "其他"。"""
    if not text:
        return "其他"
    # 与 JS 一样，具体职能词优先；只有全都没有才让工程师/开发等泛后缀兜底。
    return (_run_function_rules(text, prefer_last, False)
            or _run_function_rules(text, prefer_last, True)
            or "其他")


# 标题里的括号通常是方向/领域/届别等修饰语，不是岗位名；先剥掉，避免末尾修饰语抢走「最靠后命中」。
_TITLE_PARENTHETICAL = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")

# 英文标题常是「Job Title, Team / Org」：逗号后不是岗位名，先只看逗号前，避免 Growth 等团队名翻盘。
def _is_latin_title(text):
    return not re.search(r"[一-龥]", text)


def _classify_job_title_base_function(title="") -> str:
    """对应 JS classifyJobTitleFunction 的基础标题分类层。"""
    raw = normalize_for_match(title)
    if not raw:
        return "其他"
    if _is_latin_title(raw) and "," in raw:
        head = raw.split(",", 1)[0].strip()
        if head:
            fn = _classify_function_text(head, prefer_last=True)
            if fn != "其他":
                return fn
    stripped = _TITLE_PARENTHETICAL.sub(" ", raw).strip()
    if stripped and stripped != raw:
        fn = _classify_function_text(stripped, prefer_last=True)
        if fn != "其他":
            return fn
    return _classify_function_text(raw, prefer_last=True)


# 招聘活动标签不是 HR 岗位名；刻意不含裸「招聘」，避免把招聘专员/招聘 HR 剥空。
_RECRUIT_EVENT_LABEL = re.compile(
    r"\d{2,4}\s*届?\s*(?:校园|春季|秋季|社会)?\s*招聘|校园招聘|春季招聘|秋季招聘|社会招聘|"
    r"校招|秋招|春招|campus\s*recruit\w*|graduate\s*program",
    re.I,
)


def _title_function_without_recruit_event(title=""):
    """剥掉招聘活动标签后重判：None 表示标题里没有可剥的活动标签。"""
    raw = normalize_for_match(title)
    if not raw:
        return "其他"
    without_event = _RECRUIT_EVENT_LABEL.sub(" ", raw).strip()
    if without_event == raw:
        return None
    if not without_event:
        return "其他"
    return _classify_function_text(without_event, prefer_last=True)


def classify_job_title_function(title="") -> str:
    """只依据标题分类；含 JS _titleFunctionWithoutRecruitEvent 的活动标签修正层。"""
    title_fn = _classify_job_title_base_function(title)
    if title_fn != "职能":
        return title_fn
    stripped_fn = _title_function_without_recruit_event(title)
    # 无可剥标签是真 HR 岗；纯活动标签没有真实角色，仍保留「职能」让调用方决定是否看正文。
    if stripped_fn is None or stripped_fn == "其他":
        return title_fn
    return stripped_fn


def classify_job_function(title="", job_type="", summary="") -> str:
    # 标题权威优先（与 JS 同口径）：标题判出干净职能就用它，避免被 job_type/summary 带偏
    #（实锤：B站「数据科学家」挂部门 job_type=「产品运营类」下，拼全文会误判「产品」）。刻意不含 job_type。
    # 「职能」例外：标题「2024 校园招聘」这类是招聘活动标签而非 HR 岗 → 退回看 标题+摘要 的真实角色。
    title_fn = classify_job_title_function(title)
    if title_fn not in ("其他", "职能"):
        return title_fn
    if title_fn == "职能":
        stripped_fn = _title_function_without_recruit_event(title)
        # 无活动标签可剥 → 「职能」来自招聘专员/招聘 HR 等岗位名，是真 HR 岗，不被正文翻盘。
        if stripped_fn is None:
            return title_fn
        # 剥完露出财务/法务等真职能或研发等真实角色时，使用剥后的结果。
        if stripped_fn != "其他":
            return stripped_fn
        # 剥完什么都不剩（纯招聘活动标签）才落到下方看正文。
    full = _classify_function_text(
        normalize_for_match(" ".join(str(x) for x in (title, summary) if x))
    )
    if full in _BODY_FALLBACK_BLOCKED:
        return title_fn
    return full if full != "其他" else title_fn


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
    # 与 JS 对齐：正文命中只能由独立的标题职能背书。旧实现拿「标题+正文」分类来放行正文，
    # 正文写算法 → 正文判研发 → 允许正文命中算法，是循环论证，职能门等于失效。
    body_allowed = (not q_fns) or (classify_job_title_function(title_text) in q_fns)
    for unit in units:
        if not any(
            contains_term(title_text, term)
            or (body_allowed and term not in TITLE_ONLY_ANCHORS and contains_term(body_text, term))
            for term in unit
        ):
            return False
    return True
