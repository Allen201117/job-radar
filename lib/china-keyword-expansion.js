const ROLE_LEXICON_EN = require("./role-lexicon-en.js");

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
    "data", // 跨语言：命中 Data Scientist/Data Engineer/Data Analyst 等英文标题（子串，含 database/metadata，数据邻域可接受）
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
];

// 组索引常量：算法「岗位方向」组与 AI「技术领域」组之间是非对称包含关系，
// 见 keywordMatchUnits 里的单向展开。调整组顺序时这两个常量必须跟着改。
const ALGO_GROUP_INDEX = 0;
const AI_DOMAIN_GROUP_INDEX = CHINA_KEYWORD_GROUPS.length - 1;

// 纯职级 / 职能后缀（整串由这些词拼成才算）：它们描述「什么级别、什么形态」，不描述「什么方向」，
// 所以不配单独成为一个 AND 匹配单元。见 keywordMatchUnits 的残差处理。
const GENERIC_ROLE_SUFFIX_ONLY =
  /^(?:开发|研发|工程|工程师|技术|岗位|岗|职位|方向|专员|专家|经理|主管|总监|负责人|顾问|助理|人员|实习生|实习|校招|社招|招聘|高级|资深|初级|中级|senior|junior|lead|staff|principal)+$/;

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
function keywordMatchUnits(query, options = {}) {
  const raw = String(query || "").trim();
  if (!raw) return [];

  const normalized = normalizeForMatch(raw);
  const units = [];

  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    const group = CHINA_KEYWORD_GROUPS[i];
    if (!group.some((term) => containsTerm(normalized, term))) continue;
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

  return units;
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
  const titleText = normalizeForMatch(job?.title);
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

  const titleText = normalizeForMatch(job?.title);
  // 公司域保留短词命中：用户会直接搜「字节」「网易」等公司名。
  const companyText = normalizeForMatch(job?.company);
  // 内容域的短词（摘要 / 城市 / 类型 / 薪资）不携带稳定职能信息，不能单独证明精确匹配。
  const contentText = normalizeForMatch(
    [job?.location, job?.job_type, job?.summary, job?.salary_text]
      .filter(Boolean)
      .join(" "),
  );

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
function _minRequiredExperienceYears(text) {
  if (!text) return null;
  const raw = String(text).toLowerCase();
  const t = raw.replace(/\s+/g, "");
  // 中文年限：**必须落在「经验/经历/从业」语境里**才算硬门槛。
  // 旧实现的 /(\d{1,2})[-~至到](\d{1,2})年/ 与 /(\d{1,2})年以上/ 不看上下文，把校招 JD 里
  // 高频的成长路径/派驻时长当成了经验要求，导致明确的校招岗被层2 强制判成社招：
  //   「管培生培养计划，2~3年晋升为管理者」「通过 2-3 年的配套加速培养机制成长为…」
  //   「选拔绩优的校招生…优秀者 2-3 年发展成为主管」「需要派往墨西哥工作 3-5 年」
  // 2026-08-07 实测：moka 校招门户样本里 13 个被层2 判社招的岗，11 个是这类误判。
  // 窗口取 ±25 字而非更窄：「2 年以上在实验室硬件或软件设计开发经验」里"经验"离年限 16 字远，
  // 窗口太窄会把真·经验要求漏掉 → 社招岗被判校招。方向上遵循本模块的总原则
  // 「宁可漏判一个校招，也别把社招误标成校招」，所以宁可放宽窗口。
  for (const hit of t.matchAll(/(\d{1,2})(?:[-~至到]\d{1,2})?年(?!级)(?:以上)?/g)) {
    const around = t.slice(Math.max(0, hit.index - 25), hit.index + hit[0].length + 25);
    if (/经验|经历|从业/.test(around)) return parseInt(hit[1], 10);
  }
  const m =
    t.match(/(\d{1,2})[-~to]+(\d{1,2})years?/) || // 3-5 years
    t.match(/(\d{1,2})\+?years?(?:ofexperience)?/); // 5+ years / 5 years
  if (m) return parseInt(m[1], 10);
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

// 来源自报的招聘类型：只看 job_type 字段**本身**（不掺标题/正文），来源渠道 / 结构化 recruitType
// 落到这里最可信。job_type 是"招聘类型"取值时返回桶；是职能/类别（如"人力资源""管理类""研发"）→ null。
function sourceDeclaredCategory(jobType) {
  const t = String(jobType || "").trim();
  if (!t) return null;
  if (/实习|\bintern/i.test(t)) return "实习";
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

// 招聘类型分层判定（从最可信到兜底）。核心认知：校招/实习是"会自报家门的特殊招聘"，社招是"未标记的默认态"。
// 因此策略 = 精度优先：只在有**强/可信信号**时判校招/实习，其余一律默认社招；宁可漏判一个校招，
// 也别把社招误标成校招（假校招更坑求职者）。
function recruitmentCategory(job = {}) {
  const title = String(job.title || "");
  const summary = String(job.summary || "");
  const url = String(job.jd_url || job.apply_url || "");
  const company = String(job.company || "");

  // 层1：实习最先且最权威 —— 源渠道=实习 / 标题带"实习·intern" / url 走 /shixi|intern 通道。
  // 实习是自报家门的，且"实习"标记只认标题/url（不认正文，"实习经历"是社招 JD 常见词）。
  if (
    sourceDeclaredCategory(job.job_type) === "实习" ||
    hasInternSignal(title) ||
    /\/(shixi|intern)(\/|\?|$)/i.test(url)
  ) {
    return "实习";
  }

  // 层2：明确要求 ≥2 年经验 → 强制社招。校招=应届0经验，与之矛盾。优先级高于源 job_type：
  // 治"源头把资深岗错标校招"（如光刻主任工程师 job_type=校招 但要 8 年）。
  if (_demandsPriorExperience(job)) return "社招";

  // 层3：信任来源自报的 job_type（结构化 recruitType/渠道最可信，且此处只看字段本身不被正文污染）。
  const declared = sourceDeclaredCategory(job.job_type);
  if (declared) return declared; // 到这里 declared ∈ {校招, 社招}

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
  if (/\/(xiaozhao|campus)([-_][a-z]+)?(\/|\?|$)/i.test(url)) return "校招";
  if (/\/(social|experienced)([-_][a-z]+)?(\/|\?|$)/i.test(url)) return "社招";

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
  // 与 recruitmentCategory 的"非兜底"信号集对齐：任一可信信号命中即算"明确"（≥2年经验 / 源 job_type /
  // url 渠道 / 标题实习 / 强校招标记 / 公司名标注）。刻意不再扫正文弱词，避免"毕业生优先"把社招岗当校招硬筛。
  if (_demandsPriorExperience(job)) return true;
  if (job.job_type) return true; // 源给了 job_type（哪怕是职能类别）→ 视为有据，保持既有筛选行为
  const url = String(job.jd_url || job.apply_url || "");
  if (/\/(shixi|intern|xiaozhao|campus|social|experienced)(\/|\?|$)/i.test(url)) return true;
  if (hasInternSignal(String(job.title || ""))) return true;
  if (hasStrongCampusSignal(`${job.title || ""} ${job.summary || ""}`)) return true;
  const company = String(job.company || "");
  return /实习|校招|校园招聘/.test(company);
}

// 岗位职能粗分类（产品/研发/设计/数据/运营/市场/销售/供应链/职能/其他），用于岗位卡片的强特征标签。
// 「最靠后命中」优先，不再是「规则表顺序优先」——见 _classifyFunctionText 的注释。
// 规则内部仍保持「更具体的写在前面」，用于同结束位置时的平局决胜。
const JOB_FUNCTION_RULES = [
  // 角色锚定：只在明确的产品角色词命中（删掉裸词"产品"/"产品设计师"），
  // 否则"产品研发/产品测试/硬件产品工程师"等会被裸词误吃成产品（研发信号本应优先）。
  // 英文补充 director/head/vp of product 这类头衔式写法（外企 ATS 常见，旧规则只认 product manager）。
  ["产品", /产品经理|产品运营|产品策划|产品负责人|产品总监|产品专家|product\s*manager|product\s*owner|product\s*lead|(?:director|head|vp|vice\s*president)[,\s]+(?:of\s+)?product|technical\s*program\s*manager|\btpm\b|\bpm\b|\bpo\b/i],
  ["设计", /视觉设计|交互设计|ui\s*设计|ux|平面设计|设计师|designer/i],
  ["数据", /数据分析|数据科学|数据工程|大数据|数据挖掘|data\s*(analyst|scien|engineer)|\bbi\b|商业分析/i],
  // 研发拆成「具体方向词」和下面的「泛工程后缀」两条，后者标 generic —— 见 _classifyFunctionText。
  ["研发", /算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|\bsde\b|\bsre\b|programmer|software|软件/i],
  // 泛工程后缀（generic）：**位置必须留在这里**（紧跟具体研发词、排在运营/市场之前）。
  //   标题层（preferLast=true）跑两轮，第一轮跳过它 → 具体职能词优先，治「大数据开发工程师」
  //   「Data Engineer II」被末尾的「工程师 / Engineer」从「数据」抢进「研发」。
  //   正文兜底（preferLast=false）单轮按表顺序 → 它仍在原位当**拦截器**：JD 正文几乎都写
  //   「技术 / 开发」，命中这里判出研发后会被 classifyJobFunction 的 full === "研发" 守卫挡回
  //   「其他」。挪到表末尾这道拦截就失效，正文里的「市场 / 运营」趁虚而入——实测挪走后有 340 个
  //   标题判不出职能的岗被正文误判成市场（Manager, Project Management / Lead Athlete 之流）。
  ["研发", /工程师|研发|开发|技术|engineer|developer/i, { generic: true }],
  ["运营", /用户运营|内容运营|运营|增长|operations|growth/i],
  ["市场", /市场|营销|品牌|公关|marketing|brand|\bpr\b/i],
  // 「业务拓展」是国内 BD 岗最常见的写法，旧规则只有「商务拓展」；
  // account executive / account manager 是英文招聘里销售岗的标准词（真实库实测大量落在「其他」）。
  ["销售", /销售|商务拓展|业务拓展|渠道拓展|\bbd\b|sales|客户经理|business\s*development|account\s*(executive|manager)/i],
  ["供应链", /供应链|采购|物流|仓储|supply\s*chain|procurement|logistics/i],
  // 英文补充：financial（旧规则的 finance 匹配不到 Financial Analyst）、hrbp（\bhr\b 的词边界卡在
  // HRBP 的 B 上）、talent acquisition / compliance / administrative —— 真实库里这几类全落「其他」。
  ["职能", /人力资源|招聘|\bhr\b|\bhrbp\b|财务|会计|审计|法务|法律|合规|行政|秘书|finance|financial|legal|counsel|compliance|recruit|talent\s*acquisition|human\s*resources|administrative|\badmin\b/i],
];

// 非软件「工程/工业」领域硬标记：机械 / 工艺 / 化工 / 材料 / 土木 / 电气 …
// 这些岗常含「开发 / 技术 / 工程师」等泛词，会被下方研发规则吃进「软件研发」桶，但它们属
// 制造 / 工业工程领域，不是软件研发。库里偏制造 / 车厂 → 不隔离则被「算法 / AI / 数据」等
// 映射到研发职能的查询经「相关层」误召（实锤：「AI 数据产品经理」误命中
// 「工艺技术开发（机械/自动化）」并打「高匹配 + 命中目标方向」）。
const NON_SOFTWARE_ENG_DOMAIN =
  /机械|机电|机加|钣金|工艺|化工|化学|材料|冶金|铸造|锻造|焊接|焊工|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|热处理|土木|结构工程|岩土|暖通|给排水|管道|强电|工业工程|生产工艺|制造工艺|工艺技术|纺织|印染|涂装|总装|冲压|车身|底盘|发动机|动力总成|整车|工业自动化|机械自动化|热设计|散热|结构设计|精密仪器|仪器仪表|光学|镜头|声学|射频|天线|电源|电池|电芯|储能|逆变|试剂|生物|医疗器械|临床|药物|制药|检测认证|可靠性|环境试验|工业设计|包装设计|技术文档|标准化/;

// 软件 / IT / 算法信号：命中其一则即使带工业标记仍判软件研发（机器人 / 自动驾驶 / 嵌入式软件等交叉岗）。
// 故意排除泛词 研发 / 开发 / 技术 / 工程师（它们正是误判来源），也排除过于常见的「数据」
//（真数据岗已由上方「数据」规则先行认领，无需在此兜底）。命中此正则 = 保守地「不降级」（维持原行为，安全方向）。
const SOFTWARE_ENG_SIGNAL =
  /软件|software|算法|algorithm|前端|frontend|front[\s-]?end|后端|backend|back[\s-]?end|全栈|full[\s-]?stack|客户端|服务端|嵌入式|固件|firmware|测试开发|自动化测试|sdet|运维|sre|devops|架构师|代码|编程|程序员|programmer|\bjava\b|python|golang|c\+\+|c#|\.net|javascript|typescript|\breact\b|\bvue\b|机器学习|machine\s*learning|深度学习|deep\s*learning|\bml\b|\bnlp\b|大模型|\bllm\b|\bai\b|人工智能|计算机视觉|\bcv\b|系统开发|平台开发|web|\bapp\b|小程序|数据库|database|\bsql\b|云计算|区块链/i;

// 预编译成全局匹配版：_classifyFunctionText 要拿到「最后一次命中的位置」，需要 /g 反复 exec。
// 规则表本身不带 /g（它还被别处当普通 test 用），所以在这里各存一份，避免每次调用现构造。
const JOB_FUNCTION_RULES_GLOBAL = JOB_FUNCTION_RULES.map(([fn, re, opts]) => [
  fn,
  new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g"),
  Boolean(opts && opts.generic),
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
    const [fn, re, isGeneric] = JOB_FUNCTION_RULES_GLOBAL[i];
    if (isGeneric !== useGeneric) continue;
    // 领域降级门：仅靠泛词（开发/技术/工程师）落入「研发」、却带非软件工业领域硬标记、
    // 且无任何软件信号 → 归「其他」，不塌进软件研发桶（杜绝相关层误召，见上方常量注释）。
    if (fn === "研发" && NON_SOFTWARE_ENG_DOMAIN.test(text) && !SOFTWARE_ENG_SIGNAL.test(text)) {
      continue;
    }
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

function classifyJobTitleFunction(job = {}) {
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

// 标题判出的「职能」是不是**只**来自招聘活动标签？是 → 那不是 HR 岗，可以退回看正文找真实角色。
function _titleFunctionIsRecruitEventOnly(job = {}) {
  const raw = normalizeForMatch(job?.title);
  if (!raw) return true;
  const withoutEvent = raw.replace(RECRUIT_EVENT_LABEL, " ").trim();
  if (!withoutEvent || withoutEvent === raw) return !withoutEvent;
  return _classifyFunctionText(withoutEvent, true) === "其他";
}

function classifyJobFunction(job = {}) {
  // 标题权威优先：标题是岗位职能最可靠的信号，判出干净职能就用它，避免被 job_type / summary 带偏——
  // 实锤：B站「数据科学家」挂在部门 job_type=「产品运营类」下，旧实现拼全文 → 「产品运营」先命中 →
  // 误判「产品」→ 匹配上「AI 数据产品经理」推给产品经理用户。标题「数据科学家」应判「数据」。
  // 刻意不含 job_type（部门/招聘类型，非真实角色）。
  const titleFn = classifyJobTitleFunction(job);
  // 「职能」例外：标题「2027 校园招聘」这类是**招聘活动标签**（命中「招聘」），不是 HR 岗 →
  // 退回看 标题+摘要 里的真实角色（如正文「产品经理方向」）。
  // ⚠️ 但必须先分清「活动标签」和「真 HR 岗」：旧实现对所有「职能」标题一律退回，于是
  // 「招聘HR（抖音）」（正文写"支持产品经理与算法工程师招聘"）被判成**产品岗**推给产品经理用户——
  // 正文里那些岗位名是它的招聘对象、不是它自己的职能。判据 = 剥掉活动标签后标题还能不能判出职能：
  // 「招聘HR」「招聘专员」「HRBP」剥完仍是职能 → 真 HR 岗，不退回；「2027 校园招聘」剥完什么都不剩 → 退回。
  if (titleFn !== "其他" && titleFn !== "职能") return titleFn;
  if (titleFn === "职能" && !_titleFunctionIsRecruitEventOnly(job)) return titleFn;
  const full = _classifyFunctionText(
    normalizeForMatch([job?.title, job?.summary].filter(Boolean).join(" ")),
  );
  // 正文几乎都会写 AI/技术/算法，不能把标题未判出的岗位靠兜底误判为研发。
  if (full === "研发") return titleFn;
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
];

function _matchedGroupIndexes(query) {
  const normalized = normalizeForMatch(query);
  const idxs = [];
  CHINA_KEYWORD_GROUPS.forEach((group, i) => {
    if (group.some((term) => containsTerm(normalized, term))) idxs.push(i);
  });
  return idxs;
}

function _jobSearchableText(job) {
  return normalizeForMatch(
    [job?.title, job?.company, job?.location, job?.job_type, job?.summary, job?.salary_text]
      .filter(Boolean)
      .join(" "),
  );
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

// 短的纯拉丁缩写（≤3，如 ai/ml/pm/ui/go/hr）用词边界匹配，避免 maintain→ai、google→go 这类误匹配；
// 其余（CJK 或较长词）走普通子串包含。haystack 需已 normalizeForMatch。
function containsTerm(haystack, term) {
  const h = String(haystack || "");
  const t = normalizeForMatch(term);
  if (!t) return false;
  if (/^[a-z0-9.+#-]{1,3}$/.test(t)) {
    const escaped = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`).test(h);
  }
  return h.includes(t);
}

module.exports = {
  CHINA_KEYWORD_GROUPS,
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
};
