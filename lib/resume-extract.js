// 简历结构化抽取：prompt 构造 + LLM 输出归一化（纯函数，单测不打网络）。
// 归一化负责把模型的不确定输出收敛成稳定 schema，并对基本信息做脱敏（PIPL：不存非必要敏感信息）。

const MAX_TEXT = 12000;
const MAX_ITEMS = 12;
const MAX_SKILLS = 30;
const MAX_TAGS = 8;
const STAGES = ["实习", "校招", "社招"];

// 目标 JSON 形状，喂给模型做约束。
const SCHEMA_HINT = `{
  "headline": "一句话求职定位，如『数据分析实习生』",
  "basic_info": { "name": "姓名", "city": "所在城市", "contact": "邮箱或手机号原文" },
  "target_roles": ["目标岗位方向"],
  "target_locations": ["期望城市"],
  "skills": ["技能标签"],
  "industries": ["行业"],
  "experience_stage": "实习|校招|社招 三选一，判断不了给空串",
  "education": [{ "school": "", "degree": "本科/硕士/博士", "major": "", "start": "2019.09", "end": "2023.06" }],
  "internships": [{ "company": "", "role": "", "start": "", "end": "", "summary": "一句话职责/成果" }],
  "projects": [{ "name": "", "role": "", "stack": "技术栈/工具", "outcome": "成果，量化优先" }]
}`;

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
    skills: uniqStrings(data.skills, MAX_SKILLS),
    industries: uniqStrings(data.industries, MAX_TAGS),
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
  normalizeResumeProfile,
};
