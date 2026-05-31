const MAX_RESUME_TEXT_BYTES = 1024 * 1024;

const ROLE_KEYWORDS = [
  ["数据分析", ["数据分析", "data analyst", "数据运营", "BI", "商业分析"]],
  ["商业分析", ["商业分析", "business analyst"]],
  ["产品经理", ["产品经理", "产品实习", "product manager", "PM", "AI 产品"]],
  ["算法", ["算法", "机器学习", "深度学习", "大模型", "推荐系统", "NLP", "CV"]],
  ["投研", ["投研", "行业研究", "股票研究", "固收", "量化", "equity research"]],
  ["管培生", ["管培生", "管理培训生", "management trainee", "graduate program"]],
  ["运营", ["运营", "用户增长", "增长运营", "内容运营"]],
];

const SKILL_KEYWORDS = [
  "Python",
  "SQL",
  "R",
  "Excel",
  "Tableau",
  "Power BI",
  "Figma",
  "Axure",
  "AI 产品",
  "机器学习",
  "深度学习",
  "大模型",
  "RAG",
  "Prompt",
  "A/B 实验",
  "用户研究",
  "数据分析",
  "数据可视化",
  "Pandas",
  "Spark",
];

const CITY_KEYWORDS = [
  "北京",
  "上海",
  "深圳",
  "广州",
  "杭州",
  "南京",
  "苏州",
  "成都",
  "武汉",
  "西安",
  "香港",
  "新加坡",
  "远程",
];

function parseResumeText(text) {
  const cleanText = normalizeText(text);
  const lines = splitLines(cleanText);
  const headline = extractHeadline(lines);
  const targetRoles = matchRoles(headline).length
    ? matchRoles(headline)
    : matchRoles(cleanText);
  const targetLocations = matchCities(cleanText);
  const skills = matchResumeSkills(lines, cleanText, targetRoles);
  const education = extractSectionLines(lines, /教育|学历|学校|大学|学院|本科|硕士|博士/);
  const experience = extractSectionLines(lines, /实习|经历|工作|项目|负责|公司|研究/);
  const experienceStage = inferSeniority(cleanText);

  return {
    headline,
    target_roles: targetRoles,
    target_locations: targetLocations,
    skills,
    industries: matchIndustries(cleanText),
    seniority: experienceStage,
    experience_stage: experienceStage,
    education,
    experience,
    education_summary: summarizeLines(education),
    experience_summary: summarizeLines(experience),
    summary: buildSummary({ headline, targetRoles, targetLocations, skills }),
  };
}

function buildPreferencesFromResumeProfile(profile) {
  return {
    target_locations: unique(profile?.target_locations || []).slice(0, 6),
    target_roles: unique(profile?.target_roles || []).slice(0, 6),
    target_keywords: unique(profile?.skills || []).slice(0, 16),
  };
}

function validateResumeUploadInput({ fileName, fileType, fileSize, text }) {
  if (Number(fileSize || 0) > MAX_RESUME_TEXT_BYTES) {
    return { ok: false, reason: "file_too_large" };
  }

  const ext = getExtension(fileName);
  const type = String(fileType || "").toLowerCase();
  const textLike =
    ["txt", "md", "markdown"].includes(ext) ||
    type.startsWith("text/") ||
    type === "application/json";
  if (!textLike) return { ok: false, reason: "unsupported_file_type" };

  if (!String(text || "").trim()) return { ok: false, reason: "empty_resume_text" };
  return { ok: true, reason: null };
}

function normalizeText(text) {
  return String(text || "")
    .replace(/\r/g, "\n")
    .replace(/\t/g, " ")
    .replace(/[ ]{2,}/g, " ")
    .trim();
}

function splitLines(text) {
  return normalizeText(text)
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function extractHeadline(lines) {
  const intentLine = lines.find((line) => /求职意向|目标岗位|应聘岗位|期望岗位/.test(line));
  if (intentLine) {
    return cleanupLabel(intentLine).slice(0, 80);
  }

  const firstMeaningful = lines.find((line) => /岗位|分析|产品|算法|投研|运营|实习|校招/.test(line));
  return (firstMeaningful || lines[0] || "未命名用户画像").slice(0, 80);
}

function matchRoles(text) {
  const normalized = text.toLowerCase();
  const roles = [];
  for (const [role, aliases] of ROLE_KEYWORDS) {
    if (aliases.some((alias) => normalized.includes(alias.toLowerCase()))) {
      roles.push(role);
    }
  }
  return unique(roles);
}

function matchCities(text) {
  return orderTermsByOccurrence(text, CITY_KEYWORDS);
}

function matchSkills(text) {
  return orderTermsByOccurrence(text, SKILL_KEYWORDS);
}

function matchResumeSkills(lines, text, targetRoles) {
  const skillText = lines
    .filter((line) => /技能|技术栈|工具|熟练|掌握/.test(line))
    .join("\n");
  const explicitSkills = matchSkills(skillText);
  const extraSkills = matchSkills(text).filter((skill) => {
    if (targetRoles.includes("数据分析") && skill === "数据分析") return false;
    return !explicitSkills.includes(skill);
  });

  return unique([...explicitSkills, ...extraSkills]);
}

function matchIndustries(text) {
  const industries = [];
  const signals = [
    ["互联网", /互联网|电商|平台|用户增长/],
    ["金融", /金融|投研|证券|基金|银行|量化/],
    ["AI", /AI|人工智能|大模型|机器学习|深度学习|RAG|Prompt/i],
    ["咨询", /咨询|战略|商业分析/],
  ];
  for (const [industry, pattern] of signals) {
    if (pattern.test(text)) industries.push(industry);
  }
  return industries;
}

function inferSeniority(text) {
  if (/暑期实习|日常实习|实习|intern/i.test(text)) return "实习";
  if (/校招|应届|毕业生|new grad|campus/i.test(text)) return "校招";
  if (/社招|工作经验|全职|experienced/i.test(text)) return "社招";
  return "未判断";
}

function extractSectionLines(lines, pattern) {
  return lines
    .filter((line) => pattern.test(line))
    .map((line) => line.slice(0, 160))
    .slice(0, 8);
}

function summarizeLines(lines) {
  return (lines || [])
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .join("；")
    .slice(0, 320);
}

function buildSummary({ headline, targetRoles, targetLocations, skills }) {
  return [
    headline,
    targetRoles.length ? `方向：${targetRoles.join("、")}` : "",
    targetLocations.length ? `城市：${targetLocations.join("、")}` : "",
    skills.length ? `技能：${skills.slice(0, 8).join("、")}` : "",
  ]
    .filter(Boolean)
    .join("；");
}

function cleanupLabel(line) {
  return String(line || "")
    .replace(/^(求职意向|目标岗位|应聘岗位|期望岗位)\s*[:：]\s*/i, "")
    .trim();
}

function getExtension(fileName) {
  const match = String(fileName || "").toLowerCase().match(/\.([a-z0-9]+)$/);
  return match ? match[1] : "";
}

function unique(values) {
  return Array.from(new Set((values || []).filter(Boolean)));
}

function orderTermsByOccurrence(text, terms) {
  const normalized = String(text || "").toLowerCase();
  return terms
    .map((term) => ({
      term,
      index: normalized.indexOf(term.toLowerCase()),
    }))
    .filter((item) => item.index >= 0)
    .sort((a, b) => a.index - b.index || a.term.length - b.term.length)
    .map((item) => item.term);
}

module.exports = {
  MAX_RESUME_TEXT_BYTES,
  buildPreferencesFromResumeProfile,
  parseResumeText,
  validateResumeUploadInput,
};
