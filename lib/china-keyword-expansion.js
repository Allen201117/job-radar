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

// 全文检索（/api/jobs/search 的 FTS 路径）用的「候选词集」= 查询命中概念组的全部同义词（精确层，含跨语言，如 产品→product manager）。
// 之后仍由 jobFilterTier 在 JS 里精筛分层。**刻意不并入「同职能兄弟组」**：那会让 算法/后端(都属研发)这类查询
// 把全部研发岗都拉成候选(上海算法实测候选爆→8.9s)，而这些「同职能但非该方向」岗对关键词搜索价值低。
// 收窄到精确同义词后：候选≈结果、秒级、且更精准(算法搜出的是算法岗，不是所有工程师)。
// 只保留 ≥2 字的词（1 字无法生成 bigram/整词，且天然过泛）。元素为去空白小写。
function ftsCandidateTerms(query) {
  const terms = new Set(expandChinaKeywordTerms(query).map((t) => normalizeForMatch(t)));
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

  if (/暑期实习|summer\s+intern(?:ship)?s?\b/.test(text)) return "暑期实习";
  if (/日常实习|daily\s+intern(?:ship)?s?\b|off-?cycle\s+intern(?:ship)?s?\b/.test(text)) return "日常实习";
  if (/管培生|管理培训生|graduate\s+program|management\s+trainee/.test(text)) return "管培生";
  if (/留学生|海外学生|overseas student|returnee/.test(text)) return "留学生专项";
  // 英文 intern/graduate 必须用**词边界**：否则 "internal/international/internet" 会把全职岗误判成实习，
  // "undergraduate" 会误判成校招（本次线上 Intel 全职高级工程师因 JD 含 "internal" 被标实习的真因）。
  if (/实习|\bintern(?:ship)?s?\b|shixi/.test(text)) return "实习";
  // 校招只认**强标记**。刻意砍掉弱词「毕业生」("985毕业生优先"多为社招) 和「graduate」(=硕士学历) ——
  // 这两个在整段 JD 正文里高频误命中，是"社招被误标校招"的写入端源头（见 recruitmentCategory 同款收紧）。
  // 保留 campus / xiaozhao：它们既是 url 渠道信号、也是 discovery 的输入别名（campus→校招），中文正文极少出现。
  if (/校招|校园招聘|应届|[0-9]{2,4}届|campus|new\s+grads?\b|xiaozhao/.test(text)) return "校招";
  if (/投研|研究员|研究岗|行业研究|股票研究|equity research|investment research/.test(text)) {
    return "研究岗";
  }
  if (/兼职|part time|part-time/.test(text)) return "兼职";
  if (/社招|社会招聘|experienced|professional|full time|full-time/.test(text)) return "社招";
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
  const t = String(text).replace(/\s+/g, "").toLowerCase();
  const m =
    t.match(/(\d{1,2})[-~至到](\d{1,2})年(?!级)/) || // 3-5年 / 3~5年 / 3到5年
    t.match(/(\d{1,2})年以上/) || // 3年以上
    t.match(/(\d{1,2})年(?:以上)?(?:工作|相关|以上工作)?经验/) || // 3年(相关/工作)经验
    t.match(/(\d{1,2})[-~to]+(\d{1,2})years?/) || // 3-5 years
    t.match(/(\d{1,2})\+?years?(?:ofexperience)?/); // 5+ years / 5 years
  return m ? parseInt(m[1], 10) : null;
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
  if (/校招|校园招聘|应届|管培生|管理培训生|留学生专项|campus/i.test(t)) return "校招";
  return null;
}

// 标题/正文里的**强**校招标记（会自报家门的：应届 / 20XX届 / 校园招聘 / 管培生 / new grad）。
// 刻意不含弱词：光秃秃的"毕业生"("985毕业生优先"多为社招)、"graduate"(=硕士学历)、"校园"(=智慧校园产品) ——
// 这些在整段 JD 正文里高频误命中，正是"社招被误标校招"的根因。
function hasStrongCampusSignal(text) {
  return (
    /应届|[0-9]{2,4}届|校园招聘|校招|管培生|管理培训生|留学生专项/.test(text) ||
    /new\s?grads?\b|campus\s?(?:recruit|hiring)|graduate\s+program/i.test(text)
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
    /\/(shixi|intern)/i.test(url)
  ) {
    return "实习";
  }

  // 层2：明确要求 ≥2 年经验 → 强制社招。校招=应届0经验，与之矛盾。优先级高于源 job_type：
  // 治"源头把资深岗错标校招"（如光刻主任工程师 job_type=校招 但要 8 年）。
  if (_demandsPriorExperience(job)) return "社招";

  // 层3：信任来源自报的 job_type（结构化 recruitType/渠道最可信，且此处只看字段本身不被正文污染）。
  const declared = sourceDeclaredCategory(job.job_type);
  if (declared) return declared; // 到这里 declared ∈ {校招, 社招}

  // 层4：url 路径里的校招渠道信号（/xiaozhao /campus）。
  if (/\/(xiaozhao|campus)/i.test(url)) return "校招";

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
  if (/\/(shixi|intern|xiaozhao|campus)/i.test(url)) return true;
  if (hasInternSignal(String(job.title || ""))) return true;
  if (hasStrongCampusSignal(`${job.title || ""} ${job.summary || ""}`)) return true;
  const company = String(job.company || "");
  return /实习|校招|校园招聘/.test(company);
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

// 非软件「工程/工业」领域硬标记：机械 / 工艺 / 化工 / 材料 / 土木 / 电气 …
// 这些岗常含「开发 / 技术 / 工程师」等泛词，会被下方研发规则吃进「软件研发」桶，但它们属
// 制造 / 工业工程领域，不是软件研发。库里偏制造 / 车厂 → 不隔离则被「算法 / AI / 数据」等
// 映射到研发职能的查询经「相关层」误召（实锤：「AI 数据产品经理」误命中
// 「工艺技术开发（机械/自动化）」并打「高匹配 + 命中目标方向」）。
const NON_SOFTWARE_ENG_DOMAIN =
  /机械|机电|机加|钣金|工艺|化工|化学|材料|冶金|铸造|锻造|焊接|焊工|模具|注塑|液压|气动|数控|机床|刀具|工装|夹具|热处理|土木|结构工程|岩土|暖通|给排水|管道|强电|工业工程|生产工艺|制造工艺|工艺技术|纺织|印染|涂装|总装|冲压|车身|底盘|发动机|动力总成|整车|工业自动化|机械自动化/;

// 软件 / IT / 算法信号：命中其一则即使带工业标记仍判软件研发（机器人 / 自动驾驶 / 嵌入式软件等交叉岗）。
// 故意排除泛词 研发 / 开发 / 技术 / 工程师（它们正是误判来源），也排除过于常见的「数据」
//（真数据岗已由上方「数据」规则先行认领，无需在此兜底）。命中此正则 = 保守地「不降级」（维持原行为，安全方向）。
const SOFTWARE_ENG_SIGNAL =
  /软件|software|算法|algorithm|前端|frontend|front[\s-]?end|后端|backend|back[\s-]?end|全栈|full[\s-]?stack|客户端|服务端|嵌入式|固件|firmware|测试开发|自动化测试|sdet|运维|sre|devops|架构师|代码|编程|程序员|programmer|\bjava\b|python|golang|c\+\+|c#|\.net|javascript|typescript|\breact\b|\bvue\b|机器学习|machine\s*learning|深度学习|deep\s*learning|\bml\b|\bnlp\b|大模型|\bllm\b|\bai\b|人工智能|计算机视觉|\bcv\b|系统开发|平台开发|web|\bapp\b|小程序|数据库|database|\bsql\b|云计算|区块链/i;

// 对一段已 normalize 的文本跑职能规则（含非软件工业领域降级门）。判不出返回 "其他"。
function _classifyFunctionText(text) {
  if (!text) return "其他";
  for (const rule of JOB_FUNCTION_RULES) {
    if (rule[1].test(text)) {
      // 领域降级门：仅靠泛词（开发/技术/工程师）落入「研发」、却带非软件工业领域硬标记、
      // 且无任何软件信号 → 归「其他」，不塌进软件研发桶（杜绝相关层误召，见上方常量注释）。
      if (
        rule[0] === "研发" &&
        NON_SOFTWARE_ENG_DOMAIN.test(text) &&
        !SOFTWARE_ENG_SIGNAL.test(text)
      ) {
        continue;
      }
      return String(rule[0]);
    }
  }
  return "其他";
}

function classifyJobFunction(job = {}) {
  // 标题权威优先：标题是岗位职能最可靠的信号，判出干净职能就用它，避免被 job_type / summary 带偏——
  // 实锤：B站「数据科学家」挂在部门 job_type=「产品运营类」下，旧实现拼全文 → 「产品运营」先命中 →
  // 误判「产品」→ 匹配上「AI 数据产品经理」推给产品经理用户。标题「数据科学家」应判「数据」。
  // 刻意不含 job_type（部门/招聘类型，非真实角色）。
  const titleFn = _classifyFunctionText(normalizeForMatch(job?.title));
  // 「职能」例外：标题「2024 校园招聘」这类是招聘活动标签（命中「招聘」），不是 HR 岗 →
  // 退回看 标题+摘要 里的真实角色（如正文「产品经理方向」）；真 HR 岗（招聘专员）正文不会翻盘、仍判职能。
  if (titleFn !== "其他" && titleFn !== "职能") return titleFn;
  const full = _classifyFunctionText(
    normalizeForMatch([job?.title, job?.summary].filter(Boolean).join(" ")),
  );
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
  CITY_ALIASES,
  classifyJobFunction,
  expandChinaKeywordTerms,
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
