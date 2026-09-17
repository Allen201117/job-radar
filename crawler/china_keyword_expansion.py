"""中文↔英文求职关键词双语扩展 + 匹配（crawler 端）。

这是 lib/china-keyword-expansion.js 同义词组逻辑的 Python 移植，目的是让**发现端**
(discovery.filter_raw_jobs) 的关键词匹配与**前端看板** (jobMatchesChinaKeyword) 同口径：
中文发现关键词（如「算法」）也能命中英文外企岗（"Machine Learning Engineer"），反之亦然。

两边逻辑必须保持一致：改这里时同步 lib/china-keyword-expansion.js（及其单测）。
"""
import re
from typing import List

# 与 lib/china-keyword-expansion.js 的 CHINA_KEYWORD_GROUPS 一一对应（45 组）。
CHINA_KEYWORD_GROUPS: List[List[str]] = [
    ["算法", "机器学习", "深度学习", "machine learning", "deep learning", "algorithm", "ml",
     "nlp", "自然语言处理", "computer vision", "cv", "计算机视觉"],
    ["数据分析", "商业分析", "数据运营", "数据科学", "BI", "SQL", "Python",
     "data analyst", "data scientist", "business analyst", "analytics", "数据", "data"],
    ["数据工程", "大数据", "data engineer", "data engineering", "etl", "data platform"],
    ["产品经理", "产品", "AI 产品", "数据产品", "策略产品", "product manager",
     "product", "PM", "AI product", "po"],
    ["前端", "web 前端", "frontend", "front end", "front-end", "react", "vue", "javascript"],
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
    ["工程师", "engineer", "研发", "developer"],
    ["软件", "software"],
    ["ios", "android", "客户端", "客户端开发", "移动端", "鸿蒙", "harmony", "flutter", "react native"],
    ["ai", "人工智能", "artificial intelligence", "大模型", "llm", "aigc", "生成式", "genai", "agent", "智能体"],
    # 以下非互联网方向组一律追加：KEYWORD_GROUP_FUNCTIONS 按索引严格对齐，插入中间会使已有映射错位。
    ["柜员", "综合柜员", "柜面", "大堂经理", "teller"],
    # 不收裸「客户经理」：它同时是互联网/企业销售岗位，必须带对公或银行语境，避免把销售岗拉进金融业务。
    ["对公客户经理", "公司客户经理", "信贷", "信审", "授信", "理财经理", "私人银行", "personal banker", "business banker", "relationship manager"],
    ["理赔", "查勘", "核保", "核赔", "承保", "精算", "underwriter", "actuary"],
    # 不收裸「研究员」：只保留证券/投资语境，避免学术、互联网和行业研究岗互相污染。
    ["投资经理", "投研", "证券研究员", "行业研究员", "交易员", "资产管理", "基金", "portfolio manager", "trader"],
    # 学段+学科的教师画像需要命中「初中数学教研」这类真实教师岗位标题，故保留教研这一相邻岗位写法。
    ["教师", "老师", "讲师", "主讲", "教员", "助教", "班主任", "学科教师", "教研", "teacher", "instructor", "lecturer", "tutor"],
    ["教研", "教务", "培训师", "课程顾问", "学习教练", "课程研发"],
    ["护士", "护理岗", "临床护理", "护理部", "护理师", "护师", "护士长", "nurse", "nursing"],
    ["医生", "医师", "主治", "住院医师", "全科医生", "全科医师", "全科门诊", "专科医师", "physician", "doctor"],
    ["临床研究", "临床监查", "cra", "crc", "cta", "临床协调", "clinical research"],
    ["药师", "药剂", "药物研发", "制药", "药品注册", "pharmacist", "pharmaceutical"],
    ["医药代表", "医药信息沟通", "医学信息沟通", "医学联络", "msl", "medical representative"],
    ["机械设计", "机械工程", "结构设计", "机构设计", "模具设计", "mechanical design", "mechanical engineer"],
    ["工艺工程", "制程", "生产工艺", "制造工程", "工艺员", "process engineer", "manufacturing engineer"],
    ["电气工程", "电气设计", "自动化", "强电", "弱电", "plc", "控制工程", "electrical engineer"],
    ["质量工程", "质量管理", "品质", "品控", "品管", "质检", "qa", "qc", "sqe", "quality engineer"],
    ["生产管理", "车间主任", "班组长", "操作工", "装配", "技工", "production supervisor", "operator"],
    # 不收裸「结构工程」：软件结构工程也会使用它，建筑组只保留土建/施工等可替代的建筑语境。
    ["土木", "土建", "建筑工程", "建筑结构", "施工", "施工员", "现场工程师", "civil engineer", "construction"],
    ["造价", "工程预算", "工程结算", "招投标", "商务标", "cost engineer", "quantity surveyor"],
    ["客服", "客户服务", "客户支持", "售后", "呼叫中心", "坐席", "话务", "customer service", "customer support"],
    ["店长", "店员", "导购", "收银", "门店", "零售", "营业员", "领班", "store manager", "retail"],
    # 学段是修饰语，不是职能；独立成组后「中学数学教师」会保留「数学」而兼容高中/初中标题写法。
    ["小学", "初中", "中学", "高中", "高中部", "初中部", "k12", "中小学", "幼儿园", "幼教", "学前"],
]

# 算法岗位组与 AI 技术领域组的非对称展开与前端一致。AI 原本在末尾，后续只能追加，故索引固定为 24。
ALGO_GROUP_INDEX = 0
AI_DOMAIN_GROUP_INDEX = 24

_SPLIT_RE = re.compile(r"[\s,，、/|;；]+")
_SHORT_LATIN_RE = re.compile(r"[a-z0-9.+#-]{1,3}")

# 中文没有词边界，短词做子串会撞上「包含它的更长无关词」。只有某次出现不落在假朋友片段里才算命中。
# 不能因整串里出现一个假朋友就整体否定：例如「土建施工与系统实施工程」仍含一个真的「施工」。
CJK_FALSE_FRIENDS = {
    "施工": ["实施工", "设施工"],
    "品管": ["产品管", "样品管", "用品管", "物品管"],
    "质检": ["性质检"],
    "检测": ["性质检测"],
}


def _is_false_friend_occurrence(haystack, term, term_index, false_friends) -> bool:
    for friend in false_friends:
        offset = friend.find(term)
        while offset >= 0:
            friend_start = term_index - offset
            if friend_start >= 0 and haystack.startswith(friend, friend_start):
                return True
            offset = friend.find(term, offset + 1)
    return False


def normalize_for_match(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def split_keyword_terms(value) -> List[str]:
    raw = str(value or "").strip()
    parts = [p for p in (t.strip() for t in _SPLIT_RE.split(raw)) if p]
    return [raw, *parts]


def contains_term(haystack, term: str) -> bool:
    """短的纯拉丁缩写（≤3，如 ai/ml/pm/ui/hr）用词边界匹配，避免 maintain→ai、google→go
    这类误匹配；中文登记过假朋友的短词逐个出现位置判断；其余走普通子串包含。haystack 视为已 normalize_for_match。"""
    h = str(haystack or "")
    t = normalize_for_match(term)
    if not t:
        return False
    if _SHORT_LATIN_RE.fullmatch(t):
        escaped = re.escape(t)
        return re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", h) is not None
    false_friends = CJK_FALSE_FRIENDS.get(t)
    if false_friends:
        start = 0
        while True:
            term_index = h.find(t, start)
            if term_index < 0:
                return False
            if not _is_false_friend_occurrence(h, t, term_index, false_friends):
                return True
            start = term_index + len(t)
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
    # 保留既有宽召回兼容：旧 crawler 调用曾把「算法」扩展为 AI 领域词，已有断言依赖它。
    # 精确入口 job_matches 不走这里，仍严格对齐前端的「算法不反向泛化为所有 AI 岗」新语义。
    query_text = normalize_for_match(query)
    if any(contains_term(query_text, term) for term in CHINA_KEYWORD_GROUPS[ALGO_GROUP_INDEX]):
        terms.extend(normalize_for_match(term) for term in CHINA_KEYWORD_GROUPS[AI_DOMAIN_GROUP_INDEX])
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

# 各组（按索引，对应上面 45 组）→ 职能桶；None = 无干净职能（招聘类型/泛锚点），不参与职能门。
KEYWORD_GROUP_FUNCTIONS = [
    "研发",   # 0  算法
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
    None,     # 21 工程/研发通用组（跨语言锚点；仅 exact，不参与 related 兄弟排除）
    None,     # 22 软件（跨语言锚点；同上）
    "研发",   # 23 移动端
    None,     # 24 AI 技术领域（领域不等于职能）
    "金融业务",  # 25 柜员
    "金融业务",  # 26 银行业务（不含裸客户经理，避免抢销售岗）
    "金融业务",  # 27 保险业务
    "金融业务",  # 28 投资交易
    "教育培训",  # 29 教师
    "教育培训",  # 30 教研培训
    "医疗健康",  # 31 护理
    "医疗健康",  # 32 临床医生
    "医疗健康",  # 33 临床研究
    "医疗健康",  # 34 药学
    "医疗健康",  # 35 医药商务
    "生产制造",  # 36 机械设计
    "生产制造",  # 37 工艺制造
    "生产制造",  # 38 电气自动化
    "生产制造",  # 39 质量管理
    "生产制造",  # 40 生产操作
    "建筑工程",  # 41 土木建筑
    "建筑工程",  # 42 工程造价
    "客服服务",  # 43 客户服务
    "客服服务",  # 44 门店零售
    None,        # 45 学段（修饰语，不参与职能相关层）
]

# 非软件工程降级门专用：词表刻意宽于生产制造，只负责阻止传统工程/医疗靠泛工程师进入软件研发。
# 基底来自 HEAD 原词表，合并本轮新增制造词；结构/管道/技术文档无上下文可留「其他」，但绝不能判研发。
_NON_SOFTWARE_ENG_DOMAIN = re.compile(
    r"机械|机电|机加|钣金|工艺|化工|化学|材料|冶金|铸造|锻造|焊接|焊工|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|"
    r"热处理|土木|结构工程|岩土|暖通|给排水|管道|强电|工业工程|生产工艺|制造工艺|工艺技术|纺织|印染|涂装|总装|冲压|车身|"
    r"底盘|发动机|动力总成|整车|工业自动化|机械自动化|热设计|散热|结构设计|精密仪器|仪器仪表|光学|镜头|声学|射频|天线|电源|"
    r"电池|电芯|储能|逆变|试剂|生物|医疗器械|临床|药物|制药|检测认证|可靠性|环境试验|工业设计|包装设计|技术文档|标准化|"
    r"生产|制造|车间|产线|装配|组装|操作工|技工|班组长|工段|钳工|电工|铣工|车工|设备维护|设备维修|保养|production|"
    r"manufactur\w*|assembler|operator|machinist|technician|maintenance|fabrication|welding|tooling|transmission|mechanic|质量|品控|(?<![产样用物])品管|"
    r"(?<!性)质检|检验员|(?<!性质)检测|ehs|环保|安全员|职业健康|\bqa\b|\bqc\b|\bsqe\b|quality|safety|inspection",
    re.I,
)

# 生产制造归类专用：只放官方字典归属制造的传统工程、产线与质量安全词，不含土木/临床/生物医药。
_MANUFACTURING_DOMAIN = re.compile(
    r"生产|制造|车间|产线|装配|组装|操作工|技工|班组长|工段|钳工|电工|焊工|铣工|车工|设备维护|设备维修|保养|"
    r"production|manufactur\w*|assembler|operator|machinist|technician|maintenance|fabrication|welding|tooling|机械|机电|机加|钣金|工艺|"
    r"化工|化学|材料|冶金|铸造|锻造|焊接|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|热处理|纺织|印染|涂装|总装|"
    r"冲压|车身|底盘|发动机|动力总成|整车|电气|自动化|强电|仪器仪表|热设计|散热|射频|天线|电源|电池|电芯|储能|逆变|"
    r"光学|镜头|声学|精密仪器|工业工程|生产工艺|制造工艺|工艺技术|工业自动化|机械自动化|包装设计|标准化|检测认证|环境试验|"
    r"transmission|mechanic|质量|品控|(?<![产样用物])品管|(?<!性)质检|检验员|可靠性|质量体系|管理体系|体系工程师|体系专员|体系认证|认证|(?<!性质)检测|ehs|"
    r"环保|安全员|职业健康|\bqa\b|\bqc\b|\bsqe\b|quality|safety|inspection",
    re.I,
)

# 职能粗分类规则（与 JS JOB_FUNCTION_RULES 同口径，顺序敏感：产品经理优先于"含算法字样"）。
_JOB_FUNCTION_RULES = [
    ("产品", re.compile(r"产品经理|产品策划|产品负责人|产品总监|产品专家|产品实习生|产品助理|产品专员|产品企划|product\s*manager|product\s*owner|product\s*lead|(?:director|head|vp|vice\s*president)[,\s]+(?:of\s+)?product", re.I)),
    # PM/PO 在英文标题里还会表示上午下午、预防性保养等，故意不收裸 \bpm\b；也不收「工程项目」等泛词。
    ("项目管理", re.compile(r"项目经理|项目管理|项目主管|项目总监|项目负责人|交付经理|交付总监|\bpmo\b|project\s*manager|program\s*manager|delivery\s*manager|technical\s*program\s*manager|\btpm\b", re.I)),
    ("设计", re.compile(r"视觉设计|交互设计|ui\s*设计|ux|平面设计|设计师|designer", re.I)),
    ("数据", re.compile(r"数据分析|数据科学|数据工程|大数据|数据挖掘|data\s*(analyst|scien|engineer)|\bbi\b|商业分析", re.I)),
    # 英文裸 architect 在香港库实测 1915 个且压倒性是 IT 架构师；少数 Construction Project Architect 的漏判可接受。
    ("研发", re.compile(r"算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|\barchitect\b|\bsde\b|\bsre\b|programmer|software|软件", re.I)),
    # 具体软件研发之后、泛「工程师」之前：传统工程和质量安全不能被工程师抢进研发。
    ("生产制造", _MANUFACTURING_DOMAIN),
    # 仅认建筑语境：裸结构/强电/工程部等在生产库大量属于机械、电气和通用工程部门。
    ("建筑工程", re.compile(r"建筑师|钢结构|混凝土|建筑结构|水工结构|桥梁|土木|土建|道路|隧道|市政|岩土|勘察|暖通|给排水|供变电|幕墙|装饰|(?<![实设])施工|监理|造价|预算员|建筑设计|(?:高速|公路)\s*项目|architectural|landscape\s*architect|construction|site\s*engineer|civil\s*engineer", re.I)),
    # 泛工程后缀：与 JS 一样只在没有具体职能词时才兜底，避免「Data Engineer」被工程师抢成研发。
    ("研发", re.compile(r"工程师|研发|开发|技术|engineer|developer", re.I), True),
    ("运营", re.compile(r"用户运营|内容运营|运营|增长|operations|growth", re.I)),
    ("市场", re.compile(r"市场|营销|品牌|公关|marketing|brand|\bpr\b", re.I)),
    ("医疗健康", re.compile(r"医生|医师|护士|护理岗|临床护理|护理部|护理师|药师|药剂|临床数据|临床|\bcra\b|\bcrc\b|\bcta\b|医学|医药|药物|制药|药品|药理|检验科|放射|影像|超声|口腔|中医|兽医|营养师|康复|理疗|\bmsl\b|医学事务|医疗器械|试剂|生物制药|生物医药|medical|clinical|nurse|pharmac\w*|physician|therapist|biolog\w*|pathology", re.I)),
    ("金融业务", re.compile(r"柜员|综合柜员|理赔|查勘|核保|核赔|承保|信贷|信审|风控|风险管理|合规风控|投资|投研|精算|证券|保险|银行|理财|资产管理|资管|基金|信托|外汇|清算|清算结算|资金结算|证券结算|跨境结算|反洗钱|信用卡|交易员|teller|banker|underwrit\w*|actuar\w*|trader|trading|credit\s*analyst|investment", re.I)),
    ("教育培训", re.compile(r"教师|老师|讲师|教练|教研|助教|辅导员|班主任|教务|培训师|课程顾问|保育|幼师|teacher|instructor|tutor|faculty|professor|lecturer", re.I)),
    # 不含「客户经理」：它是销售岗位，避免客服服务抢走既有销售规则。
    ("客服服务", re.compile(r"客服|客户服务|客户支持|售后|服务专员|服务顾问|话务|坐席|门店|店长|店员|导购|收银|领班|前台|接待|服务员|咖啡师|调茶师|运动顾问|零售|customer\s*service|customer\s*support|customer\s*success|front\s*desk|receptionist|barista|cashier|retail\s*associate", re.I)),
    ("销售", re.compile(r"销售|商务拓展|业务拓展|渠道拓展|\bbd\b|sales|客户经理|business\s*development|account\s*(executive|manager)", re.I)),
    ("供应链", re.compile(r"供应链|采购|物流|仓储|supply\s*chain|procurement|logistics", re.I)),
    ("职能", re.compile(r"人力资源|招聘|\bhr\b|\bhrbp\b|财务|会计|审计|税务|法务|法律|合规|行政|秘书|finance|financial|tax|legal|counsel|compliance|recruit|talent\s*acquisition|human\s*resources|administrative|\badmin\b", re.I)),
]

# 与 JS BODY_FALLBACK_BLOCKED 对齐：职能绝大多数由标题确定；这些桶在正文里是万能套话，必须退回标题结论。
_BODY_FALLBACK_BLOCKED = {"研发", "项目管理", "生产制造", "建筑工程", "医疗健康", "金融业务", "教育培训", "客服服务"}

# function=null 的跨语言泛锚点：只在标题命中才算，绝不撞正文（职能门覆盖不到这类）。
TITLE_ONLY_ANCHORS = {normalize_for_match(t) for t in
                      ["工程师", "engineer", "研发", "developer", "软件", "software"]}

# 这些组是跨语言泛锚点，不能作为「兄弟方向」认领标题；否则工程师/软件/AI 会把细分研发方向互相排掉。
GENERIC_ANCHOR_GROUP_INDEXES = {21, 22, AI_DOMAIN_GROUP_INDEX}

# 与前端的 GENERIC_ROLE_SUFFIX_ONLY 一致：残差若只是职级/岗位后缀，不应被误加成新的 AND 条件。
_GENERIC_ROLE_SUFFIX_ONLY = re.compile(
    r"^(?:开发|研发|工程|工程师|技术|岗位|岗|职位|方向|专员|专家|经理|主管|总监|负责人|顾问|助理|人员|"
    r"实习生|实习|校招|社招|招聘|高级|资深|初级|中级|senior|junior|lead|staff|principal)+$",
    re.I,
)

# 软件/IT/算法信号（与 JS SOFTWARE_ENG_SIGNAL 同口径）：命中其一则即使带工业标记仍判软件研发
#（机器人/自动驾驶/嵌入式软件等交叉岗）。故意排除泛词 研发/开发/技术/工程师 及过常见的「数据」。
_SOFTWARE_ENG_SIGNAL = re.compile(
    r"软件|software|算法|algorithm|前端|frontend|front[\s-]?end|后端|backend|back[\s-]?end|全栈|"
    r"full[\s-]?stack|客户端|服务端|嵌入式|固件|firmware|测试开发|自动化测试|sdet|运维|sre|devops|"
    r"架构师|代码|编程|程序员|programmer|\bjava\b|python|golang|c\+\+|c#|\.net|javascript|typescript|"
    r"\breact\b|\bvue\b|机器学习|machine\s*learning|深度学习|deep\s*learning|\bml\b|\bnlp\b|大模型|"
    r"\bllm\b|\bai\b|人工智能|计算机视觉|\bcv\b|系统开发|平台开发|trading\s+systems?\s+engineer|web|\bapp\b|小程序|数据库|database|"
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
        # 配套护栏①：传统工程仅靠泛词落入研发且无软件信号时，不能塌进软件研发。
        if (name == "研发"
                and _NON_SOFTWARE_ENG_DOMAIN.search(text)
                and not _SOFTWARE_ENG_SIGNAL.search(text)):
            continue
        # 配套护栏②：传统工程词与软件信号共现时，生产制造让给软件研发。
        if name == "生产制造" and _SOFTWARE_ENG_SIGNAL.search(text):
            continue
        # 金融词也可能是软件系统所属领域（Trading Systems Engineer）；有精确软件信号时让给研发。
        if name == "金融业务" and _SOFTWARE_ENG_SIGNAL.search(text):
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
    for index, group in enumerate(CHINA_KEYWORD_GROUPS):
        if any(contains_term(normalized, term) for term in group):
            # AI 领域包含算法岗位的召回，但算法岗位不能反向泛化成所有 AI 岗；与前端保持单向展开。
            expanded = group + CHINA_KEYWORD_GROUPS[ALGO_GROUP_INDEX] if index == AI_DOMAIN_GROUP_INDEX else group
            units.append([normalize_for_match(t) for t in expanded])
    for lit in (normalize_for_match(t) for t in split_keyword_terms(raw)[1:]):
        if not lit:
            continue
        # 中文连写词不能因为尾部命中泛组就丢掉前半段：天线工程师 = [天线] AND [工程师]。
        residual = lit
        for unit in units:
            for term in unit:
                if term and term in residual:
                    residual = residual.replace(term, "")
        residual = residual.strip()
        if residual and residual != lit:
            if len(residual) >= 2 and not _GENERIC_ROLE_SUFFIX_ONLY.fullmatch(residual):
                units.append([residual])
            continue
        covered = any(any(term in lit or lit in term for term in unit) for unit in units)
        if not covered:
            units.append([lit])
    return units


def _title_claimed_by_rival_group(title, query) -> bool:
    """与前端同口径：正文命中前，先排除标题已明确属于其他细分方向的岗位。"""
    query_groups = set(_matched_group_indexes(query))
    if not query_groups:
        return False
    title_text = normalize_for_match(title)
    if not title_text:
        return False

    def hits_title(index):
        return any(contains_term(title_text, term) for term in CHINA_KEYWORD_GROUPS[index])

    for index in query_groups:
        if index not in GENERIC_ANCHOR_GROUP_INDEXES and hits_title(index):
            return False
    for index in range(len(CHINA_KEYWORD_GROUPS)):
        if index in query_groups or index in GENERIC_ANCHOR_GROUP_INDEXES:
            continue
        if not KEYWORD_GROUP_FUNCTIONS[index]:
            continue
        if hits_title(index):
            return True
    return False


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
    title_fn = classify_job_title_function(title_text)
    body_allowed = (
        not q_fns
        or (title_fn not in ("其他", "职能") and title_fn in q_fns and not _title_claimed_by_rival_group(title, query))
    )
    for unit in units:
        if not any(
            contains_term(title_text, term)
            or (body_allowed and term not in TITLE_ONLY_ANCHORS and contains_term(body_text, term))
            for term in unit
        ):
            return False
    return True
