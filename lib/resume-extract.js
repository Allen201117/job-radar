// 简历结构化抽取：prompt 构造 + LLM 输出归一化（纯函数，单测不打网络）。
// 归一化负责把模型的不确定输出收敛成稳定 schema，并对基本信息做脱敏（PIPL：不存非必要敏感信息）。
const { INDUSTRY_CATEGORIES, canonicalizeUserIndustry } = require("./company-industry");

const MAX_TEXT = 12000;
const MAX_ITEMS = 12;
const MAX_SKILLS = 30;
const MAX_TAGS = 8;
const STAGES = ["实习", "校招", "社招"];
const SKILL_TOKEN_WHITELIST = ["CI/CD", "Next.js", "A/B 实验", "Power BI"];
const SKILL_DEGREE_MODIFIERS = ["基础", "入门", "熟练", "精通", "高级", "初级", "了解", "掌握"];
const SKILL_WHITELIST_KEYS = new Set(SKILL_TOKEN_WHITELIST.map((item) => item.toLowerCase()));

// 复用公司行业分类器的权威枚举，避免模型输出与下游跨行业门不在同一类目空间。
const INDUSTRY_ENUMERATION = INDUSTRY_CATEGORIES.join("、");

// 目标 JSON 形状与字段判定规则，喂给模型做约束。
const SCHEMA_HINT = `{
  "headline": "一句话求职定位，如『数据分析实习生』",
  "basic_info": { "name": "姓名", "city": "所在城市", "contact": "邮箱或手机号原文" },
  "target_roles": ["目标岗位方向，如『产品经理』『算法工程师』『数据分析师』"],
  "target_locations": ["期望城市"],
  "skills": ["技能标签"],
  "industries": ["行业类目"],
  "experience_stage": "实习|校招|社招 三选一，判断不了给空串",
  "education": [{ "school": "", "degree": "本科/硕士/博士", "major": "", "start": "2019.09", "end": "2023.06" }],
  "internships": [{ "company": "", "role": "", "start": "", "end": "", "summary": "一句话职责/成果" }],
  "projects": [{ "name": "", "role": "", "stack": "技术栈/工具", "outcome": "成果，量化优先" }]
}

字段规则：
- target_roles：输出求职者想做的岗位方向，最多 3 个，按意愿强弱排序；不要输出技能、行业或公司名。
- industries：**只能逐字使用**「${INDUSTRY_ENUMERATION}」里的类目，不得自造（如「人工智能」不是合法类目，互联网公司一律归「互联网/科技」）。
  **最多 2 个**，只填简历里真实出现过的公司/项目所属行业，按相关度排序；一家公司都判不出就给空数组。
  ⚠️ 这个字段会被用作岗位推荐的行业硬过滤，宁可少填也不要凑数——多填一个不相关行业等于把过滤器关掉。
- experience_stage：**只有简历明确表达了求职阶段意向时才填**，否则一律填空串。
  「在找实习 / 求职意向写着实习生」→「实习」；「应届生 / 校招 / 管培生 / 20xx 届」→「校招」；
  「有正式全职工作经历（非实习）」→「社招」。
  ⚠️ **不要只凭「简历里实习经历多」就判「实习」**——很多往届生也只有实习经历。这个字段是严格过滤门，
  判错会让求职者一个岗位都收不到，拿不准时空串是正确答案。`;

function buildResumeMessages(text) {
  const system =
    "你是严谨的简历结构化抽取器。只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。" +
    "严格按给定字段抽取；信息缺失就给空字符串或空数组，绝不编造。" +
    "教育/实习/项目按时间倒序。不要输出与简历无关的内容。";
  const user =
    `请从下面的简历原文中抽取结构化信息，输出 JSON，键名与示例完全一致：\n${SCHEMA_HINT}\n\n` +
    `简历原文：\n"""\n${String(text || "").slice(0, MAX_TEXT)}\n"""`;
  return [
    { role: "system", content: system },
    { role: "user", content: user },
  ];
}

// —— 脱敏 —— 邮箱保留首字符与域名，手机号保留前 3 后 4。
function maskContact(value) {
  let s = String(value || "").trim();
  if (!s) return "";
  s = s.replace(/([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g, "$1***$2");
  s = s.replace(/(?<!\d)(\d{3})\d{4}(\d{4})(?!\d)/g, "$1****$2");
  return s.slice(0, 60);
}

function str(value, max = 120) {
  return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, max);
}

function uniqStrings(value, maxItems, maxLen = 40) {
  const list = Array.isArray(value) ? value : value ? [value] : [];
  const out = [];
  for (const item of list) {
    const s = str(item, maxLen);
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= maxItems) break;
  }
  return out;
}

// 行业硬过滤：prompt 只是软约束，模型仍会自造类目（live 实测吐过「人工智能」）。
// 这里做代码级保证：① 只留权威枚举里逐字存在的类目，经 canonicalizeUserIndustry 归一后再比对，
// 让「互联网」「科技」这类近似写法能落到「互联网/科技」；② 上限 2 个。
// 上限的理由：industries 是岗位推荐的行业硬门，用户填 6 个行业等于把门开到全开，
// 还不如只保留最相关的两个——宁可漏放行，不可把过滤器变成摆设。
const MAX_INDUSTRIES = 2;
const INDUSTRY_CATEGORY_SET = new Set(INDUSTRY_CATEGORIES);

function normalizeIndustries(value) {
  const out = [];
  for (const raw of uniqStrings(value, MAX_TAGS)) {
    const canonical = INDUSTRY_CATEGORY_SET.has(raw) ? raw : canonicalizeUserIndustry(raw);
    if (!canonical || !INDUSTRY_CATEGORY_SET.has(canonical) || out.includes(canonical)) continue;
    out.push(canonical);
    if (out.length >= MAX_INDUSTRIES) break;
  }
  return out;
}

function isWhitelistedSkill(value) {
  return SKILL_WHITELIST_KEYS.has(String(value || "").toLowerCase());
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function splitSkillParts(value) {
  let text = String(value || "");
  const protectedValues = [];

  // 斜杠既可能是分隔符，也可能属于技能名；先保护白名单，避免把 CI/CD 等拆坏。
  for (const skill of SKILL_TOKEN_WHITELIST) {
    const pattern = new RegExp(escapeRegExp(skill), "gi");
    text = text.replace(pattern, (matched) => {
      const marker = `__SKILL_TOKEN_${protectedValues.length}__`;
      protectedValues.push(matched);
      return marker;
    });
  }

  return text
    .split(/[\/、,，]/)
    .map((part) => part.replace(/__SKILL_TOKEN_(\d+)__/g, (_, index) => protectedValues[Number(index)]));
}

function stripTrailingSkillDegree(value) {
  const s = str(value, 120);
  for (const modifier of SKILL_DEGREE_MODIFIERS) {
    if (s.endsWith(modifier) && s.length > modifier.length) {
      return s.slice(0, -modifier.length).trim();
    }
  }
  return s;
}

function normalizeSkillTokens(value, maxItems = MAX_SKILLS) {
  const list = Array.isArray(value) ? value : value ? [value] : [];
  const out = [];
  const seen = new Set();
  const add = (item) => {
    const skill = stripTrailingSkillDegree(item);
    const key = skill.toLowerCase();
    if (skill && !seen.has(key) && out.length < maxItems) {
      seen.add(key);
      out.push(skill);
    }
  };

  for (const raw of list) {
    const skill = str(raw, 120);
    if (!skill) continue;
    if (isWhitelistedSkill(skill) || (skill.length > 20 && !/[（(]/.test(skill))) {
      add(skill);
      continue;
    }

    const bracketMatch = skill.match(/^(.+?)[（(]([^（）()]*)[）)]$/);
    if (bracketMatch) {
      for (const part of splitSkillParts(bracketMatch[1])) add(part);
      const bracketContent = str(bracketMatch[2], 120);
      if (!SKILL_DEGREE_MODIFIERS.includes(bracketContent)) {
        for (const part of splitSkillParts(bracketContent)) add(part);
      }
      continue;
    }

    for (const part of splitSkillParts(skill)) add(part);
  }
  return out;
}

function objectArray(value, maxItems, fields) {
  const list = Array.isArray(value) ? value : [];
  const out = [];
  for (const raw of list) {
    if (!raw || typeof raw !== "object") continue;
    const obj = {};
    let hasContent = false;
    for (const [key, max] of fields) {
      obj[key] = str(raw[key], max);
      if (obj[key]) hasContent = true;
    }
    if (hasContent) out.push(obj);
    if (out.length >= maxItems) break;
  }
  return out;
}

function normalizeStage(value) {
  const s = str(value, 8);
  return STAGES.includes(s) ? s : "";
}

function normalizeResumeProfile(raw) {
  const data = raw && typeof raw === "object" ? raw : {};
  const basic = data.basic_info && typeof data.basic_info === "object" ? data.basic_info : {};

  const education = objectArray(data.education, MAX_ITEMS, [
    ["school", 80],
    ["degree", 24],
    ["major", 60],
    ["start", 20],
    ["end", 20],
  ]);
  const internships = objectArray(data.internships, MAX_ITEMS, [
    ["company", 80],
    ["role", 60],
    ["start", 20],
    ["end", 20],
    ["summary", 240],
  ]);
  const projects = objectArray(data.projects, MAX_ITEMS, [
    ["name", 80],
    ["role", 60],
    ["stack", 120],
    ["outcome", 240],
  ]);

  const stage = normalizeStage(data.experience_stage || data.seniority);

  return {
    headline: str(data.headline, 120),
    basic_info: {
      name: str(basic.name, 40),
      city: str(basic.city || basic.location, 40),
      contact: maskContact(basic.contact || basic.email || basic.phone),
    },
    target_roles: uniqStrings(data.target_roles, MAX_TAGS),
    target_locations: uniqStrings(data.target_locations, MAX_TAGS),
    skills: normalizeSkillTokens(data.skills),
    industries: normalizeIndustries(data.industries),
    experience_stage: stage,
    seniority: stage,
    education,
    internships,
    projects,
    education_summary: summarizeEducation(education),
    experience_summary: summarizeExperience(internships, projects),
  };
}

function summarizeEducation(education) {
  return education
    .map((e) => [e.school, e.major, e.degree].filter(Boolean).join(" "))
    .filter(Boolean)
    .join("；")
    .slice(0, 320);
}

function summarizeExperience(internships, projects) {
  return [...internships, ...projects]
    .map((e) => e.company || e.name || e.role)
    .filter(Boolean)
    .join("；")
    .slice(0, 320);
}

module.exports = {
  MAX_ITEMS,
  MAX_SKILLS,
  STAGES,
  buildResumeMessages,
  maskContact,
  normalizeSkillTokens,
  normalizeResumeProfile,
};
