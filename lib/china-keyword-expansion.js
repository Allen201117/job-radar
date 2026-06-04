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

function jobMatchesChinaKeyword(job, query) {
  const terms = expandChinaKeywordTerms(query).map(normalizeForMatch);
  if (terms.length === 0) return true;

  const searchable = normalizeForMatch(
    [
      job?.title,
      job?.company,
      job?.location,
      job?.job_type,
      job?.summary,
      job?.salary_text,
    ]
      .filter(Boolean)
      .join(" "),
  );

  return terms.some((term) => containsTerm(searchable, term));
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
  if (/实习|intern|internship/.test(text)) return "实习";
  if (/校招|校园招聘|应届|毕业生|campus|new grad|graduate/.test(text)) return "校招";
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
  return "社招";
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
  expandChinaKeywordTerms,
  jobMatchesChinaKeyword,
  normalizeChinaCity,
  normalizeChinaJobFields,
  normalizeChinaJobType,
  normalizeChinaLocation,
  recruitmentCategory,
};
