const ROLE_LEXICON_EN = require("./role-lexicon-en.js");

// ── 匹配热路径记忆化（2026-09-02）─────────────────────────────────────────────
// 这是一层**纯缓存**，不改任何判定语义：缓存的都是「同输入必同输出」的纯函数结果。
//
// 病灶（香港库真实数据 CPU profile）：scoring 按 (岗位 × 关键词) 逐对调用 keywordMatchTier，
// 而它内部同时做了两件与对方无关的事 ——
//   ① 按 query 展开词库 / 判概念组：只跟关键词有关，却被 4354 行各重算一遍；
//   ② 把 title+company+location+job_type+summary 归一化：只跟岗位有关，却被每个关键词重算一遍。
// 实测 4354 行 × 12 关键词 = 52k 次调用里，59% CPU 花在 containsTerm + normalizeForMatch 上，
// 单次 /api/jobs/search 打分要 20.9s（关键词越多越慢：0 个 97ms / 4 个 2.4s / 12 个 20.9s）。
// 记忆化后每份只算一次，结果逐字段与改前相同。
//
// ⚠️ 不变量：缓存 key 必须覆盖全部输入。少一个输入 = 一个岗位/查询拿到另一个的结果，
//    静默改坏筛选准确性（本产品最高优先级指标），且不会有任何报错。改这里务必跑
//    tests/china-keyword-expansion.test.js + tests/match-memo-equivalence.test.js。
// 缓存必须声明在文件最前：模块求值期（如 TITLE_ONLY_ANCHORS）就会调用下面这些函数，
// 声明在文件尾部会撞 const 的 TDZ。

// term 侧：词表是有限闭集（CHINA_KEYWORD_GROUPS + 用户偏好词），仍留个天花板防意外增长。
const TERM_CACHE_MAX = 50000;
const _normalizedTermCache = new Map();
const _shortLatinTermRe = new Map();
const _longLatinTermRe = new Map();
// query 侧：一次请求内 query 只有几个，但会被上万行各调一次。
const QUERY_CACHE_MAX = 2000;
const _matchedGroupIndexCache = new Map();
const _keywordUnitsCache = new Map();
// job 侧：WeakMap 随行对象一起回收，不会把 candidate 缓存的 2 万行钉在内存里。
const _jobTextCache = new WeakMap();

function _cacheSet(map, key, value, max) {
  if (map.size >= max) map.clear(); // 满了整体丢弃：这些都是可重算的纯函数结果，不需要 LRU
  map.set(key, value);
  return value;
}

/** normalizeForMatch(term) 的记忆化版本。term 非字符串时不缓存（Map key 语义不可靠）。 */
function _normalizedTerm(term) {
  if (typeof term !== "string") return normalizeForMatch(term);
  const hit = _normalizedTermCache.get(term);
  if (hit !== undefined) return hit;
  return _cacheSet(_normalizedTermCache, term, normalizeForMatch(term), TERM_CACHE_MAX);
}

/**
 * 岗位侧派生文本（全部 normalizeForMatch 过）。
 * 守卫比对的是**原始字段引用**：行对象被就地改写过就重算，绝不返回别人的文本。
 * searchable 惰性算：exact 命中的岗位（keywordMatchTier 第一步就返回）根本用不到它。
 */
function _jobTexts(job) {
  if (!job || typeof job !== "object") {
    return { title: normalizeForMatch(job && job.title), company: "", content: "", searchable: "" };
  }
  const hit = _jobTextCache.get(job);
  if (
    hit &&
    hit._title === job.title &&
    hit._company === job.company &&
    hit._location === job.location &&
    hit._jobType === job.job_type &&
    hit._summary === job.summary &&
    hit._salary === job.salary_text
  ) {
    return hit;
  }
  const entry = {
    _title: job.title,
    _company: job.company,
    _location: job.location,
    _jobType: job.job_type,
    _summary: job.summary,
    _salary: job.salary_text,
    title: normalizeForMatch(job.title),
    company: normalizeForMatch(job.company),
    content: normalizeForMatch(
      [job.location, job.job_type, job.summary, job.salary_text].filter(Boolean).join(" "),
    ),
    searchable: undefined,
  };
  _jobTextCache.set(job, entry);
  return entry;
}

// 筛选器与职能分类必须共用唯一的返回值域：分类规则新增桶时，前端会自动出现对应选项，
// 避免 UI 仍展示旧集合而让用户筛到永远不可能命中的「幽灵条件」。
const JOB_FUNCTION_BUCKETS = [
  "产品", "项目管理", "设计", "数据", "研发", "生产制造", "建筑工程", "运营", "市场",
  "医疗健康", "金融业务", "教育培训", "客服服务", "销售", "供应链", "职能", "其他",
];

const CHINA_KEYWORD_GROUPS = [
  // 索引 0 = 算法**岗位方向**。刻意**不含** AI / 人工智能 / 大模型 / LLM——那些是「技术领域」
  // 不是「岗位方向」，已拆到索引 24。真实库实测：混在一起时「AI 应用研发工程师」「AI 应用测试
  // 开发工程师」「AI 架构及后端研发专家」全被判成算法岗的精确方向匹配，因为标题里那个 AI 就够了。
  [
    "算法",
    "机器学习",
    "深度学习",
    "machine learning",
    "deep learning",
    "algorithm",
    "ml",
    "nlp",
    "自然语言处理",
    "computer vision",
    "cv",
    "计算机视觉",
  ],
  [
    "数据分析",
    "商业分析",
    "数据运营",
    "数据科学",
    "BI",
    "SQL",
    "Python",
    "data analyst",
    "data scientist",
    "business analyst",
    "analytics",
    "数据", // 泛词锚点：让 query「数据」映射到本组（含下方 data），命中英文 Data* 标题
    "data", // 跨语言：命中 Data Scientist/Data Engineer/Data Analyst 等英文标题（词边界 + LATIN_TERM_VARIANTS 放行 database；datacenter/metadata/dataset 不算）
  ],
  [
    "数据工程",
    "大数据",
    "data engineer",
    "data engineering",
    "etl",
    "data platform",
  ],
  [
    "产品经理",
    "产品",
    "AI 产品",
    "数据产品",
    "策略产品",
    "product manager",
    "product",
    "PM",
    "AI product",
    "po",
  ],
  [
    "前端",
    "web 前端",
    "frontend",
    "front end",
    "front-end",
    "react",
    "vue",
    "javascript",
  ],
  [
    "后端",
    "服务端",
    "backend",
    "back end",
    "back-end",
    "服务器开发",
    "java",
    "golang",
    "go 开发",
    "全栈",
    "full stack",
    "fullstack",
  ],
  [
    "测试",
    "质量",
    "qa",
    "test engineer",
    "quality assurance",
    "测试开发",
    "sdet",
    "自动化测试",
  ],
  [
    "运维",
    "sre",
    "devops",
    "site reliability",
    "基础架构",
    "infrastructure",
    "平台工程",
    "platform engineer",
  ],
  [
    "安全",
    "信息安全",
    "网络安全",
    "security",
    "cybersecurity",
    "security engineer",
  ],
  [
    "设计",
    "ui",
    "ux",
    "交互设计",
    "视觉设计",
    "designer",
    "ui designer",
    "ux designer",
    "product designer",
  ],
  [
    "运营",
    "用户运营",
    "内容运营",
    "增长",
    "operations",
    "growth",
    "user operations",
  ],
  [
    "市场",
    "营销",
    "品牌",
    "marketing",
    "brand",
    "growth marketing",
    "市场营销",
  ],
  [
    "销售",
    "商务",
    "bd",
    "sales",
    "business development",
    "account manager",
    "客户经理",
  ],
  [
    "财务",
    "会计",
    "审计",
    "finance",
    "accounting",
    "audit",
    "financial analyst",
    "财务分析",
  ],
  [
    "人力",
    "人力资源",
    "招聘",
    "hr",
    "human resources",
    "recruiter",
    "recruiting",
    "talent",
  ],
  [
    "法务",
    "法律",
    "合规",
    "legal",
    "compliance",
    "counsel",
  ],
  [
    "供应链",
    "采购",
    "物流",
    "supply chain",
    "procurement",
    "logistics",
    "operations manager",
    // 仓储角色词（2026-09-18 库内对拍补齐）：查询「仓储运营」此前只命中本组的「物流/供应链」
    // 泛领域词，标题写「仓储主管/仓管员/仓库经理」这类不含"物流"字样的岗位召回不到。
    // 库内证据（active 校招标题 ilike）：仓储 70 / 仓库 36 / 仓管 15，逐条抽查全部落在仓储物流
    // 岗位（无一命中制造/金融等无关方向）；「仓库」的假朋友「数据仓库」已登记进
    // CJK_FALSE_FRIENDS。英文 warehouse 试过又撤（2026-09-18 全量对拍）：库内证据仅 1 例，
    // 却在英文标题里当假朋友源头——"Data Warehouse Engineer""Warehouse Production Planner"
    // "Senior Product Support Operations Manager" 这类与仓储无关的数据工程/生产计划/泛运营
    // 岗位因为含 "warehouse"/"operations" 被 `_titleRoleClusterConflict` 誤判成本组已认领，
    // 连带把它们从「数据分析」「产品经理」查询里挤掉——英文没有 CJK_FALSE_FRIENDS 那种子串
    // 位置登记机制能精确摘除，权衡后放弃这一个证据本就单薄的词，保留中文三词。
    "仓储",
    "仓库",
    "仓管",
  ],
  [
    "硬件",
    "嵌入式",
    "芯片",
    "电子",
    "hardware",
    "embedded",
    "firmware",
    "chip",
    "asic",
    "fpga",
  ],
  [
    "投研",
    "行业研究",
    "股票研究",
    "固收",
    "量化",
    "investment research",
    "equity research",
    "quant",
  ],
  [
    "管培生",
    "管理培训生",
    "校招",
    "应届",
    "graduate program",
    "campus recruitment",
    "new grad",
    "graduate",
  ],
  ["实习", "暑期实习", "日常实习", "intern", "internship"],
  // 通用「工程/研发」组（跨语言召回）：补英文 Engineer/Developer 标题的命中（外企 ATS 多英文标题）。
  // ⚠ function=null（见 KEYWORD_GROUP_FUNCTIONS 同索引）：只参与 tier-1 精确层，**不进 tier-2 兄弟排除**——
  // 否则 engineer/工程师 这类泛词几乎命中所有研发岗，会把它们当兄弟组排除，掏空前端/后端/算法的 related 层（P1 回归）。
  ["工程师", "engineer", "研发", "developer"],
  // 「软件」单列（不并入上面的泛工程组）：否则 query「软件」会等价于「工程师」、连硬件/机械工程师都召回（实测 +411% 过宽）。
  ["软件", "software"],
  // 移动端（索引 23，追加在末尾——**新组一律追加，绝不插在中间**，否则 KEYWORD_GROUP_FUNCTIONS
  // 的按索引对齐全部错位）。原本 ios / android / 客户端 挂在「前端」组里，导致真实库实测
  // 「前端开发工程师」用户 TOP10 里塞满 Android Framework / iOS / 移动端岗——国内 Web 前端与
  // 移动端是两个岗位，混在一组等于让它们互相精确命中。
  ["ios", "android", "客户端", "客户端开发", "移动端", "鸿蒙", "harmony", "flutter", "react native"],
  // AI 技术领域（索引 24）。从算法组拆出来单列，function=null（见 KEYWORD_GROUP_FUNCTIONS）：
  // 「AI」是领域不是职能——AI 产品经理是产品岗、AI 应用研发是研发岗、AI 数据分析是数据岗。
  // 混进算法组会让 qFns 平白多出「研发」，也让任何标题带 AI 的岗位冒充算法岗（实测主要误报源）。
  // 作为 tier-1 锚点仍然有用：查询「AI 产品经理」= [AI 领域] ∧ [产品]，能精确挑出 AI 方向的产品岗。
  ["ai", "人工智能", "artificial intelligence", "大模型", "llm", "aigc", "生成式", "genai", "agent", "智能体"],
  // 以下非互联网方向组一律追加：KEYWORD_GROUP_FUNCTIONS 按索引严格对齐，插入中间会使已有映射错位。
  ["柜员", "综合柜员", "柜面", "大堂经理", "teller"],
  // 不收裸「客户经理」：它同时是互联网/企业销售岗位，必须带对公或银行语境，避免把销售岗拉进金融业务。
  ["对公客户经理", "公司客户经理", "信贷", "信审", "授信", "理财经理", "私人银行", "personal banker", "business banker", "relationship manager"],
  ["理赔", "查勘", "核保", "核赔", "承保", "精算", "underwriter", "actuary"],
  // 不收裸「研究员」：只保留证券/投资语境，避免学术、互联网和行业研究岗互相污染。
  ["投资经理", "投研", "证券研究员", "行业研究员", "交易员", "资产管理", "基金", "portfolio manager", "trader"],
  // 学段+学科的教师画像需要命中「初中数学教研」这类真实教师岗位标题，故保留教研这一相邻岗位写法。
  ["教师", "老师", "讲师", "主讲", "教员", "助教", "班主任", "学科教师", "教研", "teacher", "instructor", "lecturer", "tutor"],
  ["教研", "教务", "培训师", "课程顾问", "学习教练", "课程研发"],
  ["护士", "护理岗", "临床护理", "护理部", "护理师", "护师", "护士长", "nurse", "nursing"],
  ["医生", "医师", "主治", "住院医师", "全科医生", "全科医师", "全科门诊", "专科医师", "physician", "doctor"],
  [
    "临床研究",
    "临床监查",
    "cra",
    "crc",
    "cta",
    "临床协调",
    "clinical research",
    // 2026-09-18 库内对拍补齐（active 校招标题 ilike）：临床运营 2 例（上海医药/正大天晴，
    // 均为临床运营团队负责岗）、医学经理 9 例（上海医药/扬子江/正大天晴/东阳光，医学事务管理岗，
    // 与临床研究同一职业赛道，学生搜「临床研究」时应能看到）。「临床试验」「数据管理员」试过但
    // 分别只有 1 家公司增量 / 命中农牧食品企业的无关数据岗，证据不够/噪音大，未收录。
    "临床运营",
    "医学经理",
  ],
  [
    "药师",
    "药剂",
    "药物研发",
    "制药",
    "药品注册",
    "pharmacist",
    "pharmaceutical",
    // 2026-09-18 库内对拍补齐（active 校招标题 ilike，逐条抽查无跨领域噪音）：
    // 药物化学 13 / 制剂 123 / 药理 76 / 原料药 20 / CMC 8 / 合成研究员 105（含 ADC/多肽/寡核苷酸/
    // 小核酸/有机合成等 CDMO 常见写法，均为化学合成类研发岗）。裸「合成」206 例里混入「数据合成」
    // 「语音合成大模型」等 AI 方向噪音，未收录。「合成高级研究员/合成助理研究员」中间插了职级词、
    // 不含连续子串「合成研究员」——原记为已知残留缺口，2026-09-23 起由 containsTerm 的职级插词
    // 容忍兜住（见 SENIORITY_INFIX），仍不复活裸「研究员」（见下方 2026-09-17 教训）。
    "药物化学",
    "制剂",
    "药理",
    "原料药",
    "CMC",
    "合成研究员",
  ],
  ["医药代表", "医药信息沟通", "医学信息沟通", "医学联络", "msl", "medical representative"],
  ["机械设计", "机械工程", "结构设计", "机构设计", "模具设计", "mechanical design", "mechanical engineer"],
  ["工艺工程", "制程", "生产工艺", "制造工程", "工艺员", "process engineer", "manufacturing engineer"],
  ["电气工程", "电气设计", "自动化", "强电", "弱电", "plc", "控制工程", "electrical engineer"],
  ["质量工程", "质量管理", "品质", "品控", "品管", "质检", "qa", "qc", "sqe", "quality engineer"],
  ["生产管理", "车间主任", "班组长", "操作工", "装配", "技工", "production supervisor", "operator"],
  // 不收裸「结构工程」：软件结构工程也会使用它，建筑组只保留土建/施工等可替代的建筑语境。
  ["土木", "土建", "建筑工程", "建筑结构", "施工", "施工员", "现场工程师", "civil engineer", "construction"],
  [
    "造价",
    "工程预算",
    "工程结算",
    "招投标",
    "商务标",
    "cost engineer",
    "quantity surveyor",
    // 2026-09-18 库内对拍补齐：预算员 10 例（一航局/城交公司等工程类项目预算员，全部建筑语境）。
    // 「结算」33 例逐条抽查几乎全是国际结算/期货结算/物流结算等金融业务噪音，未收录；
    // 「合约」20 例虽多为中交系「合约造价岗」，但裸「合约」在电信/保险等行业另有普遍含义、
    // 风险面无法只靠本语料确认，未收录（这个方向的低召回主要是供给缺口，非叫法缺口，见走查报告）。
    "预算员",
  ],
  ["客服", "客户服务", "客户支持", "售后", "呼叫中心", "坐席", "话务", "customer service", "customer support"],
  ["店长", "店员", "导购", "收银", "门店", "零售", "营业员", "领班", "store manager", "retail"],
  // 学段是修饰语，不是职能；独立成组后「中学数学教师」会保留「数学」而兼容高中/初中标题写法。
  ["小学", "初中", "中学", "高中", "高中部", "初中部", "k12", "中小学", "幼儿园", "幼教", "学前"],
  // 索引 46 = 投资银行/并购（2026-09-18 新增，追加在末尾，不插入中间——KEYWORD_GROUP_FUNCTIONS
  // 按索引严格对齐）。与索引 28「投资交易」故意分开成两个组：28 是买方投研/交易（投资经理/
  // 证券研究员/交易员/基金），本组是卖方投行/并购业务，两者是不同角色簇，混进同一组会让
  // 「投行分析师」召回买方研究岗、反之亦然（同「同职能≠同角色」碑，见 CLAUDE.md 2026-09-17）。
  // 库内证据（active 校招标题 ilike，逐条抽查全部为券商/银行投行部门真实岗位）：
  // 投行 22 家 8 家券商（含光大/国信/国投/安信/招商/银河/浦发/中国电信投行条线）、投资银行 3、
  // 并购 7、承做 36、承揽 13（中国五矿/中国银河/中国电信/天风/招商证券的「承做/承揽」是国内
  // 券商投行业务术语，对应海外 IBD 的 origination/execution，样本零跨领域噪音）、
  // investment banking 1（Citi 花旗 Investment Banking Analyst）、资本市场 3（股票/债券资本市场
  // 承做岗，对应 ECM/DCM）。「融资」38 例试过又撤——抽查后压倒性是企业内部投融资/财务岗
  // （国轩高科/容百科技/徐工集团等的"投融资助理/融资专员"），不是卖方投行业务，收录会把公司
  // 内部融资岗错配成投行分析师推荐，未收录。
  [
    "投行",
    "投资银行",
    "并购",
    "承做",
    "承揽",
    "investment banking",
    "资本市场",
  ],
  // 索引 47 = 编导/内容制作（2026-09-18 新增）。库内证据（active 校招标题 ilike，逐条抽查）：
  // 编导 18（米哈游/字节跳动/网易/贝壳/虎牙/新东方等，零跨领域噪音）、导演 11（游戏动画导演/
  // AIGC导演/执行导演等）、制片 7（动漫制片/影视制片）、视频剪辑 6（比裸「剪辑」14 例更干净——
  // 裸「剪辑」里混进「Agent全栈开发工程师（AI剪辑方向）」「客户端开发工程师（PC端基础剪辑）」
  // 等**做剪辑软件产品**的研发岗，未收录）。「主播」53 例试过又撤——压倒性是电商直播带货/
  // 零售主播（迪卡侬云零售/无忧传媒带货主播/FILA电商主播），甚至混进「国际直播后端开发工程师
  // （主播方向）」，属销售/运营方向不是编导内容制作，未收录；裸「策划」337 例过泛（营销策划/
  // 产品策划/活动策划等跨多个职能，未收录，仅保留复合词「短视频编导」)。
  // function=null（见 KEYWORD_GROUP_FUNCTIONS 同索引）：JOB_FUNCTION_BUCKETS 目前没有「内容制作」
  // 桶，力荐"设计"或"运营"都是够不上边的近似——不确定就不填，比塞进错的桶更诚实（同 18/19/20/21/
  // 22/24/45 等既有 null 组的处理方式），只影响 tier-2 相关层兜底，不影响本组的精确匹配。
  ["编导", "短视频编导", "导演", "制片", "视频剪辑"],
  // 索引 48 = 芯片验证（2026-09-23 新增）。用户手填「ic验证」时查询只剩字面「ic验证」一个词，
  // 真实用户（校招 · 上海/无锡/合肥/苏州/杭州）推荐页 1,529 召回只展示 5 个，而同城同阶段标题写
  // 「芯片验证工程师 / 数字验证工程师 / 逻辑验证工程师」的校招岗 ~20 个全被方向门拒掉（职能都判研发，
  // 只差叫法）。库内证据（active 近 30 天标题 ilike，逐词抽查）：芯片验证 59 / 19 家、数字验证 28 / 15、
  // soc验证 19、asic验证 13、原型验证 8、逻辑验证 4、fpga验证 4、处理器验证 3、硅后验证、
  // design verification 243 / 20 家（Apple/Intel/Amazon/长鑫，全为芯片 DV）——职能分布只有 研发/其他。
  // 🚫「设计验证」不收：抽样里有「小米汽车-热管理设计验证」（整车 DV 试验，不是芯片）；中文芯片 DV 岗
  // 另有「数字/逻辑设计验证」可由「逻辑验证」「design verification」接住。
  // 🚫 裸「验证工程师」不收：439 例横跨 建筑工程/生产制造/职能（工艺验证、电芯验证、系统验证…）。
  // 不并入硬件组（17）：那会让「ic验证」查询把「硬件工程师 / 芯片设计」都判成精确命中。
  [
    "芯片验证",
    "ic验证",
    "数字验证",
    "soc验证",
    "asic验证",
    "逻辑验证",
    "处理器验证",
    "硅后验证",
    "原型验证",
    "fpga验证",
    "design verification",
  ],
  // 索引 49 = 风控/风险管理（2026-09-23 新增）。用户手填「风控」时只剩字面「风控」一个词，而券商/银行/
  // 保险的风控岗标题压倒性写「XX风险」——真实用户（实习 · 广州）召回里广发/汇丰/越秀的
  // 「信用风险 / 市场风险 / 操作风险 / 全面风险 / 风险管理实习生」9 个全被方向门拒掉，只展示 1 个。
  // 库内证据（active 近 30 天标题 ilike，逐词抽查）：风险管理 271 / 77 家、风险策略 42、信用风险 17、
  // 风险控制 17、风险分析 15、全面风险 13、风险合规 13、操作风险 6、市场风险 6、风险量化 5，
  // 抽样全部是券商/银行/保险/消金/平台的风险岗。
  // 🚫 裸「风险」不收（569 例，含「安全风险检测」「IDC风险运营」这类非风控岗）；「反欺诈」不收
  //    （38 例里一半是反欺诈算法/产品，职能门虽能拦，但召回会被它稀释）；英文不收（国内画像用不到，
  //    risk management 142 例横跨供应链/医疗/生产制造）。
  // 不并入银行业务组（26）：那组的「信贷」同时是信贷客户经理（销售条线），并进来会把风控和客户经理搅成一簇。
  [
    "风控",
    "风险管理",
    "风险控制",
    "信用风险",
    "市场风险",
    "操作风险",
    "全面风险",
    "风险合规",
    "风险量化",
    "风险分析",
    "风险策略",
  ],
];

// 组索引常量：算法「岗位方向」组与 AI「技术领域」组之间是非对称包含关系，
// 见 keywordMatchUnits 里的单向展开。调整组顺序时这两个常量必须跟着改。
const ALGO_GROUP_INDEX = 0;
// AI 领域组原在末尾；后续组必须追加到数组末尾，故不能再用 length - 1 推导。
const AI_DOMAIN_GROUP_INDEX = 24;

// 纯职级 / 职能后缀（整串由这些词拼成才算）：它们描述「什么级别、什么形态」，不描述「什么方向」，
// 所以不配单独成为一个 AND 匹配单元。见 keywordMatchUnits 的残差处理。
// 2026-09-18 补「服务」「管培」「分析师」：库内实测查询「售后服务」在扣掉组词「售后」后残差
// 「服务」被当成强制 AND 单元，导致标题写「售后工程师/售后运营/售后客服」等不含"服务"二字的
// 岗位（active 校招 157 例里 115 例、73%）被漏判；查询「门店管培」同理扣掉「门店」后残差
// 「管培」把「储备店长」（76 例，不含"管培"二字）挡在外面；查询「投行分析师」扣掉「投行」后
// 残差「分析师」把国内券商真实标题「投行业务岗/承做岗/承揽岗」（22+36+13 例，无一处写
// "分析师"三字）全部挡在外面。三词与"经理/主管/专员"等已在表内的词同类——描述岗位的「形态」
// （服务型/培训生形态/分析师职级），不携带方向信息，补进本表后三条查询都从 AND 残差退回纯粹的
// 组内 OR 匹配，逐条 jobMatchesChinaKeyword 回归验证见 china-keyword-expansion.test.js。
const GENERIC_ROLE_SUFFIX_ONLY =
  /^(?:开发|研发|工程|工程师|技术|岗位|岗|职位|方向|专员|专家|经理|主管|总监|负责人|顾问|助理|人员|实习生|实习|校招|社招|招聘|高级|资深|初级|中级|服务|管培|分析师|senior|junior|lead|staff|principal)+$/;

const CITY_ALIASES = new Map([
  ["北京", "北京"],
  ["北京市", "北京"],
  ["beijing", "北京"],
  ["上海", "上海"],
  ["上海市", "上海"],
  ["shanghai", "上海"],
  ["深圳", "深圳"],
  ["深圳市", "深圳"],
  ["shenzhen", "深圳"],
  ["广州", "广州"],
  ["广州市", "广州"],
  ["guangzhou", "广州"],
  ["杭州", "杭州"],
  ["杭州市", "杭州"],
  ["hangzhou", "杭州"],
  ["南京", "南京"],
  ["南京市", "南京"],
  ["nanjing", "南京"],
  ["苏州", "苏州"],
  ["苏州市", "苏州"],
  ["suzhou", "苏州"],
  ["成都", "成都"],
  ["成都市", "成都"],
  ["chengdu", "成都"],
  ["武汉", "武汉"],
  ["武汉市", "武汉"],
  ["wuhan", "武汉"],
  ["西安", "西安"],
  ["西安市", "西安"],
  ["xi'an", "西安"],
  ["xian", "西安"],
  // 用户真实填过、但此前没登记的地级市（画像体检：14/64 个画像因此报 location_unregistered_city）。
  // 没登记 ≠ 完全搜不到——normalizeChinaCity 的子串兜底仍能把「浙江省宁波市」认出来；缺的是
  // ① 归一成规范名（写回 location 与筛选口径一致）② cityMatchTokens 的**双向**匹配（筛「宁波」
  // 才能命中 location="Ningbo"）。拼音只收**唯一**的：泰州/台州、福州/抚州 同音，收了会张冠李戴。
  ["无锡", "无锡"],
  ["无锡市", "无锡"],
  ["wuxi", "无锡"],
  ["合肥", "合肥"],
  ["合肥市", "合肥"],
  ["hefei", "合肥"],
  ["宁波", "宁波"],
  ["宁波市", "宁波"],
  ["ningbo", "宁波"],
  ["东莞", "东莞"],
  ["东莞市", "东莞"],
  ["dongguan", "东莞"],
  ["佛山", "佛山"],
  ["佛山市", "佛山"],
  ["foshan", "佛山"],
  ["珠海", "珠海"],
  ["珠海市", "珠海"],
  ["zhuhai", "珠海"],
  ["惠州", "惠州"],
  ["惠州市", "惠州"],
  ["huizhou", "惠州"],
  ["湛江", "湛江"],
  ["湛江市", "湛江"],
  ["zhanjiang", "湛江"],
  ["青岛", "青岛"],
  ["青岛市", "青岛"],
  ["qingdao", "青岛"],
  ["南昌", "南昌"],
  ["南昌市", "南昌"],
  ["nanchang", "南昌"],
  ["南宁", "南宁"],
  ["南宁市", "南宁"],
  ["nanning", "南宁"],
  // 校招 ATS 常把低频城市直接写成英文/拼音（如 China\\Shanxi-Taiyuan）。这些别名归入
  // 全站城市口径，供岗位筛选与校招分面共同复用，避免专区另维护一份词表。
  ["太原", "太原"],
  ["太原市", "太原"],
  ["taiyuan", "太原"],
  ["桂林", "桂林"],
  ["桂林市", "桂林"],
  ["guilin", "桂林"],
  ["济南", "济南"],
  ["济南市", "济南"],
  ["jinan", "济南"],
  // 2026-09-23 线上 /campus 城市下拉逐条核对：同批还有这三个英文原文（全站别名表里此前没有）。
  ["沈阳", "沈阳"],
  ["沈阳市", "沈阳"],
  ["shenyang", "沈阳"],
  ["郑州", "郑州"],
  ["郑州市", "郑州"],
  ["zhengzhou", "郑州"],
  ["南通", "南通"],
  ["南通市", "南通"],
  ["nantong", "南通"],
  // 同批 /campus 城市下拉（校招 + 实习两份选项表逐条核对）里还有这几个拼音原文。
  ["长沙", "长沙"],
  ["长沙市", "长沙"],
  ["changsha", "长沙"],
  ["重庆", "重庆"],
  ["重庆市", "重庆"],
  ["chongqing", "重庆"],
  ["三亚", "三亚"],
  ["三亚市", "三亚"],
  ["sanya", "三亚"],
  ["乌鲁木齐", "乌鲁木齐"],
  ["乌鲁木齐市", "乌鲁木齐"],
  ["urumqi", "乌鲁木齐"],
  ["厦门", "厦门"],
  ["厦门市", "厦门"],
  ["xiamen", "厦门"],
  ["海口", "海口"],
  ["海口市", "海口"],
  ["haikou", "海口"],
  ["长春", "长春"],
  ["长春市", "长春"],
  ["changchun", "长春"],
  ["绍兴", "绍兴"],
  ["绍兴市", "绍兴"],
  ["shaoxing", "绍兴"],
  ["连云港", "连云港"],
  ["连云港市", "连云港"],
  ["lianyungang", "连云港"],
  ["泰州", "泰州"], // 不收拼音 taizhou：与台州同音
  ["泰州市", "泰州"],
  ["福州", "福州"], // 不收拼音 fuzhou：与抚州同音
  ["福州市", "福州"],
  ["香港", "香港"],
  ["香港特别行政区", "香港"],
  ["hong kong", "香港"],
  ["新加坡", "新加坡"],
  ["singapore", "新加坡"],
  ["纽约", "纽约"],
  ["new york", "纽约"],
  ["nyc", "纽约"],
  ["旧金山", "旧金山"],
  ["san francisco", "旧金山"],
  ["sf", "旧金山"],
  ["西雅图", "西雅图"],
  ["seattle", "西雅图"],
  ["山景城", "山景城"],
  ["mountain view", "山景城"],
  ["桑尼维尔", "桑尼维尔"],
  ["sunnyvale", "桑尼维尔"],
  ["圣何塞", "圣何塞"],
  ["san jose", "圣何塞"],
  ["奥斯汀", "奥斯汀"],
  ["austin", "奥斯汀"],
  ["波士顿", "波士顿"],
  ["boston", "波士顿"],
  ["伦敦", "伦敦"],
  ["london", "伦敦"],
  ["全国", "全国"],
  ["全国多地", "全国"],
  ["多地", "全国"],
  ["remote", "远程"],
  ["远程", "远程"],
]);

// 省份/区域不是岗位的规范城市，不能写回 location；只在筛选匹配时展开到库内常见的主城市。
// 同一省份只保留主要招聘城市，避免把省级意图不必要地扩成所有地级市。
const CHINA_CITY_REGION_EXPANSIONS = new Map([
  ["安徽", ["合肥"]],
  ["安徽省", ["合肥"]],
  ["福建", ["福州", "厦门"]],
  ["福建省", ["福州", "厦门"]],
  ["甘肃", ["兰州"]],
  ["甘肃省", ["兰州"]],
  ["广东", ["广州", "深圳"]],
  ["广东省", ["广州", "深圳"]],
  ["广西", ["南宁"]],
  ["广西壮族自治区", ["南宁"]],
  ["贵州", ["贵阳"]],
  ["贵州省", ["贵阳"]],
  ["海南", ["海口"]],
  ["海南省", ["海口"]],
  ["河北", ["石家庄"]],
  ["河北省", ["石家庄"]],
  ["河南", ["郑州"]],
  ["河南省", ["郑州"]],
  ["黑龙江", ["哈尔滨"]],
  ["黑龙江省", ["哈尔滨"]],
  ["湖北", ["武汉"]],
  ["湖北省", ["武汉"]],
  ["湖南", ["长沙"]],
  ["湖南省", ["长沙"]],
  ["吉林", ["长春"]],
  ["吉林省", ["长春"]],
  ["江苏", ["南京", "苏州"]],
  ["江苏省", ["南京", "苏州"]],
  ["江西", ["南昌"]],
  ["江西省", ["南昌"]],
  ["辽宁", ["沈阳", "大连"]],
  ["辽宁省", ["沈阳", "大连"]],
  ["内蒙古", ["呼和浩特"]],
  ["内蒙古自治区", ["呼和浩特"]],
  ["宁夏", ["银川"]],
  ["宁夏回族自治区", ["银川"]],
  ["青海", ["西宁"]],
  ["青海省", ["西宁"]],
  ["山东", ["济南", "青岛"]],
  ["山东省", ["济南", "青岛"]],
  ["山西", ["太原"]],
  ["山西省", ["太原"]],
  ["陕西", ["西安"]],
  ["陕西省", ["西安"]],
  ["四川", ["成都"]],
  ["四川省", ["成都"]],
  ["西藏", ["拉萨"]],
  ["西藏自治区", ["拉萨"]],
  ["新疆", ["乌鲁木齐"]],
  ["新疆维吾尔自治区", ["乌鲁木齐"]],
  ["云南", ["昆明"]],
  ["云南省", ["昆明"]],
  ["浙江", ["杭州"]],
  ["浙江省", ["杭州"]],
  ["北京", ["北京"]],
  ["北京市", ["北京"]],
  ["上海", ["上海"]],
  ["上海市", ["上海"]],
  ["天津", ["天津"]],
  ["天津市", ["天津"]],
  ["重庆", ["重庆"]],
  ["重庆市", ["重庆"]],
  ["珠三角", ["广州", "深圳"]],
  ["长三角", ["上海", "杭州", "南京", "苏州"]],
  ["京津冀", ["北京", "天津", "石家庄"]],
]);

// 海外城市的规范名（canonical）。它们保留在 CITY_ALIASES 里**只为匹配**（normalizeChinaCity
// 让「San Francisco」和「旧金山」归一到同一 key）；但**显示/落库**归一（normalizeChinaLocation）
// 必须把海外英文地名原样透传——不能把 "San Francisco, CA" 翻成 "旧金山、CA"。
// 香港/新加坡不入此集合：沿用既有「归一为中文名展示」的行为（港=国内，新加坡为常用中文名，改动会动既有测试）。
const OVERSEAS_CITY_CANONICALS = new Set([
  "纽约",
  "旧金山",
  "西雅图",
  "山景城",
  "桑尼维尔",
  "圣何塞",
  "奥斯汀",
  "波士顿",
  "伦敦",
]);

function expandChinaKeywordTerms(query, options = {}) {
  const raw = String(query || "").trim();
  if (!raw) return [];

  const normalized = normalizeForMatch(raw);
  const terms = new Set(splitKeywordTerms(raw));

  for (const group of CHINA_KEYWORD_GROUPS) {
    const matched = group.some((term) => containsTerm(normalized, term));
    if (matched) {
      group.forEach((term) => terms.add(term));
      group.forEach((term) => terms.add(normalizeForMatch(term)));
    }
  }

  if (shouldIncludeOverseasLexicon(options)) {
    for (const group of matchedOverseasLexiconGroups(normalized)) {
      group.forEach((term) => terms.add(term));
      group.forEach((term) => terms.add(normalizeForMatch(term)));
    }
  }

  return Array.from(terms)
    .map((term) => String(term || "").trim())
    .filter(Boolean);
}

// 全文检索（/api/jobs/search 的 FTS 路径）用的「候选词集」= 查询命中概念组的全部同义词（精确层，含跨语言，如 产品→product manager）。
// 之后仍由 jobFilterTier 在 JS 里精筛分层。**刻意不并入「同职能兄弟组」**：那会让 算法/后端(都属研发)这类查询
// 把全部研发岗都拉成候选(上海算法实测候选爆→8.9s)，而这些「同职能但非该方向」岗对关键词搜索价值低。
// 收窄到精确同义词后：候选≈结果、秒级、且更精准(算法搜出的是算法岗，不是所有工程师)。
// 只保留 ≥2 字的词（1 字无法生成 bigram/整词，且天然过泛）。元素为去空白小写。
function ftsCandidateTerms(query, options = {}) {
  const terms = new Set(expandChinaKeywordTerms(query, options).map((t) => normalizeForMatch(t)));
  return Array.from(terms).filter((t) => t && t.length >= 2);
}

// 把查询拆成若干「概念单元」，用于组合意图的精准匹配。
// 一个单元 = 一组同义词（OR），单元之间 AND。例如 "AI PM"：
//   命中「算法/AI」组 → 单元A=[算法,ai,大模型,...]；命中「产品」组 → 单元B=[产品经理,产品,pm,...]
//   岗位须同时命中 A 和 B → 才算「AI 产品经理」，避免把纯算法岗或纯产品岗也召回（旧逻辑是全 OR，召回过宽）。
// 查询里不属于任何组的散词（如公司名/小众词）各自成单元，也按 AND 处理 → 提升精准度。
// 把 query 展开成匹配单元。**只跟 (query, 是否带海外词库) 有关**，与岗位无关 —— 但打分时
// 会被上万行各调一次，故记忆化。缓存值冻结成只读：现有调用方（jobMatchesChinaKeyword 的
// every/some、opportunities.ts 的 filter、单测）全是只读，冻上后将来谁就地改会当场抛错，
// 而不是把一个查询的单元污染带给下一个查询。
/**
 * @param {string} query
 * @param {{ includeOverseasLexicon?: boolean }} [options]
 * @returns {ReadonlyArray<ReadonlyArray<string>>} 冻结的匹配单元（单元间 AND、单元内 OR）。
 *   冻结是有意的：返回的是共享缓存里的那一份，就地改写会污染后续所有同查询的调用方。
 */
function keywordMatchUnits(query, options = {}) {
  const raw = String(query || "").trim();
  if (!raw) return EMPTY_UNITS;
  const cacheKey = `${shouldIncludeOverseasLexicon(options) ? "1" : "0"}\u0000${raw}`;
  const cached = _keywordUnitsCache.get(cacheKey);
  if (cached !== undefined) return cached;

  const normalized = normalizeForMatch(raw);
  const units = [];

  const matchedGroupIdx = [];
  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    if (CHINA_KEYWORD_GROUPS[i].some((term) => containsTerm(normalized, term))) matchedGroupIdx.push(i);
  }

  // 21=工程师/研发/engineer/developer、22=软件/software 命中时，若命中位置与另一个**具体方向组**
  // 在查询原文里重叠（同一段字描述的是一件事，如「药物研发」里的"研发"完全被"药物研发"包住，
  // 「机械工程师」里的"工程师"与"机械工程"共享"工程"两个字），独立成一条 AND 单元就是重复限制——
  // 2026-09-18 实测「药物研发」：34 组已经命中整串"药物研发"，21 组又独立命中"研发"二字，残差
  // 处理把两处命中都扣掉后剩下的"药物"当成第三个强制 AND 单元，真实「有机合成研究员/制剂研究员」
  // 类标题因为标题里不是"研发"而是"研究员"，被这第三层硬性 AND 挡在门外。
  // 判据 = 去掉 21/22 后，**只用其余具体方向组**能否把原始查询几乎耗尽（残差 <2 字，同下方残差
  // 门槛）：能耗尽 → 21/22 的命中纯属文字重叠、没有独立信息，压掉；耗不尽（如「硬件工程师」里
  // "硬件"耗完后还剩"工程师"三个实字）→ 21/22 是查询里另一段独立信息，必须保留，否则会把
  // 「硬件产品经理」「测试」组的「供应商质量管理」这类无关角色一并放行（2026-09-18 全量对拍
  // 实测：不分场合一律压掉会让 8 个常见技术方向查询各多出成百上千个跨领域误判，代价远大于收益）。
  const specificMatchedIdx = matchedGroupIdx.filter((i) => !GENERIC_ANCHOR_GROUP_INDEXES.has(i));
  let suppressGenericFallback = false;
  if (specificMatchedIdx.length > 0) {
    const specificTerms = specificMatchedIdx.flatMap((i) => CHINA_KEYWORD_GROUPS[i]);
    const remainder = specificTerms
      .reduce((rest, term) => (term && rest.includes(normalizeForMatch(term)) ? rest.split(normalizeForMatch(term)).join("") : rest), normalized)
      .trim();
    suppressGenericFallback = remainder.length < 2;
  }

  for (const i of matchedGroupIdx) {
    if (suppressGenericFallback && (i === 21 || i === 22)) continue;
    const group = CHINA_KEYWORD_GROUPS[i];
    // 非对称包含：AI 领域 ⊃ 算法岗位。搜「人工智能」要召回 Machine Learning Engineer，
    // 但搜「算法工程师」不该因为标题带个 AI 就召回任何 AI 岗（本轮实测最大的误报源）。
    // 组机制本身是对称的，所以在**查询展开**这一步单向补上：命中 AI 领域组 → 单元并入算法组；
    // 命中算法组 → 单元只有算法组，不反向拉进 AI 领域词。
    const expanded =
      i === AI_DOMAIN_GROUP_INDEX ? [...group, ...CHINA_KEYWORD_GROUPS[ALGO_GROUP_INDEX]] : group;
    units.push(expanded.map(normalizeForMatch));
  }

  if (shouldIncludeOverseasLexicon(options)) {
    mergeOverseasLexiconUnits(units, matchedOverseasLexiconGroups(normalized));
  }

  // 散词（split 后的各 token，去掉整串本身）：未被任何已命中组覆盖的，单独成 AND 单元。
  // ⚠️ 中文连写词切不开（splitKeywordTerms 只按空格/标点分），所以「整串里含某个组词」不等于
  // 整串都被覆盖了：「天线工程师」只有「工程师」命中组，旧实现按 lit.includes(t) 判为已覆盖 →
  // 「天线」被整个丢掉 → 查询退化成搜「工程师」，匹配上 Software Engineer / 销售工程师
  // （实测某射频画像 27% 的岗都是这么误召的）。改为扣掉已命中组词后取残差另立单元。
  const literals = splitKeywordTerms(raw).slice(1).map(normalizeForMatch).filter(Boolean);
  for (const lit of literals) {
    const residual = units
      .flat()
      .reduce((rest, term) => (term && rest.includes(term) ? rest.split(term).join("") : rest), lit)
      .trim();
    // 残差 ≥2 字符才算真实意图；单字残差多为「大数据工程师」扣完剩下的「大」这类碎片。
    // 且残差必须携带**方向信息**：纯职级/职能后缀（开发 / 研发 / 高级 / 实习生…）不能另立 AND 单元。
    // 实测踩坑：查询「前端开发工程师」扣掉「前端」「工程师」后残差是「开发」，被当成硬性 AND 条件 →
    // 「前端工程师」「高级前端工程师」「前端研发工程师」这些**真·前端岗**全部掉出 exact、降到 related，
    // 跟「良率提升工程师」这类兜底岗同档同分，排序上彻底混在一起（该画像方向准确率被拉到 19%）。
    // 「天线工程师」的「天线」不在此列，仍然另立单元——那才是这段残差逻辑存在的理由。
    if (residual && residual !== lit) {
      if (residual.length >= 2 && !GENERIC_ROLE_SUFFIX_ONLY.test(residual)) units.push([residual]);
      continue;
    }
    const covered = units.some((u) => u.some((t) => t.includes(lit) || lit.includes(t)));
    if (!covered) units.push([lit]);
  }

  for (const unit of units) Object.freeze(unit);
  return _cacheSet(_keywordUnitsCache, cacheKey, Object.freeze(units), QUERY_CACHE_MAX);
}

// 跨语言泛锚点：工程师 / 软件 这两组 function=null（见 KEYWORD_GROUP_FUNCTIONS），
// 职能门覆盖不到，且天然极泛（几乎所有研发岗正文都含）→「只在岗位标题命中才算数」，绝不撞正文。
// 其余泛词（产品/数据/测试/设计…）的跨职能误召一律交给下方「职能门」治，无需逐词维护清单。
// 元素须为 normalizeForMatch 后的小写形式。
const TITLE_ONLY_ANCHORS = new Set(
  ["工程师", "engineer", "研发", "developer", "软件", "software"].map(normalizeForMatch),
);

function isTitleOnlyAnchor(term) {
  return TITLE_ONLY_ANCHORS.has(normalizeForMatch(term));
}

// 正文里的短词几乎不携带岗位职能信息（如「测试」「硬件」常见于任意 JD），只能由标题确认方向。
function isBodyWeakTerm(term) {
  const normalized = normalizeForMatch(term);
  if (!normalized) return false;
  if (/^[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]+$/.test(normalized)) {
    return normalized.length <= 2;
  }
  return /^[a-z]+$/.test(normalized) && normalized.length <= 3;
}

// 跨语言泛锚点组（工程/研发通用、软件）：它们不代表任何细分方向，判「标题归谁」时必须跳过，
// 否则「工程师」这个词会让任意工程岗都自称已被本查询认领。
// 泛锚点组：几乎每个技术岗的标题/正文都带这些词，所以「标题命中了它」不足以证明标题就是这个方向，
// 不能拿它去放行下面的兄弟组检查。21/22 = 工程师/软件；24 = AI 领域词。
const GENERIC_ANCHOR_GROUP_INDEXES = new Set([21, 22, AI_DOMAIN_GROUP_INDEX]);

// 组内「领域锚点词」：它描述**这个岗在哪个领域**，不描述**这个人做什么角色**。
// 组是按「岗位方向」建的，但每组里都掺了几个领域词（数据 / 产品 / 品牌 / 财务 …）用来兜跨语言召回。
// 这些词在**标题**上是最大的误报源——2026-09-17 真实库对拍（6 份简历画像 × A/B 两维 top-25）
// 21 个被独立裁判判「不是同一个角色」的岗里，**全部 roleTier=exact**，其中 9 个是这么进来的：
//   查询「数据分析师」→ 标题「大数据开发负责人 / 零部件数据工程师 / 大模型训练数据工程师」（靠"数据"）
//   查询「AI 产品经理」→ 标题「AI产品运营 / 大模型MaaS网关产品运营专家」（靠"产品"）
//   查询「品牌营销」  → 标题「品牌设计 / 大客户销售专家-商业营销」（靠"品牌""营销"）
//   查询「审计」      → 标题「财务科技（ERP方向）- 全栈开发工程师 / 财务数字化业财产品」（靠"财务"）
// 共同形态 = **只靠领域锚点命中标题，而标题里的角色词属于另一个角色簇**（大数据 / 运营 / 设计 /
// 销售 / 全栈）。它落在职能门之下：产品 vs 产品运营同属「产品/运营」相邻职能，算法组的兄弟排除
// 也管不到，必须在「具体角色」这一层判。
//
// ⚠️ 只有「领域词」才能进这张表。**角色词绝不能进**——它同时也是别的组认领标题的凭据：
// 「设计」留在设计组里，正是靠它把「品牌设计」判给设计组；把它标成锚点，这条修法自己就失效了。
const GROUP_DOMAIN_ANCHORS = new Map([
  [1, ["数据", "data", "sql", "python", "bi"]],
  [3, ["产品", "product"]],
  [11, ["市场", "品牌", "brand"]],
  // 「商务」在销售组里，但它同时是「商务管理 / 商务专员 / 商务标」的通用后缀——拿它去认领标题
  // 会误杀真岗（2026-09-17 对拍：品牌营销画像的「商务管理-品牌中心」「海外市场商务专员」
  // 两个 same_role 岗就是被它剔掉的）。销售组仍能靠「销售 / sales / bd / 客户经理」认领。
  [12, ["商务"]],
  [13, ["财务", "finance"]],
  // 「CMC」「制剂」是药学里的**功能/产品领域**词，不是岗位角色——2026-09-18 全量对拍实测：
  // 不标成锚点会让"CMC Lead, Launch Product, Small Molecules""MR-呼吸生物制剂新产品-上海"
  // 这类标题（前者是产品岗挂了 CMC 功能领域前缀，后者是医药代表/MR 推广"制剂"类产品、不是
  // 制剂研发岗本人）被 `_titleRoleClusterConflict` 误判成"已被药学组认领"，产品经理查询回归
  // 少召回的岗位大多是这么丢的（同「品牌/商务/财务」的锚点道理：领域词能兜召回，但不能替真正
  // 的角色词——药物研发/合成研究员/药理/原料药/临床研究等——做主）。
  [34, ["CMC", "制剂"]],
  // 「风控」在标题里常是**业务域**不是角色：「账号风控产品实习生」「风控平台产品经理」「风控算法工程师」。
  // 2026-09-23 对拍：新建风控组（49）后不标锚点，产品经理画像的「账号风控产品实习生」（same_role）被
  // `_titleRoleClusterConflict` 判给风控组、当场拒掉。风控组仍能靠「风险管理 / 信用风险 / 市场风险…」认领标题；
  // 查询「风控」本身不受影响（只写了领域词 = 要整个领域，交给职能门挑）。
  [49, ["风控"]],
]);

function _groupRoleTerms(i) {
  const anchors = GROUP_DOMAIN_ANCHORS.get(i);
  if (!anchors) return CHINA_KEYWORD_GROUPS[i];
  const skip = new Set(anchors.map(normalizeForMatch));
  return CHINA_KEYWORD_GROUPS[i].filter((t) => !skip.has(normalizeForMatch(t)));
}

// 角色簇门（tier-1）：查询只靠领域锚点命中标题，而标题带着另一个角色簇的角色词 → 那个岗属于那个簇。
//
// 与下面 _titleClaimedByRivalGroup 的分工：那条只管**正文**命中（bodyAllowed），本条管**标题**命中——
// 上述 9 个误报全是标题直接命中，正文那道门一次都没拦到。
// 三条不误杀的约束：
//   ① 查询自己的**角色词**（非锚点）出现在标题 → 标题就是这个角色，立即放行；
//   ② 查询的组在标题上压根没命中（命中在正文/公司）→ 不归本门管，交还给原有职能门；
//   ③ 认领方必须是「有职能映射的具体方向组」且用它自己的**角色词**认领——泛锚点组
//      （工程师 / 软件 / AI 领域）和招聘类型组（校招 / 实习 / 投研）无权认领。
//   ④ 查询本身必须携带**角色意图**——查询只写了领域词（「数据」「产品」）时，用户要的就是整个领域，
//      凭什么替他把 Data Engineer 划掉？（tests/cross-language-recall「数据 → Data Engineer」钉着这条。）
function _queryHasRoleIntent(query) {
  const normalized = normalizeForMatch(query);
  for (const i of _matchedGroupIndexes(query)) {
    if (GENERIC_ANCHOR_GROUP_INDEXES.has(i) || !KEYWORD_GROUP_FUNCTIONS[i]) continue;
    if (!GROUP_DOMAIN_ANCHORS.has(i)) return true; // 该组没有锚点 → 命中的必然是角色词
    if (_groupRoleTerms(i).some((term) => containsTerm(normalized, term))) return true;
  }
  return false;
}

function _titleRoleClusterConflict(job, query) {
  const qGroups = _matchedGroupIndexes(query);
  if (qGroups.length === 0) return false;
  if (!_queryHasRoleIntent(query)) return false; // ④
  const titleText = _jobTexts(job).title;
  if (!titleText) return false;

  let anchorOnly = false;
  for (const i of qGroups) {
    if (GENERIC_ANCHOR_GROUP_INDEXES.has(i) || !KEYWORD_GROUP_FUNCTIONS[i]) continue;
    if (_groupRoleTerms(i).some((term) => containsTerm(titleText, term))) return false; // ①
    if (CHINA_KEYWORD_GROUPS[i].some((term) => containsTerm(titleText, term))) anchorOnly = true;
  }
  if (!anchorOnly) return false; // ②

  // 认领只看标题主干，括号里的限定语不算数：「品牌传播（先进制造及质量方向）」的「质量」是业务域，
  // 不是岗位角色，拿它判给质量组会误杀一个真·品牌岗（2026-09-17 对拍实测）。
  // 与 _classifyJobTitleBaseFunction 用同一个 TITLE_PARENTHETICAL，口径不另立一套。
  const mainTitle = titleText.replace(TITLE_PARENTHETICAL, " ");
  const qGroupSet = new Set(qGroups);
  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    if (qGroupSet.has(i) || GENERIC_ANCHOR_GROUP_INDEXES.has(i)) continue;
    if (!KEYWORD_GROUP_FUNCTIONS[i]) continue; // ③
    if (_groupRoleTerms(i).some((term) => containsTerm(mainTitle, term))) return true;
  }
  return false;
}

// 标题是否已被「别的细分方向」认领。
//
// 病灶：职能桶只有 9 个，「研发」是个巨桶（算法/前端/后端/测试/运维/安全/硬件全在里面）。
// 旧的 bodyAllowed 只要求「岗位职能 == 查询职能」，在研发桶内部等于没设防：查询「算法工程师」
// 的同义词组含 AI / 大模型 / 机器学习，而这些词几乎每篇技术岗 JD 都会写 → 真实库实测把
// 「阿里云运维工程师」「后端开发工程师」「Java 广告系统研发工程师」全判成 exact 方向匹配。
//
// 修法：标题里没有查询自己的细分词、却带着另一个细分方向的词 → 这个岗属于那个细分，
// 它正文里的泛技术词不能再算作本方向的精确命中。标题带查询细分词的岗一律放行（不误杀）。
function _titleClaimedByRivalGroup(job, query) {
  const qGroups = new Set(_matchedGroupIndexes(query));
  if (qGroups.size === 0) return false;
  const titleText = _jobTexts(job).title;
  if (!titleText) return false;

  const hitsTitle = (i) => CHINA_KEYWORD_GROUPS[i].some((term) => containsTerm(titleText, term));

  // 查询自己的细分组在标题里命中 → 标题就是这个方向，放行。
  for (const i of qGroups) {
    if (GENERIC_ANCHOR_GROUP_INDEXES.has(i)) continue;
    if (hitsTitle(i)) return false;
  }
  // 标题被非查询的细分组认领 → 属于那个细分。
  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    if (qGroups.has(i) || GENERIC_ANCHOR_GROUP_INDEXES.has(i)) continue;
    if (!KEYWORD_GROUP_FUNCTIONS[i]) continue; // 招聘类型 / 投研：不是方向，不参与认领
    if (hitsTitle(i)) return true;
  }
  return false;
}

// 查询命中的概念组对应的职能集合（去掉 null：招聘类型 / 投研 / 工程通用组无干净职能桶）。
function queryFunctions(query) {
  return new Set(
    _matchedGroupIndexes(query)
      .map((i) => KEYWORD_GROUP_FUNCTIONS[i])
      .filter(Boolean),
  );
}

function jobMatchesChinaKeyword(job, query, options = {}) {
  const units = keywordMatchUnits(query, options);
  if (units.length === 0) return true;

  // 三份文本只跟岗位有关、与 query 无关 → 一个岗位算一次，别被每个关键词重算（见文件头缓存说明）。
  // 公司域保留短词命中：用户会直接搜「字节」「网易」等公司名。
  // 内容域的短词（摘要 / 城市 / 类型 / 薪资）不携带稳定职能信息，不能单独证明精确匹配。
  const jobTexts = _jobTexts(job);
  const titleText = jobTexts.title;
  const companyText = jobTexts.company;
  const contentText = jobTexts.content;

  // 职能门：正文（非标题）命中只在「标题已明确的岗位职能与查询职能相容」时才算数。
  // 治跨职能污染双向——算法岗正文写"产品"不该被 pm 召回，产品岗正文写"算法"也不该被"算法"召回。
  // 不能用正文兜底的职能反过来给正文放行，避免“正文自己证明自己”；查询无职能信号时仍放行公司检索。
  const qFns = queryFunctions(query);
  const titleFn = classifyJobTitleFunction(job);
  // 同职能内还要过「细分方向」这一关：光同职能挡不住研发巨桶内部的算法↔运维↔后端↔测试互串。
  const bodyAllowed =
    qFns.size === 0 ||
    (titleFn !== "其他" &&
      titleFn !== "职能" &&
      qFns.has(titleFn) &&
      !_titleClaimedByRivalGroup(job, query));

  // 角色簇门：标题只被领域锚点（数据/产品/品牌/财务…）命中、而标题的角色词归另一个簇 → 不是同角色。
  if (_titleRoleClusterConflict(job, query)) return false;

  // 单元间 AND、单元内 OR（组合意图精准，"AI PM" = AI ∧ 产品）；
  // 标题命中始终算数；公司正文可保留短词，内容正文须非泛锚点、非短弱词，且过职能门。
  return units.every((unit) =>
    unit.some(
      (term) =>
        containsTerm(titleText, term) ||
        (bodyAllowed &&
          !isTitleOnlyAnchor(term) &&
          (containsTerm(companyText, term) ||
            (!isBodyWeakTerm(term) && containsTerm(contentText, term)))),
    ),
  );
}

function normalizeChinaCity(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  const normalized = normalizeForMatch(raw);
  if (CITY_ALIASES.has(normalized)) return CITY_ALIASES.get(normalized);
  if (CITY_ALIASES.has(raw)) return CITY_ALIASES.get(raw);

  for (const [alias, city] of CITY_ALIASES.entries()) {
    if (normalized.includes(normalizeForMatch(alias))) return city;
  }

  return raw;
}

// 供城市筛选调用：省份/区域展开为可匹配的主城市；普通城市仍只返回自身规范名。
// 不修改 normalizeChinaCity，避免把岗位的原始 location 归一为多个城市。
function expandChinaCityTargets(value) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  const targets = CHINA_CITY_REGION_EXPANSIONS.get(normalizeForMatch(raw));
  return targets ? [...targets] : [normalizeChinaCity(raw)];
}

// 反向别名索引：canonical 规范名 → 其全部别名 token 集合（含中英/拼音，均 normalizeForMatch 小写）。惰性构建一次。
let _cityAliasReverse = null;
function cityAliasReverse() {
  if (_cityAliasReverse) return _cityAliasReverse;
  const m = new Map();
  for (const [alias, canonical] of CITY_ALIASES.entries()) {
    if (!m.has(canonical)) m.set(canonical, new Set());
    m.get(canonical).add(normalizeForMatch(alias));
    m.get(canonical).add(normalizeForMatch(canonical));
  }
  _cityAliasReverse = m;
  return m;
}

// 返回与筛选城市等价的【全部】匹配 token（规范名 + 所有别名，含中英/拼音；均 normalizeForMatch 小写）。
// 治 normalizeChinaCity 单向归一 → 筛「北京」漏掉 location="Beijing" 的岗（双向匹配）。调用方用
// `hay.some(includes)` 判 location 是否命中任一 token（hay 亦需小写 + 折叠空白）。
function cityMatchTokens(city) {
  const raw = String(city || "").trim();
  if (!raw) return [];
  const set = new Set([normalizeForMatch(raw)]);
  for (const target of expandChinaCityTargets(raw)) {
    const canonical = normalizeChinaCity(target);
    set.add(normalizeForMatch(canonical));
    const aliases = cityAliasReverse().get(canonical);
    if (aliases) for (const a of aliases) set.add(a);
  }
  return Array.from(set).filter(Boolean);
}

function normalizeChinaLocation(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;

  const separators = /[,，、/|;；]+/;
  let recognizedAny = false;
  const parts = raw
    .split(separators)
    .map((part) => {
      const clean = part.trim();
      const normalized = normalizeChinaCity(clean);
      // 海外城市只用于匹配、不改写显示：原样保留英文地名（"San Francisco" 不翻成 "旧金山"）。
      if (OVERSEAS_CITY_CANONICALS.has(normalized)) return clean;
      const recognized =
        CITY_ALIASES.has(clean) ||
        CITY_ALIASES.has(normalizeForMatch(clean)) ||
        normalized !== clean;
      if (recognized) recognizedAny = true;
      return normalized || clean;
    })
    .filter(Boolean);
  const unique = Array.from(new Set(parts));

  return recognizedAny && unique.length > 0 ? unique.join("、") : raw;
}

function normalizeChinaJobType({ title, sourceType, url, summary } = {}) {
  const text = normalizeForMatch([title, sourceType, url, summary].filter(Boolean).join(" "));

  if (/暑期实习|summer(?:\s+[0-9]{4})?\s+intern(?:ship)?s?\b/.test(text)) return "暑期实习";
  if (/日常实习|daily\s+intern(?:ship)?s?\b|off-?cycle\s+intern(?:ship)?s?\b/.test(text)) return "日常实习";
  if (/管培生|管理培训生|graduate\s+program|management\s+trainee/.test(text)) return "管培生";
  if (/留学生|海外学生|overseas student|returnee/.test(text)) return "留学生专项";
  // 英文 intern/graduate 必须用**词边界**：否则 "internal/international/internet" 会把全职岗误判成实习，
  // "undergraduate" 会误判成校招（本次线上 Intel 全职高级工程师因 JD 含 "internal" 被标实习的真因）。
  if (/实习|\bintern(?:ship)?s?\b|shixi/.test(text)) return "实习";
  // 校招只认**强标记**。刻意砍掉弱词「毕业生」("985毕业生优先"多为社招) 和「graduate」(=硕士学历) ——
  // 这两个在整段 JD 正文里高频误命中，是"社招被误标校招"的写入端源头（见 recruitmentCategory 同款收紧）。
  // 保留 campus / xiaozhao：它们既是 url 渠道信号、也是 discovery 的输入别名（campus→校招），中文正文极少出现。
  if (
    /校招|校园招聘|应届|[0-9]{2,4}届|campus|new\s+grads?\b|university\s+graduate|entry[-\s]?level|xiaozhao/.test(text)
  ) {
    return "校招";
  }
  if (/投研|研究员|研究岗|行业研究|股票研究|equity research|investment research/.test(text)) {
    return "研究岗";
  }
  if (/兼职|part time|part-time/.test(text)) return "兼职";
  if (/社招|社会招聘|experienced|professional|full time|full-time/.test(text)) return "社招";
  if (/\b(senior|staff|principal|lead|distinguished)\b/.test(text)) return "社招";
  if (/全职/.test(text)) return "全职";

  return null;
}

// 把细粒度 job_type / 标题归并到三大招聘类型桶之一（社招 / 校招 / 实习），用于前端筛选。
// 必须穷尽：每个岗位都落到唯一一个桶。分层设计见 recruitmentCategory 注释。

// 从文本抽【明确要求的工作经验年限下限】。只匹配带经验语境的写法（N年以上 / N-M年 / N年…经验 /
// N+ years），避开"2024年 / 成立3年 / 3年制 / 3年级"等噪声。返回数字下限，无则 null。
// 用途：校招=应届0经验、实习=在校生，任何"≥2年经验硬要求"都与之矛盾 → 是判定社招的权威信号。
// 岗位**写明数字**的经验年限下限（中文「N年…经验」语境 / 英文 N years）；没写数字返回 null。
// 与下面 _minRequiredExperienceYears 的区别：这里不含 senior/staff/lead 这类资历词代理——
// 推翻一个租户级的「实习频道」声明（recruitmentCategory 层2b）只认这一种证据。
function _statedExperienceYears(text) {
  if (!text) return null;
  const t = String(text).toLowerCase().replace(/\s+/g, "");
  // 中文年限：**必须落在「经验/经历/从业」语境里**才算硬门槛。
  // 旧实现的 /(\d{1,2})[-~至到](\d{1,2})年/ 与 /(\d{1,2})年以上/ 不看上下文，把校招 JD 里
  // 高频的成长路径/派驻时长当成了经验要求，导致明确的校招岗被层2 强制判成社招：
  //   「管培生培养计划，2~3年晋升为管理者」「通过 2-3 年的配套加速培养机制成长为…」
  //   「选拔绩优的校招生…优秀者 2-3 年发展成为主管」「需要派往墨西哥工作 3-5 年」
  // 2026-08-07 实测：moka 校招门户样本里 13 个被层2 判社招的岗，11 个是这类误判。
  // 窗口取 ±25 字而非更窄：「2 年以上在实验室硬件或软件设计开发经验」里"经验"离年限 16 字远，
  // 窗口太窄会把真·经验要求漏掉 → 社招岗被判校招。方向上遵循本模块的总原则
  // 「宁可漏判一个校招，也别把社招误标成校招」，所以宁可放宽窗口。
  // ⚠️ 数字前必须有非数字边界 `(?<![0-9])`（2026-09-18 加）：没有它，「2026年应届生…有实习经验优先」
  // 会从 `2026年` 里咬出 `26年`、「2027年后毕业的在校生」咬出 `27年`，把写明应届的岗判成 26 年经验的社招。
  // 全库这种「≥3 位数字+年」落在经验语境里的行只有 159 行，改前/改后逐行对拍见提交说明。
  for (const hit of t.matchAll(/(?<![0-9])(\d{1,2})(?:[-~至到]\d{1,2})?年(?!级)(?:以上)?/g)) {
    const around = t.slice(Math.max(0, hit.index - 25), hit.index + hit[0].length + 25);
    if (/经验|经历|从业/.test(around)) return parseInt(hit[1], 10);
  }
  const m =
    t.match(/(\d{1,2})[-~to]+(\d{1,2})years?/) || // 3-5 years
    t.match(/(\d{1,2})\+?years?(?:ofexperience)?/); // 5+ years / 5 years
  return m ? parseInt(m[1], 10) : null;
}

function _minRequiredExperienceYears(text) {
  if (!text) return null;
  const stated = _statedExperienceYears(text);
  if (stated !== null) return stated;
  // 没写数字时用英文资历词做代理（Staff / Senior / Lead Engineer 这类标题）。
  const raw = String(text).toLowerCase();
  if (/\b(principal|distinguished)\b/.test(raw)) return 12;
  if (/\b(staff|lead)\b/.test(raw)) return 8;
  if (/\bsenior\b/.test(raw)) return 5;
  if (/\b(mid[-\s]?level|intermediate)\b/.test(raw)) return 3;
  if (/\b(entry[-\s]?level|junior)\b/.test(raw)) return 0;
  return null;
}

// 岗位是否硬要求 ≥2 年工作经验（→ 绝不可能是校招/实习）。阈值取 2 而非 1：
// 校招/实习几乎不会要求 ≥2 年经验，误纠概率近 0；用户反馈的"3年经验"完全覆盖。
function _demandsPriorExperience(job = {}) {
  const years = _minRequiredExperienceYears(
    [job.title, job.experience, job.summary].filter(Boolean).join(" "),
  );
  return years !== null && years >= 2;
}

// 同上，但只认岗位**写明数字**的年限（不认 senior/staff/lead 资历词代理）。见 recruitmentCategory 层2b。
function _statesPriorExperience(job = {}) {
  const years = _statedExperienceYears([job.title, job.experience, job.summary].filter(Boolean).join(" "));
  return years !== null && years >= 2;
}

// 来源自报的招聘类型：只看 job_type 字段**本身**（不掺标题/正文），来源渠道 / 结构化 recruitType
// 落到这里最可信。job_type 是"招聘类型"取值时返回桶；是职能/类别（如"人力资源""管理类""研发"）→ null。
function sourceDeclaredCategory(jobType) {
  const t = String(jobType || "").trim();
  if (!t) return null;
  // intern 必须**两侧**词边界：`\bintern` 只有左边界，internal / international / internet 全会命中。
  // 中文「实习」是 CJK 无此问题。同款坑 2026-09-02 在 crawler/normalizer.extract_job_type 上
  // 实锤过——那里裸子串把 27,824 个在招岗标成实习（Stripe "internal tools" / 汇丰
  // "international banking"），这里是同一条链路的读时防御。
  if (/实习|\bintern(?:ship)?s?\b/i.test(t)) return "实习";
  if (/社招|社会招聘|全职|experienced|professional|full.?time/i.test(t)) return "社招";
  if (/校招|校园招聘|应届|管培生|管理培训生|留学生专项|campus|new\s+grad|university\s+graduate|entry[-\s]?level/i.test(t)) {
    return "校招";
  }
  return null;
}

// 标题/正文里的**强**校招标记（会自报家门的：应届 / 20XX届 / 校园招聘 / 管培生 / new grad）。
// 刻意不含弱词：光秃秃的"毕业生"("985毕业生优先"多为社招)、"graduate"(=硕士学历)、"校园"(=智慧校园产品) ——
// 这些在整段 JD 正文里高频误命中，正是"社招被误标校招"的根因。
function hasStrongCampusSignal(text) {
  return (
    /应届|[0-9]{2,4}届|校园招聘|校招|管培生|管理培训生|留学生专项/.test(text) ||
    /new\s?grads?\b|university\s+graduate|entry[-\s]?level|campus\s?(?:recruit|hiring)|graduate\s+program/i.test(text)
  );
}

// 实习标记（标题/url 优先，正文里的"实习经历"不算 → 避免社招岗误判）。
function hasInternSignal(text) {
  return /实习|shixi/.test(text) || /\bintern(?:ship)?s?\b/i.test(text);
}

const RECRUITMENT_CATEGORIES = new Set(["实习", "校招", "社招"]);
// 物化列 jobs.recruitment_category 的取值合法才认；NULL/脏值 → 走现算兜底。
function _materializedRecruitmentCategory(job) {
  const v = job && typeof job.recruitment_category === "string" ? job.recruitment_category : "";
  return RECRUITMENT_CATEGORIES.has(v) ? v : null;
}

// jd_url / apply_url 里的招聘渠道信号 —— **唯一一份**，recruitmentCategory（层1/层4）与
// hasExplicitRecruitmentType 共读。2026-09-18 live 实锤两份手抄正则会漂：层4 在 08-07 放宽了
// moka 的 `-recruitment` / `_apply` 后缀，hasExplicitRecruitmentType 那份没跟，结果 6,906 个只靠 url
// 判成校招的 moka 岗 recruitment_explicit=false，被 /jobs 校招筛选（要求 explicit and category）淘汰。
// 各条的取舍理由写在使用处的注释里，这里只放正则本身。
const URL_INTERN_PATH_RE = /\/(shixi|intern)(\/|\?|$)/i;
const URL_INTERN_POSTTYPE_RE = /[?&]postType=intern(?:s|ship)?\b/i;
const URL_INTERN_RECRUITTYPE_RE = /[?&]recruitType=12(?![0-9])/i;
const URL_CAMPUS_PORTAL_RE = /\/(xiaozhao|campus)([-_][a-z]+)?(\/|\?|$)/i;
const URL_SOCIAL_PORTAL_RE = /\/(social|experienced)([-_][a-z]+)?(\/|\?|$)/i;
const URL_CAMPUS_POSTTYPE_RE = /[?&]postType=campus\b/i;
const URL_CAMPUS_RECRUITTYPE_RE = /[?&]recruitType=1(?![0-9])/i;
const URL_RECRUITMENT_SIGNAL_RES = [
  URL_INTERN_PATH_RE,
  URL_INTERN_POSTTYPE_RE,
  URL_INTERN_RECRUITTYPE_RE,
  URL_CAMPUS_PORTAL_RE,
  URL_SOCIAL_PORTAL_RE,
  URL_CAMPUS_POSTTYPE_RE,
  URL_CAMPUS_RECRUITTYPE_RE,
];
// 任一 url 渠道信号命中 = recruitmentCategory 不会走层7 兜底（层1/层4 各自会用其中一条短路）。
function hasUrlRecruitmentSignal(url) {
  return URL_RECRUITMENT_SIGNAL_RES.some((re) => re.test(url));
}

// 招聘类型分层判定（从最可信到兜底）。核心认知：校招/实习是"会自报家门的特殊招聘"，社招是"未标记的默认态"。
// 因此策略 = 精度优先：只在有**强/可信信号**时判校招/实习，其余一律默认社招；宁可漏判一个校招，
// 也别把社招误标成校招（假校招更坑求职者）。
function recruitmentCategory(job = {}) {
  // 物化列优先（2026-09-17）：jobs.recruitment_category 由入库时的这同一套规则算好（分类所有权归数据库，
  // 见 CLAUDE.md「校招专区首屏」第 7 条）。读路径再用**截断的** 300 字摘要重算，会和列打架——
  // 线上实锤：/today 给社招岗写「校招岗位」理由，而卡片徽标（读列）显示社会招聘。有列就认列，NULL 才现算。
  const materialized = _materializedRecruitmentCategory(job);
  if (materialized) return materialized;
  const title = String(job.title || "");
  const summary = String(job.summary || "");
  const url = String(job.jd_url || job.apply_url || "");
  const company = String(job.company || "");

  // 层1：标题自报「实习·intern」—— **岗位级**声明，最权威。只认标题不认正文（"实习经历"是社招 JD 常见词）。
  // 渠道级的实习信号（源 job_type / url 通道 / 查询参数）**不在这一层**，见层2 之后的「层2b」：
  // 它们是租户对整个频道的声明，会被个别租户挪作他用，必须让位给岗位自己写的经验要求。
  if (hasInternSignal(title)) return "实习";

  // 渠道自报的实习信号（判定放在层2b，这里先算出来给层2 用）。
  const channelIntern =
    sourceDeclaredCategory(job.job_type) === "实习" ||
    URL_INTERN_PATH_RE.test(url) ||
    URL_INTERN_POSTTYPE_RE.test(url) ||
    URL_INTERN_RECRUITTYPE_RE.test(url);

  // 层2：明确要求 ≥2 年经验 → 强制社招。校招=应届0经验，与之矛盾。优先级高于源 job_type：
  // 治"源头把资深岗错标校招"（如光刻主任工程师 job_type=校招 但要 8 年）。
  // ⚠️ 对渠道自报实习的行，只认**写明数字**的年限（_statesPriorExperience），不认资历词代理：
  // 2026-09-18 全集对拍，把渠道实习挪到本层之后时，8 行是只靠正文里的 staff / lead / senior 翻成社招的，
  // 其中中金「【2027】人力资源岗」("staff development")、日立「Entry Program」("employs 1,900 staff")、
  // 美敦力「IT_Intern」("lead with purpose") 是明明白白的实习岗。资历词是给英文标题用的代理，
  // 推翻一个租户级声明必须拿岗位自己写的数字。
  if (channelIntern ? _statesPriorExperience(job) : _demandsPriorExperience(job)) return "社招";

  // 层2b：渠道自报的实习 —— 源 job_type 写着实习 / url 走 /shixi|intern 通道 / wecruit `postType=intern` /
  // 老版 wt `recruitType=12`。信号本身可信（是门户自己声明的渠道，与路径令牌同级），但它是**租户级**的：
  // 2026-09-18 live 实锤两家租户把 wt 平台的 recruitType=12（门户导航上就叫「实习生招聘」）当蓝领社招频道用——
  // 中伟新材料 64 行（电工 3 年 / 钳工 3-5 年 / 投资高级经理 8 年）、浙江华友钴业 18 行（仓管员「仓储经验 3 年以上」/
  // 保安 / 生产操作工），标题自带「实习」的比例 1.6% / 0%，正常租户 60~100%。这些信号此前与标题同在层1、
  // 抢在层2 之前拍板，经验门对这条路径完全失效：rt=12 且 experience 写着 ≥2 年的 23 个在招岗全部标成实习。
  // 挪到层2 之后 = 岗位自己写的「≥2 年经验」压过频道声明；没有经验要求的照旧判实习。
  // 🚫 别把它们挪回层1「省事」：全集验收见 tests/recruitment-category.test.js 同名用例与提交说明的迁移矩阵。
  //
  // wecruit/hotjob 系（career.honor.com / *.hotjob.cn …）的渠道写在查询参数里：
  // `posDetail.html?postId=…&postType=campus|intern|society`，不是路径段。2026-09-09 live 全库对拍：
  // postType=campus 的 3,757 个在招岗里 700 个（21 家公司）被兜底成「社招」、postType=intern 有 40 个——
  // 荣耀应届生门户 93 岗进库后 91 个判成社招就是这么来的。
  // 老版 wt（WinTalent，`*.hotjob.cn` 等）把渠道写成**数字常量** `recruitType=`：1=校招 / 2=社招 / 12=实习
  // （平台常量，非每公司配置，见 crawler/adapters/wt.py 顶部注释），而且这个值就在 jd_url 里。
  // 为什么 job_type 已经带标签了还要认 URL：`job_type` 是 adapter 拼出来的**可变派生字段**
  // （wt.py 的 _RT_CATEGORY_LABEL 把「校园招聘/实习」拼在职能类别后面），一旦那步回退 / 源停抓 /
  // 老代码写进来的旧值被 _PRESERVE_IF_EMPTY 保留，结论就**静默**退回层7 的「社招」——不报错、没人知道。
  // jd_url 里的 recruitType 是 canonical 身份的一部分、不会漂。2026-09-18 live 全库实测：rt=1 的
  // 5,373 个在招岗里仍有 83 行 job_type 不带标签（固德威 31 行自 08-11 起没再抓过，28 行判成社招），
  // 这就是同一个失效模式当场发生的样子。
  // ⚠️ `1` 后面必须跟否定数字前瞻，否则 `recruitType=12`（实习）会被当成 `1`（校招）。
  if (channelIntern) return "实习";

  // 层3：信任来源自报的 job_type（结构化 recruitType/渠道最可信，且此处只看字段本身不被正文污染）。
  const declared = sourceDeclaredCategory(job.job_type);
  if (declared) return declared; // 到这里 declared ∈ {校招, 社招}（实习已在层2b 拍板）

  // 层4：url 路径里的招聘门户信号（北森/百度等 ATS 明确分 /campus 与 /social 两个门户 → 权威）。
  // 对称处理：/campus|/xiaozhao → 校招；/social|/experienced → 社招。放在正文强标记之前：
  // 治"社招门户里正文写了'应届亦可'被误判校招"（实测 beisen /social 门户 ~3000 岗中招）。
  //
  // ⚠️ 门户令牌后允许一段 -/_ 后缀（`([-_][a-z]+)?`）：moka 的门户路径是
  // `/campus-recruitment/`、`/campus_apply/`、`/social-recruitment/`，旧正则要求令牌后紧跟
  // `/ ? $`，对 moka **整个层4 失效**。社招那侧碰巧被层7 兜底成社招所以没露馅，校招这侧
  // 就成了漏判：2026-08-07 实测 moka 校招门户 5525 个在招岗里 31.6% 被兜底成「社招」，
  // 进不了校招专区（抽样 474 个漏判岗中，要求工作年限的 **0 个**，正文清一色
  // 「本科及以上学历 / 相关专业毕业 / 有学生干部经历或实习经验者优先」= 标准校招 JD）。
  // 安全性：层2（≥2 年经验强制社招）在本层之前，所以放宽这里不会让资深岗被误标校招。
  if (URL_CAMPUS_PORTAL_RE.test(url)) return "校招";
  if (URL_SOCIAL_PORTAL_RE.test(url)) return "社招";
  // wecruit 查询参数渠道（见层1 注释）。⚠️ 刻意**不**对 postType=society 对称判社招：社招本来就是层7 默认态，
  // 加这条只会压掉社招门户里标题写明「2026届 / 27届」的 120 个岗（隆基 / TCL 把校招岗挂在社招门户），
  // 2026-09-09 全库 15,153 行对拍：不加它 → 校招→社招 0、实习→社招 0，改动纯增量（社招→校招 674、→实习 96）。
  if (URL_CAMPUS_POSTTYPE_RE.test(url)) return "校招";
  // 老版 wt 的数字渠道常量（见层1 注释）。放层4 而不是层1 = 让层2（≥2 年经验）先拍板，
  // 与 postType=campus 同层、也与 wt.py 把「校园招聘」写进 job_type 后走层3 的路径同层。
  // ⚠️ 诚实边界：层2 对 wt 只兜住一半。2026-09-18 全库实测 rt=1/12 里 experience 字段整体写着
  // 「≥2 年」的 34 行，层2 只判出 17 行社招 —— 因为 _minRequiredExperienceYears 要求年限落在
  // 「经验/经历/从业」语境里，而 wt 的 experience 常是裸值「3-5年」「5年」。另 21 行标题带资深词的
  // 只兜住 5 行，但那 16 行多数**本来就是真校招**（国机集团 8 个「高级研发工程师」exp=应届/不限、
  // 中国五矿「【27校招】高级研发工程师」exp=无经验 —— 「高级」是职级不是资历要求）。
  // 要让裸年限也算硬门槛得改层2 本身，影响所有源、需单独立项，本次刻意不动。
  // 🚫 **刻意不加 `recruitType=2 → 社招`**，与上面 postType=society 同一个理由，且有实测：
  // 全库 rt=2 的 13,201 个在招岗里，现在有 168 个判校招（TCL实业 46 / 中国一汽 17 / 长城汽车 17 /
  // 特变电工 15…，靠标题「XX届 / 应届」被层5 捞回来）、89 个判实习（层1 捞回来）。加这条 =
  // 层4 抢在层5 前面把那 168 个当场压回社招，收益 0（社招本来就是层7 默认态）。
  if (URL_CAMPUS_RECRUITTYPE_RE.test(url)) return "校招";

  // 层5：标题/正文的**强**校招标记（不含弱词，见 hasStrongCampusSignal）。
  if (hasStrongCampusSignal(`${title} ${summary}`)) return "校招";

  // 层6：公司名显式标注（如库里的"华润电力 CR Power 校招"）。
  if (/实习/.test(company)) return "实习";
  if (/校招|校园招聘/.test(company)) return "校招";

  // 层7：兜底 —— 无任何标记 = 社会招聘（社招是默认/未标记状态，统计上是大头）。
  return "社招";
}

// 岗位是否带【明确的】招聘类型信号（标题/JD/job_type 能判出 实习/校招/社招/全职 等具体桶）。
// 用途：前端筛选区分「明确不符」与「信息不足」。recruitmentCategory 对无信号岗位兜底成「社招」，
// 若据此硬筛会把大量「类型未知」岗（实测库里 job_type ~94% 为空）误杀 → 信息不足时应放行而非淘汰。
function hasExplicitRecruitmentType(job = {}) {
  // 与 recruitmentCategory 同款：物化列 recruitment_explicit 有值就认列（与 recruitment_category 同一次写入）。
  if (_materializedRecruitmentCategory(job) && typeof job.recruitment_explicit === "boolean") {
    return job.recruitment_explicit;
  }
  // 与 recruitmentCategory 的"非兜底"信号集对齐：任一可信信号命中即算"明确"（≥2年经验 / 源 job_type /
  // url 渠道 / 标题实习 / 强校招标记 / 公司名标注）。刻意不再扫正文弱词，避免"毕业生优先"把社招岗当校招硬筛。
  if (_demandsPriorExperience(job)) return true;
  if (job.job_type) return true; // 源给了 job_type（哪怕是职能类别）→ 视为有据，保持既有筛选行为
  const url = String(job.jd_url || job.apply_url || "");
  if (hasUrlRecruitmentSignal(url)) return true; // 与层1/层4 同一份正则（见 URL_RECRUITMENT_SIGNAL_RES）
  if (hasInternSignal(String(job.title || ""))) return true;
  if (hasStrongCampusSignal(`${job.title || ""} ${job.summary || ""}`)) return true;
  const company = String(job.company || "");
  return /实习|校招|校园招聘/.test(company);
}

// 非软件工程降级门专用：词表刻意宽于生产制造，职责只是「绝不让传统工程/医疗靠泛工程师进软件研发」。
// 基底来自 HEAD 原词表，合并本轮新增制造词；结构/管道/技术文档等无上下文可留「其他」，但绝不能判研发。
const NON_SOFTWARE_ENG_DOMAIN =
  /机械|机电|机加|钣金|工艺|化工|化学(?!习)|材料|冶金|铸造|锻造|焊接|焊工|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|热处理|土木|结构工程|岩土|暖通|给排水|管道|强电|工业工程|生产工艺|制造工艺|工艺技术|纺织|印染|涂装|总装|冲压|车身|底盘|发动机|动力总成|整车|工业自动化|机械自动化|热设计|散热|结构设计|精密仪器|仪器仪表|光学|镜头|声学|射频|天线|电源|电池|电芯|储能|逆变|试剂|生物|医疗器械|临床|药物|制药|检测认证|可靠性|环境试验|工业设计|包装设计|技术文档|标准化|生产|制造|车间|产线|装配|组装|操作工|技工|班组长|工段|钳工|电工|铣工|车工|设备维护|设备维修|保养|production|manufactur\w*|assembler|operator|machinist|technician|maintenance|fabrication|welding|tooling|transmission|mechanic|质量|品控|(?<![产样用物])品管|(?<!性)质检|检验员|(?<!性质)检测|ehs|环保|安全员|职业健康|\bqa\b|\bqc\b|\bsqe\b|quality|safety|inspection/i;

// 生产制造归类专用：只放官方字典归属制造的传统工程、产线与质量安全词，不含土木/临床/生物医药。
const MANUFACTURING_DOMAIN =
  /生产|制造|车间|产线|装配|组装|操作工|技工|班组长|工段|钳工|电工|焊工|铣工|车工|设备维护|设备维修|保养|production|manufactur\w*|assembler|operator|machinist|technician|maintenance|fabrication|welding|tooling|机械|机电|机加|钣金|工艺|化工|化学(?!习)|材料|冶金|铸造|锻造|焊接|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|热处理|纺织|印染|涂装|总装|冲压|车身|底盘|发动机|动力总成|整车|电气|自动化|强电|仪器仪表|热设计|散热|射频|天线|电源|电池|电芯|储能|逆变|光学|镜头|声学|精密仪器|工业工程|生产工艺|制造工艺|工艺技术|工业自动化|机械自动化|包装设计|标准化|检测认证|环境试验|transmission|mechanic|质量|品控|(?<![产样用物])品管|(?<!性)质检|检验员|可靠性|质量体系|管理体系|体系工程师|体系专员|体系认证|认证|(?<!性质)检测|ehs|环保|安全员|职业健康|\bqa\b|\bqc\b|\bsqe\b|quality|safety|inspection/i;

// 岗位职能粗分类（产品/研发/设计/数据/运营/市场/销售/供应链/职能/其他），用于岗位卡片的强特征标签。
// 「最靠后命中」优先，不再是「规则表顺序优先」——见 _classifyFunctionText 的注释。
// 规则内部仍保持「更具体的写在前面」，用于同结束位置时的平局决胜。
const JOB_FUNCTION_RULES = [
  // 角色锚定：只在明确的产品角色词命中（删掉裸词"产品"/"产品设计师"），
  // 否则"产品研发/产品测试/硬件产品工程师"等会被裸词误吃成产品（研发信号本应优先）。
  // 英文补充 director/head/vp of product 这类头衔式写法（外企 ATS 常见，旧规则只认 product manager）。
  ["产品", /产品经理|产品策划|产品负责人|产品总监|产品专家|产品实习生|产品助理|产品专员|产品企划|product\s*manager|product\s*owner|product\s*lead|(?:director|head|vp|vice\s*president)[,\s]+(?:of\s+)?product/i],
  // 项目/交付是独立职能：PM/PO 在英文岗位里还会表示上午下午、预防性保养等，故意不收裸 \bpm\b。
  // 也不收「工程项目」等泛词，避免把土建/制造项目误打成项目管理。
  // 「项目专员 / 项目助理」是国内 PMO 条线最常见的初级写法（体检里用户手填 2 次，库里 25 个岗），
  // 旧规则只认经理/主管/总监级，把它们全落进「其他」。仍不收裸「项目」（会吃掉土建/制造项目）。
  ["项目管理", /项目经理|项目管理|项目主管|项目总监|项目负责人|项目专员|项目助理|交付经理|交付总监|\bpmo\b|project\s*manager|program\s*manager|delivery\s*manager|technical\s*program\s*manager|\btpm\b/i],
  // ux 只认词首（UX / UXD / UXCD / UXUI）加显式的 UI/UX、3D UX：旧的裸 `ux` 吃进 linux / Wuxi / Benelux / Sioux /
  //   luxe / auxiliary / 法语 travaux·niveaux —— 2026-09-23 全量对拍（44,152 个候选）：正文里的 Linux 让 336 个
  //   在招岗被正文兜底判成设计，标题里「嵌入式Linux开发」「Process Engineer-Wuxi」按最靠后命中也被抢成设计。
  //   不能两边都卡边界：「UIUX」「XR3DUX设计」「UXCD」是真设计岗（第一版这么写过，当场丢了它们）。
  // 「美工」是国内中小企业对视觉设计岗的通用叫法；建模/原画属美术设计条线。
  // 刻意不收裸「建模」——「数据建模 / 财务建模」不是设计。
  ["设计", /视觉设计|交互设计|ui\s*设计|(?<![a-z0-9_])ux|(?:ui|3d)\s*[/&+]?\s*ux|平面设计|设计师|美工|美术设计|原画|三维建模|3d\s*建模|建模师|blender|designer/i],
  // 补 business analyst（英文 BA 的标准写法，旧规则只有中文「商业分析」）与数据中台/数仓条线。
  ["数据", /数据分析|数据科学|数据工程|大数据|数据挖掘|数据中台|数据仓库|数仓|数据治理|data\s*(analyst|scien|engineer)|business\s*analyst|\bbi\b|商业分析/i],
  // 研发拆成「具体方向词」和下面的「泛工程后缀」两条，后者标 generic —— 见 _classifyFunctionText。
  // 英文裸 architect 在香港库实测 1915 个且压倒性是 IT 架构师，归研发；代价是极少数 Construction Project Architect
  // 也会归研发，以少数漏判换掉大规模误判。architectural / landscape architect 留给下方建筑工程。
  // 网络安全/IC 验证是两个被整条漏掉的研发方向（体检里用户手填「网络安全」2 次、「ic验证」「数字 IC 验证」各 1 次）。
  // ⚠️ 刻意不收裸「安全」「安全工程师」：库里「安全员 / 安全管理岗」压倒性是 EHS（生产制造），
  //    只收把语境写死的复合词；同理 IC 侧不收裸 `ic`（两字母子串误伤面太大）。
  ["研发", /算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|网络安全|信息安全|网络空间安全|安全攻防|渗透测试|cyber\s*security|infosec|ic\s*验证|ic\s*设计|数字ic|模拟ic|芯片设计|soc\s*设计|\barchitect\b|\bsde\b|\bsre\b|programmer|software|软件/i],
  // 化学 / 药物合成类研发（2026-09-23 创始人拍板「有机合成研究员算研发」）：此前「有机合成研究员」归生产制造、
  //   「药物合成研究员」归医疗健康、「多肽合成研究员」判不出，而「研发工程师（有机合成方向）」是研发 ——
  //   同一类岗三个桶，方向填「有机合成研究员」的用户被职能门挡掉一半对口岗。
  //   只收合成学科词（有机/药物/化学/多肽/核酸…合成、药物化学）与「X合成研究员 / 科研员 / 科学家」：
  //   🚫 不收裸「合成」——「合成数据 / 语音合成 / 3D 内容合成」是 AI 方向；
  //   真生产岗靠「最靠后命中」留在生产制造：「有机合成车间主任」「合成工艺技术员」「合成一装置外操」末尾的角色词更靠后。
  //   工艺岗按创始人口径不带进研发，两种语序都要挡：「合成工艺研究员」靠末尾的工艺，「工艺合成研究员」靠 `(?<!工艺)`
  //   （不加时 301 行全量对拍里「工艺合成研究员」「化学工艺合成研究员」「创新工艺合成科学家」被判研发、与前者不一致）。
  //   explicitDomain：学科词本身就是研发语境，跳过下方「传统工程无软件信号不许进研发」那道护栏
  //   （「药物化学研究员」「化学合成研究员」含 化学/药物，不跳过就永远进不了研发）。
  ["研发", /(?:有机|药物|化学|化药|药化|多肽|核酸|寡核苷酸|液相|固相|adc)\s*合成|(?<!工艺)合成(?:高级|助理|资深|首席)?(?:研究员|科研员|科学家)|药物化学|(?:medicinal|synthetic|organic)\s*chemist\w*/i, { explicitDomain: true }],
  // 具体软件研发之后、泛「工程师」之前：BOSS/智联把传统工程和质量安全归生产制造；放晚了会被工程师抢进研发。
  ["生产制造", MANUFACTURING_DOMAIN],
  // 电厂 / 车间 / 4S 店的一线岗位条线：库里 active「其他」里这几类各几十上百个岗（集控运行、热控检修工、
  // 服务维保技师、普工、化验员…）。技师只收写死语境的复合词——裸「技师」在美容/按摩里是服务业岗位。
  // 「实验员」**不带**领域前缀排除（2026-09-18 撤掉 09-17 加的 `(?<!药理|药物|医学|中药|临床|生物|毒理|动物|筛选|检验|发现)`）：
  //   角色词决定职能，领域前缀不能把同一个角色拆进不同桶。那张排除表把全库 118 个 active「实验员」岗拆成
  //   生产制造 95 / 医疗健康 12 / 其他 11 —— 康缘药业同一场南京校招里「药物筛选实验员--功效物质筛选」判医疗健康、
  //   「中药功效物质实验员」判生产制造；表里的 生物/动物/筛选/检验 在医疗健康规则里根本没有对应词，
  //   「分子生物实验员」「动物实验员」直接掉进「其他」。后果：方向填「实验员」的用户（职能集 = {生产制造}）被
  //   职能门拒掉标题字面就是「实验员」的岗（真实画像实测：5 个康缘南京校招岗全拒，推荐页只剩 5 张）。
  //   现行口径与兄弟角色词一致：化验员 / 检验员 / QC 都是「角色词赢」→ 生产制造（「原料药QC实验员」早就是）。
  //   双向代价：方向只落在医疗健康的用户从此拿不到「药理实验员」（44 个真实画像里没有这样的人；唯一含医疗健康的
  //   画像同时含生产制造）。回归钉在 tests/classify-job-function.test.js。
  ["生产制造", /检修|巡操|集控|普工|维保|(?:维修|设备|机修|喷漆|钣金|安装)技师|实验员|化验员|设备管理|设备主管|精益|(?<!网络|信息)安全管理|安全生产|electrician|welder|mechatronic\w*|robotics\s*tech/i],
  // 仅认建筑语境：裸结构/强电/工程部等在生产库大量属于机械、电气和通用工程部门，不能再放这里。
  // 补：资料员（建筑「八大员」之一，用户手填过）、消防/暖通安装条线（fire alarm / sprinkler / HVAC）。
  ["建筑工程", /建筑师|钢结构|混凝土|建筑结构|水工结构|桥梁|土木|土建|道路|隧道|市政|岩土|勘察|暖通|给排水|供变电|幕墙|装饰|(?<![实设])施工|监理|造价|预算员|资料员|建筑设计|(?:高速|公路)\s*项目|architectural|landscape\s*architect|construction|site\s*engineer|civil\s*engineer|\bhvac\b|sprinkler|fire\s*(alarm|detection)/i],
  // 泛工程后缀（generic）：**位置必须留在这里**（紧跟具体研发词、排在运营/市场之前）。
  //   标题层（preferLast=true）跑两轮，第一轮跳过它 → 具体职能词优先，治「大数据开发工程师」
  //   「Data Engineer II」被末尾的「工程师 / Engineer」从「数据」抢进「研发」。
  //   正文兜底（preferLast=false）单轮按表顺序 → 它仍在原位当**拦截器**：JD 正文几乎都写
  //   「技术 / 开发」，命中这里判出研发后会被 classifyJobFunction 的正文兜底守卫挡回
  //   「其他」。挪到表末尾这道拦截就失效，正文里的「市场 / 运营」趁虚而入——实测挪走后有 340 个
  //   标题判不出职能的岗被正文误判成市场（Manager, Project Management / Lead Athlete 之流）。
  // 🚫 scientist / researcher / 研究员 试过、又撤了（2026-09-17 全库对拍）：加进来确实能捞回
  //    几百个裸 Scientist，但**净效果是负的** —— 英文标题只看第一个逗号前的部分，
  //    「Principal Scientist, Clinical Pharmacology」从此在逗号前就判出研发，不再退回整串看
  //    `pharmac*`，272 个药企科学家岗被从医疗健康抢走；中文侧「合成研究员（工艺）」剥掉括号后
  //    只剩「研究员」，同样把 83 个岗从生产制造抢进研发。捞回的和抢错的一个量级，不划算。
  ["研发", /工程师|研发|开发|技术|engineer|developer/i, { generic: true }],
  // 大模型训练 / 推理基础设施条线（2026-09-23）：「Agentic Post-training-阿里星」「AI Infra研究员」这类标题
  // 没有任何研发角色词（也没有工程师后缀）→ 判「其他」，正文兜底再被「招聘项目：…」判成「职能」，
  // 职能门对它们放行，产品经理画像的 /today 里出现训练基础设施岗、理由写「方向匹配：AI Agent」。
  // ⚠️ 必须是 generic（和上一条同理）：这些词在标题里常是**团队 / 业务线**而非角色——
  //    「AI产品经理-Dev Infra」「高招招聘专员-Infra与基座方向」「研发项目经理-大模型训练infra团队」。
  //    放进具体词那一轮，按最靠后命中会让末尾的 Infra 抢走真实角色（2026-09-23 全量对拍：15,679 个候选里
  //    产品 11 / 运营 2 / 项目管理 2 / 职能 3 个真岗被抢进研发）；generic 只在标题没有任何角色词时才说话。
  // 「强化学习」同族（2026-09-23 补）：此前它含的「化学」让「强化学习研究员」被判生产制造，化学改成 `化学(?!习)` 后
  //   这批岗落回「其他」，归到这里才算完。英文 reinforcement learning 暂未收（没有全量对拍过）。
  // 只收写死语境的复合词：
  // 🚫 不收裸 大模型 / llm / agent / 多模态 —— 领域不是角色；
  // 🚫 不收裸 训练 / 推理 —— 「AI训练师」是标注运营岗、「推理」有剧本杀策划；
  // infra 只认整词、不吃 infrastructure（基建 / 云基础设施的整词另有归属）。边界写成 ASCII 显式环视而不是 \b：
  //   JS 的 \b 本来就只认 ASCII（与此等价），但 crawler/china_keyword_expansion.py 同口径那条若写 \b，
  //   Python 会把汉字当单词字符 →「AI Infra实习生」在那边匹配不上，两端漂移。
  // 双向代价（同一次对拍，infra 单独贡献 114 行里约 12 行判错）：「1688-AI平台产品-Infra」「战略分析专家（AI Infra方向）」
  //   「投资专家-AI Infra」「AI infra GTM Specialist」「Infra Tech Business Dev」「Tech Infra Prog Mgr」这类
  //   角色词不在任何规则里的岗被判成研发。换来的是 AI Infra 实习生 / 研究员 / 负责人 这一整类不再对非研发画像放行。
  ["研发", /post[\s-]?training|pre[\s-]?training|后训练|预训练|强化学习|(?<![a-z0-9_])rlhf(?![a-z0-9_])|训练框架|训练引擎|推理框架|推理引擎|推理加速|推理优化|(?<![a-z0-9_])infra(?![a-z0-9_])/i, { generic: true }],
  // 「营运」是零售/餐饮对运营的通用叫法。
  // 🚫 裸「电商」试过、又撤了（2026-09-17 全库对拍）：它在中文标题里是**业务线**不是岗位名，
  //    而中文按「最靠后命中」判，业务线恰恰挂在末尾 —— 实测会把 690 个岗从正确职能抢进运营
  //    （「AI产品经理-抖音电商」→运营 125、「资深前端开发工程师-抖音电商」→运营 415…）。
  //    用户手填的裸「电商」因此仍判不出方向，这是**刻意的取舍**：别再把它加回来。
  ["运营", /用户运营|内容运营|运营|营运|电商运营|增长|operations|growth/i],
  ["市场", /市场|营销|品牌|公关|marketing|brand|\bpr\b/i],
  // 行业业务线放在销售之前：保险销售、课程顾问等按官方职位字典先归金融/教育；客户经理未纳入客服词表，仍归销售。
  // 补两类：① 外企药企的治疗领域代表写法（oncology / cardiovascular / 疫苗…），按「行业业务线先于销售」
  //    的既定口径归医疗健康；② 采血/急救/照护等一线医护岗。
  ["医疗健康", /医生|医师|护士|护理岗|临床护理|护理部|护理师|照护|药师|药剂|临床数据|临床|\bcra\b|\bcrc\b|\bcta\b|医学|医药|药物|制药|药品|药理|检验科|放射|影像|超声|口腔|中医|兽医|营养师|康复|理疗|\bmsl\b|医学事务|医疗器械|试剂|生物制药|生物医药|medical|clinical|nurse|pharmac\w*|physician|therapist|biolog\w*|pathology|oncolog\w*|cardiovascular|neuroscience|dermatolog\w*|vaccines?|therapeutic\s*area|rare\s*disease|phlebotom\w*|paramedic/i],
  // 旧规则有中文「银行」却没有英文 bank/banking（外企与港资行的岗位标题全是英文），
  // 财富管理条线（Wealth Relationship Manager / 财富顾问）同理整条漏掉。
  // 补「信用/市场/操作/全面风险」（2026-09-23）：券商/银行风险管理部的四类标准岗名。旧规则只认「风控/风险管理」，
  // 「市场风险管理岗」「市场风险实习生」被「市场」判成市场营销（6 例），其余三类判不出落「其他」。
  // 按「最靠后命中」，复合词结束位置晚于「市场」，自然胜出，不影响「风险策略运营」这类末尾是别的角色词的标题。
  // 补投行/并购条线（2026-09-18）：「投行」「承做」「承揽」是国内券商投行部门标准业务术语
  // （对应海外 IBD 的 origination/execution），旧规则里没有任何一个会命中，导致「投行业务岗
  // （先进制造方向）」这类标题剥掉括号修饰语后判不出职能、又跌回带括号的原始标题重判，被括号里
  // 的"制造"二字误判成生产制造（见 CHINA_KEYWORD_GROUPS 索引 46 投行组注释的库内证据）。
  ["金融业务", /柜员|综合柜员|理赔|查勘|核保|核赔|承保|信贷|信审|风控|风险管理|合规风控|信用风险|市场风险|操作风险|全面风险|投资|投研|精算|证券|保险|银行|理财|财富顾问|财富管理|资产管理|资管|基金|信托|外汇|清算|清算结算|资金结算|证券结算|跨境结算|反洗钱|信用卡|交易员|投行|并购|承做|承揽|teller|banker|\bbank(ing)?\b|mortgage|wealth\s*(management|relationship)|equity\s*research|fixed\s*income|capital\s*markets|underwrit\w*|actuar\w*|trader|trading|credit\s*analyst|investment/i],
  // 「教培」是用户手填的常见写法（音乐教培）。
  // 🚫 裸「培训」不收：库里 300+ 个「管理培训生 / 培训生」压倒性不是教培岗。
  // 🚫 裸「教育」试过、又撤了（同上全库对拍）：它是**行业**不是岗位，挂在标题末尾会抢走真实角色 ——
  //    实测「中级客户经理-教育」等 35 个销售岗被判成教育培训。
  ["教育培训", /教师|老师|讲师|教练|教研|助教|辅导员|班主任|教务|培训师|培训机构|教培|课程顾问|保育|幼师|teacher|instructor|tutor|faculty|professor|lecturer/i],
  // 客服服务不含「客户经理」：它是销售岗位，避免抢走既有销售规则。
  // 英文零售门店条线（Retail Store Associate / Store Manager / Visual Merchandiser）与
  // client service 系写法，旧规则只认 `retail associate` 一种，库里几百个岗落「其他」。
  // 「retail banking」「retail sales」不会被误吃——它们的 bank / sales 位置更靠后，按最靠后命中胜出。
  ["客服服务", /客服|客户服务|客户支持|售后|服务专员|服务顾问|话务|坐席|门店|店长|店员|导购|收银|领班|前台|接待|服务员|咖啡师|调茶师|运动顾问|零售|customer\s*service|customer\s*support|customer\s*success|front\s*desk|receptionist|barista|cashier|\bretail\b(?!\s*(platform|engineering|developer|architect|technolog|design))|store\s*(associate|manager|director|supervisor)|merchandiser|client\s*(service|support|associate|experience)|contact\s*cent(er|re)|service\s*associate/i],
  // 「业务拓展」是国内 BD 岗最常见的写法，旧规则只有「商务拓展」；
  // account executive / account manager 是英文招聘里销售岗的标准词（真实库实测大量落在「其他」）。
  // 「外贸」是国内外贸业务员岗最常见的写法（用户手填 2 次），旧词表整条没有。
  ["销售", /销售|商务拓展|业务拓展|渠道拓展|渠道经理|外贸|\bbd\b|sales|客户经理|business\s*development|account\s*(executive|manager)/i],
  // 补仓储一线（仓管/物控）、招投标（采购条线）、司机与英文 warehouse / buyer / sourcing 系。
  // ⚠️ 不收裸 driver：`Driver Development Engineer`（驱动开发）会被吃成供应链。
  ["供应链", /供应链|采购|物流|仓储|仓管|仓库管理|物控|物料管理|物料计划|招投标|招标专员|投标专员|司机|叉车|supply\s*chain|procurement|logistics|warehouse|\bbuyer\b|sourcing|material\s*(handler|planner)|customs\s*brokerage|forklift/i],
  // 英文补充：financial（旧规则的 finance 匹配不到 Financial Analyst）、hrbp（\bhr\b 的词边界卡在
  // HRBP 的 B 上）、talent acquisition / compliance / administrative —— 真实库里这几类全落「其他」。
  // 补：人事 / 文员 / 后勤（用户手填的常见写法，旧词表只有「人力资源 / 行政」）、英文 accountant。
  ["职能", /人力资源|人事|招聘|\bhr\b|\bhrbp\b|财务|会计|审计|税务|法务|法律|合规|行政|后勤|文员|秘书|finance|financial|account(ant|ing)|tax|legal|counsel|compliance|recruit|talent\s*acquisition|human\s*resources|administrative|executive\s*assistant|\badmin\b/i],
];

// 软件 / IT / 算法信号：命中其一则即使带工业标记仍判软件研发（机器人 / 自动驾驶 / 嵌入式软件等交叉岗）。
// 故意排除泛词 研发 / 开发 / 技术 / 工程师（它们正是误判来源），也排除过于常见的「数据」
//（真数据岗已由上方「数据」规则先行认领，无需在此兜底）。命中此正则 = 保守地「不降级」（维持原行为，安全方向）。
const SOFTWARE_ENG_SIGNAL =
  /软件|software|算法|algorithm|前端|frontend|front[\s-]?end|后端|backend|back[\s-]?end|全栈|full[\s-]?stack|客户端|服务端|嵌入式|固件|firmware|测试开发|自动化测试|sdet|运维|sre|devops|架构师|代码|编程|程序员|programmer|\bjava\b|python|golang|c\+\+|c#|\.net|javascript|typescript|\breact\b|\bvue\b|机器学习|machine\s*learning|深度学习|deep\s*learning|\bml\b|\bnlp\b|大模型|\bllm\b|\bai\b|人工智能|计算机视觉|\bcv\b|系统开发|平台开发|trading\s+systems?\s+engineer|web|\bapp\b|小程序|数据库|database|\bsql\b|云计算|区块链/i;

// 预编译成全局匹配版：_classifyFunctionText 要拿到「最后一次命中的位置」，需要 /g 反复 exec。
// 规则表本身不带 /g（它还被别处当普通 test 用），所以在这里各存一份，避免每次调用现构造。
const JOB_FUNCTION_RULES_GLOBAL = JOB_FUNCTION_RULES.map(([fn, re, opts]) => [
  fn,
  new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g"),
  Boolean(opts && opts.generic),
  Boolean(opts && opts.explicitDomain),
]);

// 对一段已 normalize 的文本跑职能规则（含非软件工业领域降级门）。判不出返回 "其他"。
//
// `preferLast` 决定多规则同时命中时谁赢，**标题传 true、正文兜底传 false**，两者不能混用：
//
// ▸ 标题（preferLast=true）取「最靠后命中」。中文岗位标题的信息顺序是
//   「公司-事业部-部门-岗位名」，部门名经常带着另一个职能的词：
//   「外运华东-水集事业部-物流分公司**市场销售部**销售代表」里「物流」（供应链）和「市场」
//   都排在真正的岗位名「销售代表」前面，顺序优先会把整条销售岗判成市场，塞进「品牌营销」
//   用户的看板。岗位名在末尾是中英文招聘标题的共同惯例，按结束位置取最靠后的最稳。
//
// ▸ 正文兜底（preferLast=false）保持「规则表顺序优先」。**位置在正文里没有语义**——
//   JD 末尾通常是任职要求/福利，谁排最后纯属偶然。2026-09-01 实测：正文也用最靠后命中会让
//   数据岗少判 1/3（600→398），`Firmware Security Systems Architect` 因为 JD 末尾提到采购
//   被判成供应链。这条边界是踩坑后加的，别为了「统一」把它抹平。
//
// preferLast 的平局规则（两条都不能少）：
//   ① 结束位置相同 → 取匹配更长的那条。「产品运营」里产品规则匹配到 4 个字、运营规则只匹配到
//      2 个字，都在同一位置结束 —— 更长的匹配更具体，判「产品」（保住既有行为）。
//   ② 长度再相同 → 取规则表里更靠前的（表内顺序仍然编码了「谁更具体」）。
function _classifyFunctionText(text, preferLast = false) {
  if (!text) return "其他";
  // 两轮：先只看具体职能词，全都没命中才让泛工程后缀（工程师 / engineer / 开发…）兜底。
  return _runFunctionRules(text, preferLast, false) || _runFunctionRules(text, preferLast, true) || "其他";
}

function _runFunctionRules(text, preferLast, useGeneric) {
  let best = null;
  for (let i = 0; i < JOB_FUNCTION_RULES_GLOBAL.length; i++) {
    const [fn, re, isGeneric, explicitDomain] = JOB_FUNCTION_RULES_GLOBAL[i];
    if (isGeneric !== useGeneric) continue;
    // 配套护栏①：传统工程仅靠泛词落入研发且无软件信号时，不能塌进软件研发。
    if (fn === "研发" && !explicitDomain && NON_SOFTWARE_ENG_DOMAIN.test(text) && !SOFTWARE_ENG_SIGNAL.test(text)) {
      continue;
    }
    // 配套护栏②：传统工程词与软件信号共现时，生产制造让给研发（嵌入式/自动驾驶算法/自动化测试开发）。
    if (fn === "生产制造" && SOFTWARE_ENG_SIGNAL.test(text)) continue;
    // 金融词也可能只是软件系统所属领域（Trading Systems Engineer）；有精确软件信号时同样让给研发。
    if (fn === "金融业务" && SOFTWARE_ENG_SIGNAL.test(text)) continue;
    if (!preferLast) {
      // 顺序优先：第一条命中的就是答案（等价于改造前的行为）。
      re.lastIndex = 0;
      if (re.test(text)) return String(fn);
      continue;
    }
    re.lastIndex = 0;
    let m;
    let last = null;
    while ((m = re.exec(text)) !== null) {
      last = m;
      if (m.index === re.lastIndex) re.lastIndex++; // 防零宽匹配死循环
    }
    if (!last) continue;
    const end = last.index + last[0].length;
    const len = last[0].length;
    if (!best || end > best.end || (end === best.end && len > best.len)) {
      best = { fn: String(fn), end, len };
    }
  }
  return best ? best.fn : null;
}

// 标题里的括号装的是**修饰语**（方向 / 领域 / 届别 / 工号 / 城市），不是岗位名。
// 「最靠后命中」优先的代价就在这儿：括号通常在标题末尾，里面的词位置最靠后，会赢过真正的岗位名——
// 实测「高级前端开发工程师（HR领域）」因为末尾那个 HR 被判成职能岗。
// 所以先在剥掉括号的标题上判，判不出来再退回完整标题（整个标题都被括号包住的情况）。
// 只在标题层剥：summary 正文里的括号常有实义，不能一并剥。
const TITLE_PARENTHETICAL = /[（(【\[][^）)】\]]*[）)】\]]/g;

// 英文标题的信息顺序与中文**相反**，这条边界不能想当然：
//   中文 =「公司-事业部-部门-岗位名」，岗位名在**末尾**；
//   英文 =「Job Title, Team / Org / Region」，岗位名在**开头**，逗号后面是团队、业务线、项目、地区。
// 实测反例（都是「最靠后命中」在英文上翻的车）：
//   Engineering Manager, Growth        → 末尾 Growth 把研发岗判成运营
//   Account Executive, Construction Insurance / Financial Analyst II, Connected Warfare → 同理被带偏
// 所以纯英文标题先只看第一个逗号前的部分；判不出来再退回整串。
function _isLatinTitle(text) {
  return !/[一-龥]/.test(text);
}

function _classifyJobTitleBaseFunction(job = {}) {
  const raw = normalizeForMatch(job?.title);
  if (!raw) return "其他";
  if (_isLatinTitle(raw) && raw.includes(",")) {
    const head = raw.slice(0, raw.indexOf(",")).trim();
    if (head) {
      const fn = _classifyFunctionText(head, true);
      if (fn !== "其他") return fn;
    }
  }
  const stripped = raw.replace(TITLE_PARENTHETICAL, " ").trim();
  if (stripped && stripped !== raw) {
    const fn = _classifyFunctionText(stripped, true);
    if (fn !== "其他") return fn;
  }
  return _classifyFunctionText(raw, true);
}

// 招聘**活动**标签（届别 / 校招 / 春秋招 / 社招 这类），不是 HR 岗位名。
// 刻意不含裸「招聘」——「招聘专员」「招聘HR」里的招聘是岗位名的一部分，剥掉就把真 HR 岗判没了。
const RECRUIT_EVENT_LABEL =
  /\d{2,4}\s*届?\s*(?:校园|春季|秋季|社会)?\s*招聘|校园招聘|春季招聘|秋季招聘|社会招聘|校招|秋招|春招|campus\s*recruit\w*|graduate\s*program/gi;

// 正文里的**招聘元信息**：字段标签（招聘单位 / 项目 / 对象 / 类别…：）、招聘活动（校园招聘 / 秋招…）、
// 公告引用（详见招聘公告 / 简章）。它们说的是「这次招聘」，不是「这个岗位做招聘」——
// 阿里 / B站 / 网易的 JD 开头固定是「工作地点：… 招聘项目：…」，国家能源是「【招聘单位】：国能…」，
// 标题判不出角色时正文兜底就被这个「招聘」判成职能（2026-09-23 全量对拍见下方 classifyJobFunction 注释）。
// 只在**正文**上剥：标题里的招聘活动另由 RECRUIT_EVENT_LABEL 那一层处理；「制定招聘计划 / 拓展招聘渠道」这类
// 真 HR 职责不带这些标签，照旧判职能。
const BODY_RECRUIT_META =
  /招聘\s*(?:单位|项目|对象|类别|类型|人数|批次|方式|届别|地点|时间|范围)\s*[】\]]?\s*[:：]|招聘(?:公告|简章)/g;

function _stripBodyRecruitMeta(summary) {
  if (!summary) return summary;
  return String(summary).replace(BODY_RECRUIT_META, " ").replace(RECRUIT_EVENT_LABEL, " ");
}

// 剥掉招聘活动标签后，标题还判出什么职能？
//   null   = 标题里根本没有活动标签可剥（「招聘HR」「招聘专员」）→「职能」是岗位名带来的，是真 HR 岗；
//   "其他" = 剥完什么都不剩 / 判不出（「2027 校园招聘」）→ 交给调用方退回看正文；
//   其它值 = 活动标签盖住了真实角色（「2026届校园招聘焊接工程师」→ 研发）。
function _titleFunctionWithoutRecruitEvent(job = {}) {
  const raw = normalizeForMatch(job?.title);
  if (!raw) return "其他";
  const withoutEvent = raw.replace(RECRUIT_EVENT_LABEL, " ").trim();
  if (withoutEvent === raw) return null;
  if (!withoutEvent) return "其他";
  return _classifyFunctionText(withoutEvent, true);
}

// 标题职能门也要看见活动标签背后白纸黑字写出的真实角色：
// 「2026年校园招聘-信息技术类岗位」不能因「招聘」先命中职能桶，就失去正文同职能词的召回资格。
// 纯「2027 校园招聘」仍是「职能」，不会让正文自证为产品/研发；真招聘 HR 也没有标签可剥，仍归职能。
function classifyJobTitleFunction(job = {}) {
  const titleFn = _classifyJobTitleBaseFunction(job);
  if (titleFn !== "职能") return titleFn;
  const strippedFn = _titleFunctionWithoutRecruitEvent(job);
  if (strippedFn === null || strippedFn === "其他") return titleFn;
  return strippedFn;
}

// 职能绝大多数由岗位名称即可确定；这些桶的词在 JD 正文里都是万能套话（如技术/项目经验、配合生产部门、
// 医药行业背景、服务客户）。正文兜底判出它们等于没判，只允许标题里的明确角色词归桶。
const BODY_FALLBACK_BLOCKED = new Set(["研发", "项目管理", "生产制造", "建筑工程", "医疗健康", "金融业务", "教育培训", "客服服务"]);

function classifyJobFunction(job = {}) {
  // 物化列优先（2026-09-17）：jobs.job_function 由入库时的同一套规则算好、触发器守着「依据变了就置 NULL」
  // （jobs-db/schema.sql jobs_guard_job_function）。读路径认列，NULL 才现算——这样 /jobs 候选取数可以
  // 不再为「必被职能门拒掉」的行传正文，且各处口径与 /campus 一致。
  // 用 `in`（而非 typeof）判：调用方拿 `{title: role}` 这种没有该属性的对象来分类用户目标岗位，必须照旧现算。
  if (job && typeof job === "object" && "job_function" in job) {
    const materialized = typeof job.job_function === "string" ? job.job_function : null;
    if (materialized && JOB_FUNCTION_BUCKETS.includes(materialized)) return materialized;
  }
  // 标题权威优先：标题是岗位职能最可靠的信号，判出干净职能就用它，避免被 job_type / summary 带偏——
  // 实锤：B站「数据科学家」挂在部门 job_type=「产品运营类」下，旧实现拼全文 → 「产品运营」先命中 →
  // 误判「产品」→ 匹配上「AI 数据产品经理」推给产品经理用户。标题「数据科学家」应判「数据」。
  // 刻意不含 job_type（部门/招聘类型，非真实角色）。
  const titleFn = classifyJobTitleFunction(job);
  // 「职能」例外：标题「2027 校园招聘」这类是**招聘活动标签**（命中「招聘」），不是 HR 岗 →
  // 退回看 标题+摘要 里的真实角色（如正文「产品经理方向」）。
  // ⚠️ 但必须先分清「活动标签」和「真 HR 岗」：旧实现对所有「职能」标题一律退回，于是
  // 「招聘HR（抖音）」（正文写"支持产品经理与算法工程师招聘"）被判成**产品岗**推给产品经理用户——
  // 正文里那些岗位名是它的招聘对象、不是它自己的职能。判据 = 把活动标签剥掉后重判一次标题：
  // 「招聘HR」「招聘专员」「HRBP」压根没有标签可剥 → 真 HR 岗，不退回；
  // 「2027 校园招聘」剥完什么都不剩 → 退回看正文；剥完露出真实角色 → 用那个角色。
  if (titleFn !== "其他" && titleFn !== "职能") return titleFn;
  // ⚠️ 旧实现只问「剥完还判不判得出职能」，判得出就一律保留「职能」——于是
  //   「2026届三航南通海洋公司校园招聘焊接工程师」「2026届校园招聘金属结构设计岗」
  //   这类被「校园招聘」里的"招聘"判成 HR 岗（2026-09-02 香港库实测：校招标题里 383 个「职能」
  //   有约两三成是这么来的）。判据要落到剥完的**结果本身**：
  if (titleFn === "职能") {
    const strippedFn = _titleFunctionWithoutRecruitEvent(job);
    // 没有活动标签可剥 → 「职能」来自岗位名本身，是真 HR 岗。
    if (strippedFn === null) return titleFn;
    // 剥完仍判出职能（「2026届校招…财务管理岗」）或判出别的真实角色（焊接工程师→研发）→ 都用剥完的。
    if (strippedFn !== "其他") return strippedFn;
    // 剥完什么都判不出（纯活动标签标题）→ 落到下面看正文。
  }
  const full = _classifyFunctionText(
    normalizeForMatch([job?.title, _stripBodyRecruitMeta(job?.summary)].filter(Boolean).join(" ")),
  );
  if (BODY_FALLBACK_BLOCKED.has(full)) return titleFn;
  return full !== "其他" ? full : titleFn;
}

// P1-B 两层关键词匹配的"相关层"职能映射：CHINA_KEYWORD_GROUPS 各组（按索引）→ 职能桶。
// 与 classifyJobFunction 同口径；null = 该组不是职能（招聘类型/无干净职能），不参与相关层。
const KEYWORD_GROUP_FUNCTIONS = [
  "研发", // 0  算法/AI
  "数据", // 1  数据分析
  "数据", // 2  数据工程
  "产品", // 3  产品
  "研发", // 4  前端
  "研发", // 5  后端
  "研发", // 6  测试
  "研发", // 7  运维
  "研发", // 8  安全
  "设计", // 9  设计
  "运营", // 10 运营
  "市场", // 11 市场
  "销售", // 12 销售
  "职能", // 13 财务
  "职能", // 14 人力
  "职能", // 15 法务
  "供应链", // 16 供应链
  "研发", // 17 硬件
  null, // 18 投研（无干净职能桶）
  null, // 19 管培/校招（招聘类型）
  null, // 20 实习（招聘类型）
  null, // 21 工程/研发通用组（跨语言锚点；仅 tier-1 精确，不参与 related 兄弟排除）
  // ⚠ 22 之后的新组必须**追加**在数组末尾并同步这里，索引与 CHINA_KEYWORD_GROUPS 严格对齐。
  null, // 22 软件（跨语言锚点；同上，单列以免「软件」过宽等价「工程师」）
  "研发", // 23 移动端（iOS / Android / 客户端；从前端组拆出，两者互为兄弟组、不再互相精确命中）
  null, // 24 AI 技术领域（领域≠职能：AI 产品/AI 研发/AI 数据各属其职能，故不映射任何职能桶）
  "金融业务", // 25 柜员
  "金融业务", // 26 银行业务（不含裸客户经理，避免抢销售岗）
  "金融业务", // 27 保险业务
  "金融业务", // 28 投资交易
  "教育培训", // 29 教师
  "教育培训", // 30 教研培训
  "医疗健康", // 31 护理
  "医疗健康", // 32 临床医生
  "医疗健康", // 33 临床研究
  "医疗健康", // 34 药学
  "医疗健康", // 35 医药商务
  "生产制造", // 36 机械设计
  "生产制造", // 37 工艺制造
  "生产制造", // 38 电气自动化
  "生产制造", // 39 质量管理
  "生产制造", // 40 生产操作
  "建筑工程", // 41 土木建筑
  "建筑工程", // 42 工程造价
  "客服服务", // 43 客户服务
  "客服服务", // 44 门店零售
  null, // 45 学段（修饰语，不参与职能相关层）
  "金融业务", // 46 投资银行/并购（2026-09-18 新增，见 CHINA_KEYWORD_GROUPS 同索引注释）
  null, // 47 编导/内容制作（2026-09-18 新增，无对应职能桶，见 CHINA_KEYWORD_GROUPS 同索引注释）
  "研发", // 48 芯片验证（2026-09-23 新增，见 CHINA_KEYWORD_GROUPS 同索引注释）
  "金融业务", // 49 风控/风险管理（2026-09-23 新增，见 CHINA_KEYWORD_GROUPS 同索引注释）
];

// 筛选器的「一级职能 → 二级岗位方向」只从现有词表按下标派生，不能另维护一份手写表：
// 词表新增方向时，手写表极易漏同步，UI 会重新出现「能搜到却不能筛」的断层。
// 一级顺序刻意沿用 JOB_FUNCTION_BUCKETS；function=null 的组是技术领域/招聘类型/泛锚点，
// 不是可供用户主动收窄的岗位方向，绝不能混进来污染筛选。
const JOB_FUNCTION_TAXONOMY = Object.freeze(
  JOB_FUNCTION_BUCKETS.map((jobFunction) =>
    Object.freeze({
      function: jobFunction,
      roles: Object.freeze(
        CHINA_KEYWORD_GROUPS.flatMap((group, index) =>
          KEYWORD_GROUP_FUNCTIONS[index] === jobFunction ? [group[0]] : [],
        ),
      ),
    }),
  ),
);

function _matchedGroupIndexes(query) {
  const key = String(query || "");
  const hit = _matchedGroupIndexCache.get(key);
  if (hit !== undefined) return hit;
  const normalized = normalizeForMatch(query);
  const idxs = [];
  CHINA_KEYWORD_GROUPS.forEach((group, i) => {
    if (group.some((term) => containsTerm(normalized, term))) idxs.push(i);
  });
  // 冻结：调用方只读（queryFunctions / keywordMatchTier / _titleClaimedByRivalGroup 都只遍历）。
  // 冻上以后万一将来有人就地改它会当场抛错，而不是把污染悄悄传给下一行。
  return _cacheSet(_matchedGroupIndexCache, key, Object.freeze(idxs), QUERY_CACHE_MAX);
}

function _jobSearchableText(job) {
  const texts = _jobTexts(job);
  if (texts.searchable === undefined) {
    texts.searchable = normalizeForMatch(
      [job?.title, job?.company, job?.location, job?.job_type, job?.summary, job?.salary_text]
        .filter(Boolean)
        .join(" "),
    );
  }
  return texts.searchable;
}

// 返回岗位相对查询的匹配档：
//   "exact"   = tier-1 精确（标题/摘要直接含概念组词，沿用 jobMatchesChinaKeyword，零回退）
//   "related" = tier-2 相关（同职能、且未被兄弟细分组精确认领——"前端"岗不进"后端"的相关层）
//   null      = 不匹配
// 动机：88% 岗位空摘要 → 关键词只能匹配标题 → 召回崩；相关层用职能兜底找回标题泛而无摘要的同类岗。
function keywordMatchTier(job, query, options = {}) {
  if (jobMatchesChinaKeyword(job, query, options)) return "exact";

  const qGroups = _matchedGroupIndexes(query);
  const qFunctions = new Set(qGroups.map((i) => KEYWORD_GROUP_FUNCTIONS[i]).filter(Boolean));
  if (qFunctions.size === 0) return null; // 查询无职能映射（实习/投研/散词）→ 不滥召相关层
  if (!qFunctions.has(classifyJobFunction(job))) return null; // 不同职能

  const searchable = _jobSearchableText(job);
  const qGroupSet = new Set(qGroups);

  // 别的方向已经认领了这个岗 → 不算本查询的相关岗。
  //
  // 原实现只排除**同职能**的兄弟组（`qFunctions.has(fn)`），于是「销售工程师」这种
  // ——classifyJobFunction 因为「工程师」判成研发、但标题白纸黑字写着「销售」的岗——
  // 因为销售组映射到「销售」职能、与查询职能不同而被 continue 跳过，堂而皇之进了
  // 「前端开发工程师」的相关层。真实库实测：某前端画像 TOP25 里挤满销售工程师 /
  // 试剂产品工程师 / 技术文档工程师，方向准确率 12%。
  // 改为排除**所有**非查询的具体方向组：标题/正文里出现了另一个明确方向的词，就归那个方向。
  // 泛锚点组（工程师 / 软件 / AI 领域）继续豁免——它们几乎命中所有技术岗，拿它们排除会把
  // 「高级软件工程师」这类真正需要相关层兜底的泛标题岗一起杀掉（那正是相关层存在的理由）。
  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    if (qGroupSet.has(i) || GENERIC_ANCHOR_GROUP_INDEXES.has(i)) continue;
    if (!KEYWORD_GROUP_FUNCTIONS[i]) continue; // 招聘类型 / 投研：不是方向，无权认领
    if (CHINA_KEYWORD_GROUPS[i].some((term) => containsTerm(searchable, term))) return null;
  }
  return "related";
}

function normalizeChinaJobFields(job) {
  const title = job?.title || "";
  const summary = job?.summary || "";
  const url = job?.jd_url || job?.apply_url || "";
  const normalizedJobType = normalizeChinaJobType({
    title,
    sourceType: job?.job_type,
    url,
    summary,
  });
  const currentJobType = job?.job_type || null;
  const shouldKeepSpecificType =
    currentJobType &&
    normalizedJobType &&
    ["社招", "全职", "兼职"].includes(normalizedJobType) &&
    /[·,，/|]/.test(currentJobType);

  return {
    ...job,
    location: normalizeChinaLocation(job?.location),
    job_type: shouldKeepSpecificType
      ? currentJobType
      : normalizedJobType || currentJobType,
  };
}

function shouldIncludeOverseasLexicon(options) {
  return Boolean(options && options.includeOverseasLexicon);
}

function overseasLexiconGroups() {
  const groups = [];
  for (const section of ["roles", "skills"]) {
    for (const [cn, terms] of Object.entries(ROLE_LEXICON_EN[section] || {})) {
      groups.push([cn, ...(Array.isArray(terms) ? terms : [])]);
    }
  }
  return groups;
}

function matchedOverseasLexiconGroups(normalizedQuery) {
  const normalized = normalizeForMatch(normalizedQuery);
  if (!normalized) return [];
  return overseasLexiconGroups().filter((group) =>
    group.some((term) => containsTerm(normalized, term)),
  );
}

function mergeOverseasLexiconUnits(units, lexiconGroups) {
  for (const group of lexiconGroups) {
    const normalizedTerms = Array.from(new Set(group.map(normalizeForMatch).filter(Boolean)));
    if (normalizedTerms.length === 0) continue;

    const target = units.find((unit) =>
      normalizedTerms.some((term) =>
        unit.some(
          (existing) =>
            existing === term ||
            containsTerm(term, existing) ||
            containsTerm(existing, term),
        ),
      ),
    );
    if (target) {
      for (const term of normalizedTerms) {
        if (!target.includes(term)) target.push(term);
      }
    } else {
      units.push(normalizedTerms);
    }
  }
}

// 用户手填的目标岗位写法五花八门（2026-09-17 走查 44 个真实用户，7 个推荐页 0 岗，其中 4 个栽在这里）：
//   「项目专员/助理」—— 斜杠是「或」，旧逻辑把两段当成 AND，一个岗都对不上；
//   「英文相关」「技术岗位」—— 「相关 / 岗位」是填充词，bigram 链 (英文 & 文相 & 相关) 要求原句出现在标题里；
//   「办公室文员」—— 库里 119 个「文员」岗没有一个写「办公室」。
// 这里把一条写法拆成若干**干净的岗位短语**，召回与匹配两端共用（profile.ts / scoring.ts 都走它）。
// 只做保守的拆分与去填充，不做同义替换——同义扩展仍由词组表负责。
// 2026-09-17 存量体检（64 份线上画像）又补了几类写法，都是同一个病：一格里塞了多条 / 带了岗位无关的后缀。
//   「销售；采购」「文体/影视/写作/媒体类」—— 分隔符不止斜杠，中文顿号 / 分号 / 逗号同样是「或」；
//   「测试 后端」「质量工程师 工艺工程师」「销售 管培 运营」—— 纯中文时空格也是「或」
//       （**只在纯中文时**：「AI 产品经理」「AIGC 内容实习生」的空格是词内空格，拆了就毁）；
//   「ai算法+雷达」—— 加号同理，但只在含中文时拆（别碰 C++ / CI/CD 这类技能写法）；
//   「机械工程师助理（设计方向）」—— 括号里是修饰不是岗位名；
//   「行政/后勤类」「化学分析岗」「机械设计实习生」—— 后缀要反复剥（拆完还可能再带一层）。
// 只做保守的拆分与去填充，不做同义替换——同义扩展仍由词组表负责。
const ROLE_HARD_SEPARATOR_RE = /[/／|｜、，,；;]/;
const ROLE_FILLER_SUFFIX_RE = /(相关|方向|岗位|职位|工作|实习生|实习|类|岗)$/;
const ROLE_MODIFIER_PREFIX_RE = /^(办公室|门店|总部|部门|公司)/;
const ROLE_TRAILING_BRACKET_RE = /[（(][^（）()]*[）)]$/;
const HAS_LATIN_RE = /[A-Za-z0-9]/;
const HAS_CJK_RE = /[一-鿿]/;

/**
 * 把一条写法拆成候选片段：硬分隔符一律拆；空格只在**纯中文且每段都 ≥2 字**时拆；
 * 加号只在含中文时拆。任一附加规则拆出 1 字碎片就整体弃权（宁可不拆，不可拆碎）。
 */
function splitRoleCandidates(value) {
  const out = [];
  for (const chunk of String(value || "").split(ROLE_HARD_SEPARATOR_RE)) {
    const piece = chunk.trim();
    if (!piece) continue;
    const plus =
      HAS_CJK_RE.test(piece) && piece.includes("+") ? piece.split(/[+＋]/).map((s) => s.trim()) : [piece];
    const usePlus = plus.length > 1 && plus.every((s) => s.length >= 2);
    for (const sub of usePlus ? plus : [piece]) {
      const spaced = sub.split(/\s+/);
      const useSpace =
        spaced.length > 1 && !HAS_LATIN_RE.test(sub) && spaced.every((s) => s.length >= 2);
      for (const seg of useSpace ? spaced : [sub]) {
        if (seg) out.push(seg);
      }
    }
  }
  return out;
}

/** 反复剥后缀/括号/前缀修饰，直到不再变化（拆完可能又露出一层，如「行政/后勤类」→「后勤类」→「后勤」）。 */
function stripRoleDecorations(part) {
  let s = part;
  for (let i = 0; i < 4; i += 1) {
    const before = s;
    s = s.replace(ROLE_TRAILING_BRACKET_RE, "").trim();
    s = s.replace(ROLE_FILLER_SUFFIX_RE, "").trim();
    s = s.replace(ROLE_MODIFIER_PREFIX_RE, "").trim();
    if (s === before) break;
  }
  return s;
}

function normalizeRolePhrases(roles) {
  const out = [];
  for (const raw of Array.isArray(roles) ? roles : [roles]) {
    for (const part of splitRoleCandidates(raw)) {
      const stripped = stripRoleDecorations(part);
      // 剥完只剩 1 个字或空 = 这条写法本来就只有填充词，保留原样别丢
      const phrase = stripped.length >= 2 ? stripped : part;
      if (!out.includes(phrase)) out.push(phrase);
    }
  }
  return out;
}

function splitKeywordTerms(value) {
  const raw = String(value || "").trim();
  const parts = raw
    .split(/[\s,，、/|;；]+/)
    .map((term) => term.trim())
    .filter(Boolean);

  return [raw, ...parts];
}

function normalizeForMatch(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

// 中文没有词边界，短词做子串会撞上「包含它的更长无关词」。只有某次出现不落在假朋友片段里才算命中。
// 不能因整串里出现一个假朋友就整体否定：例如「土建施工与系统实施工程」仍含一个真的「施工」。
const CJK_FALSE_FRIENDS = Object.freeze({
  "施工": ["实施工", "设施工"],
  "品管": ["产品管", "样品管", "用品管", "物品管"],
  "质检": ["性质检"],
  "检测": ["性质检测"],
  // 「数据仓库」= data warehouse，一个数据工程概念，不是物理仓储——2026-09-18 全量对拍实测：
  // 给供应链组新增「仓库」角色词后，「数据仓库开发工程师」这类岗（50 例）被 `_titleRoleClusterConflict`
  // 误判成"已被供应链组认领"，连带把它们从「数据分析」查询里挤掉。库内只有「数据仓库」这一种
  // 假朋友前缀（「数据仓储/数据仓管」查无此写法），不影响「仓库管理员/仓库经理」等真仓储岗。
  "仓库": ["数据仓库"],
});

function isFalseFriendOccurrence(haystack, term, termIndex, falseFriends) {
  return falseFriends.some((friend) => {
    let offset = friend.indexOf(term);
    while (offset !== -1) {
      const friendStart = termIndex - offset;
      if (friendStart >= 0 && haystack.startsWith(friend, friendStart)) return true;
      offset = friend.indexOf(term, offset + 1);
    }
    return false;
  });
}

// 短的纯拉丁缩写（≤3，如 ai/ml/pm/ui/go/hr）用词边界匹配；中文登记过假朋友的短词逐个出现位置判断。
// 纯拉丁长词（≥4 字母、不含空格/连字符/数字）也走词边界（见下 LATIN_TERM_VARIANTS）；
// 其余（CJK、多词短语、带连字符的复合词）走普通子串包含。haystack 需已 normalizeForMatch。
// 模块级常量：正则字面量在函数体里每次求值都会新建一个 RegExp 对象，而 containsTerm 在
// 打分热路径上每行每词各调一次。无 /g 标志 → .test 无状态，提到外面共享是安全的。
const SHORT_LATIN_TERM_RE = /^[a-z0-9.+#-]{1,3}$/;
const PURE_LATIN_LONG_TERM_RE = /^[a-z]{4,}$/;

// 纯拉丁长词的裸子串会撞上「包含它的更长无关词」——2026-09-18 全库 active 标题实测（104,670 行含词表词）：
//   product ⊂ production 2,166 / productivity 92（「Production Technician」被判成产品经理 exact，1,430 例）
//   search ⊂ research 1,968 + researcher 423 · intern ⊂ international 386 / internal 289 · quant ⊂ quantum 71
//   sales ⊂ salesforce 97 · doctor ⊂ postdoctoral 44 · asic ⊂ basic 10 · react ⊂ reactor 5 · teller ⊂ storyteller 6
// 所以纯拉丁长词一律词边界 + 自动容忍复数 s。但同一份数据里也有大量**同概念派生词**只能靠子串命中
// （engineering 5,210 / quantitative 340 / agentic 578 / auditor 149 / paralegal 63 / presales 98），
// 一刀切会误杀 → 这张表把**数据里验证过**的同概念派生词放回来。默认严格：新冒出的超串不会再悄悄命中，
// 要放行必须来这里登记（且登记的必须是同一个方向的词，别把 salesforce / research 这种加回去）。
const LATIN_TERM_VARIANTS = Object.freeze({
  engineer: ["engineering"],
  data: ["database"], // 数据邻域（DBA / Database Engineer）沿用旧口径；datacenter / dataset / metadata 不算
  quant: ["quantitative"],
  agent: ["agentic"],
  audit: ["auditor", "auditing"],
  legal: ["paralegal"],
  sales: ["presales", "aftersales", "telesales", "salesperson"],
  brand: ["branding"],
  pharmaceutical: ["biopharmaceutical", "radiopharmaceutical"],
  algorithm: ["algorithmic"],
  harmony: ["harmonyos"],
  retail: ["retailer"],
});
// am/pm 既是岗位缩写（PM = 产品/项目经理，「产品经理」组与海外词库都收了它），也是排班时间的后缀。
// 2026-09-18 /today 真库对拍抓到：海外倒班岗标题 "Builds-B Shift (Mon-Fri 2 PM- 10:30PM)" 里的 PM 是独立
// token，被词边界正则判成「精确命中 产品经理」。全库 active 标题含独立 pm token 的 480 条里 63 条是这种
// 时间写法、全被判 exact（DSV / Jabil / Baxter 的仓储产线倒班岗）。
// 判据 = 前面紧跟「**独立的** 1~2 位小时数（可带 :mm，与 am/pm 之间至多一个空格）」时不算命中。
// ⚠️ 小时数必须独立（前一个字符不是字母数字或在串首）：「T0 PM」是量化 T0 策略的 PM 岗，0 前面是字母 t，
// 不是时间，仍要命中。反向对拍：417 条非时间写法的 PM 岗（PM(J16657) / Senior PM, Growth / 搜索策略pm）
// 改前改后必须一条不少。"AM & PM Weekend" / "PM Shift" 这类班次写法没有小时数，本条不管，仍会命中（已知残差）。
const MERIDIEM_TERMS = new Set(["am", "pm"]);
const MERIDIEM_TIME_LOOKBEHIND = "(?<!(?:^|[^a-z0-9])[0-9]{1,2}(?::[0-9]{2})? ?)";
// 中文角色名中间常插一个**职级词**：「合成研究员」→「有机合成**高级**研究员 / 有机合成**助理**研究员 /
// 有机合成**（助理）**研究员」。连续子串对不上，这类标题字面就是用户要的岗，却被判成方向不符
// （2026-09-23 真实画像：方向「有机合成研究员」、上海/杭州，召回里 6 个这样的岗全被 role_mismatch 拒掉）。
// 只放行**封闭的职级词表**，且前缀、角色名都必须原样出现：
//   🚫 中间插「销售 / 运营 / 营销 / 应用 / 成功 / 市场…」不行——那是另一个角色（产品**运营**经理 ≠ 产品经理，
//      客户**成功**经理 ≠ 客户经理）。全库 35 万个在招标题扫过，插在词表角色名中间的词里这类占绝大多数。
//   🚫 前缀不同不行：「有机合成研究员」不因此命中「分析研究员 / 药物合成高级研究员」。
// 全库对拍（35.2 万个不同的在招标题 × 词表全部 417 个词，改前改后逐对比）：新命中 94 个标题、0 个丢失，
// 逐条看过都是同一角色（合成研究员 51 / 产品经理 25 / 客户经理 7 / 医学经理 6 / 投资经理 4 / 现场工程师 1）。
const INFIX_ROLE_NOUNS = ["研究员", "工程师", "经理", "分析师", "设计师", "专员", "顾问", "主管", "讲师", "医师", "药师", "教师", "老师", "技师", "会计", "律师"];
// 职级词表导出给 lib/job-search.ts：SQL 候选（search_doc 的 bigram tsquery）要按同一张表放宽，
// 否则 JS 判 exact 的「有机合成高级研究员」在 /jobs 关键词搜索里根本进不了候选。改这两张表两边自动同步。
const SENIORITY_INFIX_WORDS = Object.freeze(["高级", "资深", "中级", "初级", "助理", "副", "首席"]);
const SENIORITY_INFIX_PAREN_WORDS = Object.freeze(["高级", "资深", "中级", "初级", "助理", "副"]);
const SENIORITY_INFIX = `(?:${SENIORITY_INFIX_WORDS.join("|")}|[（(](?:${SENIORITY_INFIX_PAREN_WORDS.join("|")})[)）])`;
const PURE_CJK_TERM_RE = /^[一-鿿]+$/;
const _seniorityInfixCache = new Map();
/** 「前缀 ≥2 字 + 角色名」的纯中文词 → { noun, re }；其余返回 null（也缓存，热路径上只查一次表）。 */
function _seniorityInfixPattern(t) {
  const hit = _seniorityInfixCache.get(t);
  if (hit !== undefined) return hit;
  let pattern = null;
  if (PURE_CJK_TERM_RE.test(t)) {
    const noun = INFIX_ROLE_NOUNS.find((n) => t.endsWith(n) && t.length - n.length >= 2);
    if (noun) {
      const prefix = t.slice(0, -noun.length);
      pattern = { prefix, noun, re: new RegExp(`${prefix}${SENIORITY_INFIX}${noun}`) };
    }
  }
  return _cacheSet(_seniorityInfixCache, t, pattern, TERM_CACHE_MAX);
}
/**
 * containsTerm 会对这个词放宽职级插词时，返回 { prefix, noun }（「合成研究员」→ 合成 + 研究员）；否则 null。
 * 与 containsTerm 的分支一一对应（拉丁词、带假朋友的词走不到职级分支），SQL 候选据此放宽才不会多放一类词。
 */
function seniorityInfixSplit(term) {
  const t = _normalizedTerm(term);
  if (!t || CJK_FALSE_FRIENDS[t]) return null;
  const infix = _seniorityInfixPattern(t);
  return infix && { prefix: infix.prefix, noun: infix.noun };
}
/** 空 query 的匹配单元。与旧实现返回的 `[]` 语义相同（调用方只读），共享一份省分配。 */
/** @type {ReadonlyArray<ReadonlyArray<string>>} */
const EMPTY_UNITS = Object.freeze([]);

function containsTerm(haystack, term) {
  const h = String(haystack || "");
  const t = _normalizedTerm(term);
  if (!t) return false;
  if (SHORT_LATIN_TERM_RE.test(t)) {
    let re = _shortLatinTermRe.get(t);
    if (re === undefined) {
      const escaped = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      re = _cacheSet(
        _shortLatinTermRe,
        t,
        new RegExp(`(^|[^a-z0-9])${MERIDIEM_TERMS.has(t) ? MERIDIEM_TIME_LOOKBEHIND : ""}${escaped}([^a-z0-9]|$)`),
        TERM_CACHE_MAX,
      );
    }
    return re.test(h);
  }
  if (PURE_LATIN_LONG_TERM_RE.test(t)) {
    let re = _longLatinTermRe.get(t);
    if (re === undefined) {
      const alts = [t, ...(LATIN_TERM_VARIANTS[t] || [])].join("|");
      re = _cacheSet(
        _longLatinTermRe,
        t,
        new RegExp(`(^|[^a-z0-9])(?:${alts})s?([^a-z0-9]|$)`),
        TERM_CACHE_MAX,
      );
    }
    return re.test(h);
  }
  const falseFriends = CJK_FALSE_FRIENDS[t];
  if (falseFriends) {
    let termIndex = h.indexOf(t);
    while (termIndex !== -1) {
      if (!isFalseFriendOccurrence(h, t, termIndex, falseFriends)) return true;
      termIndex = h.indexOf(t, termIndex + t.length);
    }
    return false;
  }
  if (h.includes(t)) return true;
  const infix = _seniorityInfixPattern(t);
  return infix !== null && h.includes(infix.noun) && infix.re.test(h);
}

module.exports = {
  normalizeRolePhrases,
  CHINA_KEYWORD_GROUPS,
  GROUP_DOMAIN_ANCHORS,
  JOB_FUNCTION_BUCKETS,
  JOB_FUNCTION_TAXONOMY,
  KEYWORD_GROUP_FUNCTIONS,
  CHINA_CITY_REGION_EXPANSIONS,
  CITY_ALIASES,
  _minRequiredExperienceYears,
  cityMatchTokens,
  classifyJobFunction,
  expandChinaKeywordTerms,
  expandChinaCityTargets,
  ftsCandidateTerms,
  hasExplicitRecruitmentType,
  jobMatchesChinaKeyword,
  keywordMatchTier,
  keywordMatchUnits,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  normalizeChinaLocation,
  recruitmentCategory,
  seniorityInfixSplit,
  SENIORITY_INFIX_WORDS,
  SENIORITY_INFIX_PAREN_WORDS,
};
