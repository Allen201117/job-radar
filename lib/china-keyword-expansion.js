const CHINA_KEYWORD_GROUPS = [
  [
    "算法",
    "机器学习",
    "深度学习",
    "人工智能",
    "AI",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "algorithm",
    "ml",
    "llm",
    "大模型",
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
    "客户端",
    "ios",
    "android",
    "客户端开发",
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
];

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
  ["全国", "全国"],
  ["全国多地", "全国"],
  ["多地", "全国"],
  ["remote", "远程"],
  ["远程", "远程"],
]);

function expandChinaKeywordTerms(query) {
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

  return Array.from(terms)
    .map((term) => String(term || "").trim())
    .filter(Boolean);
}

// 中文 bigram 全文检索（/api/jobs/search 的 FTS 路径）用的「候选词集」——作为 SQL 有界预筛的超集，
// 之后仍由 jobFilterTier 在 JS 里精筛分层，故这里只需「不漏」(超集)：
//   = 查询命中概念组的全部同义词（精确层）∪ 与查询同职能的所有组的词（相关层候选，让 bigram 预筛也能纳入同职能岗）。
// 只保留 ≥2 字的词（1 字无法生成 bigram，且天然过泛）。元素为去空白小写。
function ftsCandidateTerms(query) {
  const qFns = queryFunctions(query);
  const terms = new Set(expandChinaKeywordTerms(query).map((t) => normalizeForMatch(t)));
  CHINA_KEYWORD_GROUPS.forEach((group, i) => {
    const fn = KEYWORD_GROUP_FUNCTIONS[i];
    if (fn && qFns.has(fn)) group.forEach((t) => terms.add(normalizeForMatch(t)));
  });
  return Array.from(terms).filter((t) => t && t.length >= 2);
}

// 把查询拆成若干「概念单元」，用于组合意图的精准匹配。
// 一个单元 = 一组同义词（OR），单元之间 AND。例如 "AI PM"：
//   命中「算法/AI」组 → 单元A=[算法,ai,大模型,...]；命中「产品」组 → 单元B=[产品经理,产品,pm,...]
//   岗位须同时命中 A 和 B → 才算「AI 产品经理」，避免把纯算法岗或纯产品岗也召回（旧逻辑是全 OR，召回过宽）。
// 查询里不属于任何组的散词（如公司名/小众词）各自成单元，也按 AND 处理 → 提升精准度。
function keywordMatchUnits(query) {
  const raw = String(query || "").trim();
  if (!raw) return [];

  const normalized = normalizeForMatch(raw);
  const units = [];

  for (const group of CHINA_KEYWORD_GROUPS) {
    if (group.some((term) => containsTerm(normalized, term))) {
      units.push(group.map(normalizeForMatch));
    }
  }

  // 散词（split 后的各 token，去掉整串本身）：未被任何已命中组覆盖的，单独成 AND 单元。
  const literals = splitKeywordTerms(raw).slice(1).map(normalizeForMatch).filter(Boolean);
  for (const lit of literals) {
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

// 查询命中的概念组对应的职能集合（去掉 null：招聘类型 / 投研 / 工程通用组无干净职能桶）。
function queryFunctions(query) {
  return new Set(
    _matchedGroupIndexes(query)
      .map((i) => KEYWORD_GROUP_FUNCTIONS[i])
      .filter(Boolean),
  );
}

function jobMatchesChinaKeyword(job, query) {
  const units = keywordMatchUnits(query);
  if (units.length === 0) return true;

  const titleText = normalizeForMatch(job?.title);
  // 正文域 = 标题之外的全部可匹配文本（摘要 / 公司 / 城市 / 类型 / 薪资）。
  // 散词（公司名等用户亲手输入的 token）靠此命中公司字段——见 china-job-intent「散词按 AND」用例。
  const bodyText = normalizeForMatch(
    [job?.company, job?.location, job?.job_type, job?.summary, job?.salary_text]
      .filter(Boolean)
      .join(" "),
  );

  // 职能门：正文（非标题）命中只在「岗位职能与查询职能相容」时才算数。
  // 治跨职能污染双向——算法岗正文写"产品"不该被 pm 召回，产品岗正文写"算法"也不该被"算法"召回。
  // 查询无职能信号（纯公司名 / 散词搜索）时放行，不误伤公司检索。
  const qFns = queryFunctions(query);
  const bodyAllowed = qFns.size === 0 || qFns.has(classifyJobFunction(job));

  // 单元间 AND、单元内 OR（组合意图精准，"AI PM" = AI ∧ 产品）；
  // 标题命中始终算数；正文命中须 非泛锚点 且 过职能门。
  return units.every((unit) =>
    unit.some(
      (term) =>
        containsTerm(titleText, term) ||
        (bodyAllowed && !isTitleOnlyAnchor(term) && containsTerm(bodyText, term)),
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

  if (/暑期实习|summer intern|summer internship/.test(text)) return "暑期实习";
  if (/日常实习|daily intern|off-cycle intern/.test(text)) return "日常实习";
  if (/管培生|管理培训生|graduate program|management trainee/.test(text)) return "管培生";
  if (/留学生|海外学生|overseas student|returnee/.test(text)) return "留学生专项";
  if (/实习|intern|internship|shixi/.test(text)) return "实习";
  if (/校招|校园招聘|应届|毕业生|campus|new grad|graduate|xiaozhao/.test(text)) return "校招";
  if (/投研|研究员|研究岗|行业研究|股票研究|equity research|investment research/.test(text)) {
    return "研究岗";
  }
  if (/兼职|part time|part-time/.test(text)) return "兼职";
  if (/社招|社会招聘|experienced|professional|full time|full-time/.test(text)) return "社招";
  if (/全职/.test(text)) return "全职";

  return null;
}

// 把细粒度 job_type / 标题归并到三大招聘类型桶之一（社招 / 校招 / 实习），用于前端筛选。
// 必须穷尽：每个岗位都落到唯一一个桶，未知信号默认社招（社招是主体）。
const RECRUITMENT_INTERN = new Set(["暑期实习", "日常实习", "实习"]);
const RECRUITMENT_CAMPUS = new Set(["校招", "管培生", "留学生专项"]);

function recruitmentCategory(job = {}) {
  const specific =
    normalizeChinaJobType({
      title: job.title,
      sourceType: job.job_type,
      url: job.jd_url || job.apply_url,
      summary: job.summary,
    }) ||
    job.job_type ||
    "";

  if (RECRUITMENT_INTERN.has(specific)) return "实习";
  if (RECRUITMENT_CAMPUS.has(specific)) return "校招";
  // 兜底：specific 可能是未归一化的原始 job_type，关键词再判一次。
  if (/实习|intern/i.test(specific)) return "实习";
  if (/校招|校园|应届|毕业生|campus|new\s?grad|graduate|管培|管理培训生|留学生|overseas student/i.test(specific)) {
    return "校招";
  }
  // P1-D 源/公司名显式标注的招聘类型（如库里的"华润电力 CR Power 校招"），治空 job_type 误堆社招。
  const company = String(job.company || "");
  if (/实习/.test(company)) return "实习";
  if (/校招|校园招聘/.test(company)) return "校招";
  return "社招";
}

// 岗位职能粗分类（产品/研发/设计/数据/运营/市场/销售/供应链/职能/其他），用于岗位卡片的强特征标签。
// 顺序敏感：先判更具体的（产品经理优先于「含算法字样」），命中即返回。
const JOB_FUNCTION_RULES = [
  // 角色锚定：只在明确的产品角色词命中（删掉裸词"产品"/"产品设计师"），
  // 否则"产品研发/产品测试/硬件产品工程师"等会被裸词误吃成产品（研发信号本应优先）。
  ["产品", /产品经理|产品运营|产品策划|产品负责人|产品总监|产品专家|product\s*manager|product\s*owner|\bpm\b|\bpo\b/i],
  ["设计", /视觉设计|交互设计|ui\s*设计|ux|平面设计|设计师|designer/i],
  ["数据", /数据分析|数据科学|数据工程|大数据|数据挖掘|data\s*(analyst|scien|engineer)|\bbi\b|商业分析/i],
  ["研发", /工程师|研发|开发|算法|前端|后端|客户端|测试|运维|架构|嵌入式|硬件|engineer|developer|\bsde\b|\bsre\b|programmer|software|技术/i],
  ["运营", /用户运营|内容运营|运营|增长|operations|growth/i],
  ["市场", /市场|营销|品牌|公关|marketing|brand|\bpr\b/i],
  ["销售", /销售|商务拓展|\bbd\b|sales|客户经理|business\s*development/i],
  ["供应链", /供应链|采购|物流|仓储|supply\s*chain|procurement|logistics/i],
  ["职能", /人力资源|招聘|\bhr\b|财务|会计|审计|法务|法律|合规|行政|finance|legal|recruit|human\s*resources/i],
];

function classifyJobFunction(job = {}) {
  const text = normalizeForMatch([job?.title, job?.job_type, job?.summary].filter(Boolean).join(" "));
  if (!text) return "其他";
  for (const rule of JOB_FUNCTION_RULES) {
    if (rule[1].test(text)) return String(rule[0]);
  }
  return "其他";
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
  null, // 22 软件（跨语言锚点；同上，单列以免「软件」过宽等价「工程师」）
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
function keywordMatchTier(job, query) {
  if (jobMatchesChinaKeyword(job, query)) return "exact";

  const qGroups = _matchedGroupIndexes(query);
  const qFunctions = new Set(qGroups.map((i) => KEYWORD_GROUP_FUNCTIONS[i]).filter(Boolean));
  if (qFunctions.size === 0) return null; // 查询无职能映射（实习/投研/散词）→ 不滥召相关层
  if (!qFunctions.has(classifyJobFunction(job))) return null; // 不同职能

  // 兄弟组排除：岗位被"非查询组、但映射到同职能"的细分组精确命中 → 属于那个细分（如前端），不算本查询相关。
  const searchable = _jobSearchableText(job);
  const qGroupSet = new Set(qGroups);
  for (let i = 0; i < CHINA_KEYWORD_GROUPS.length; i++) {
    if (qGroupSet.has(i)) continue;
    const fn = KEYWORD_GROUP_FUNCTIONS[i];
    if (!fn || !qFunctions.has(fn)) continue;
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
  classifyJobFunction,
  expandChinaKeywordTerms,
  ftsCandidateTerms,
  jobMatchesChinaKeyword,
  keywordMatchTier,
  keywordMatchUnits,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  normalizeChinaLocation,
  recruitmentCategory,
};
