const test = require("node:test");
const assert = require("node:assert/strict");
const {
  MAX_SKILLS,
  buildResumeMessages,
  normalizeResumeProfile,
  normalizeSkillTokens,
} = require("../lib/resume-extract");

test("normalizeSkillTokens 拆括号技能并丢弃程度说明", () => {
  assert.deepEqual(
    normalizeSkillTokens([
      "原型设计（Figma / Axure）",
      "Python（基础）",
      "Excel（高级）",
      "Python（Pandas、NumPy）",
      "CUDA基础",
    ]),
    ["原型设计", "Figma", "Axure", "Python", "Excel", "Pandas", "NumPy", "CUDA"],
  );
});

test("normalizeSkillTokens 保留白名单中的完整英文技能名", () => {
  assert.deepEqual(
    normalizeSkillTokens(["CI/CD", "Next.js", "A/B 实验", "Power BI"]),
    ["CI/CD", "Next.js", "A/B 实验", "Power BI"],
  );
});

test("normalizeSkillTokens 识别所有约定分隔符", () => {
  assert.deepEqual(
    normalizeSkillTokens(["JS/TS、SQL, BI，PPT"]),
    ["JS", "TS", "SQL", "BI", "PPT"],
  );
});

test("normalizeSkillTokens 不拆中文长句", () => {
  const longSentence = "负责用户增长策略制定与跨团队协同推进，持续复盘核心指标表现";
  assert.deepEqual(normalizeSkillTokens([longSentence]), [longSentence]);
});

test("normalizeSkillTokens 大小写不敏感去重并受技能上限约束", () => {
  const values = ["Python", "python", ...Array.from({ length: MAX_SKILLS }, (_, i) => `skill-${i}`)];
  const normalized = normalizeSkillTokens(values);
  assert.equal(normalized[0], "Python");
  assert.equal(normalized.length, MAX_SKILLS);
});

test("normalizeResumeProfile 保持既有 schema 并使用归一化技能", () => {
  const out = normalizeResumeProfile({
    headline: "算法实习生",
    basic_info: { name: "张三", contact: "13812345678" },
    target_roles: ["算法工程师"],
    target_locations: ["北京"],
    skills: ["Python（Pandas、NumPy）"],
    industries: ["互联网/科技"],
    experience_stage: "实习",
    education: [{ school: "某大学" }],
    internships: [{ company: "某公司" }],
    projects: [{ name: "某项目" }],
  });

  assert.deepEqual(Object.keys(out), [
    "headline", "basic_info", "target_roles", "target_locations", "skills", "industries",
    "experience_stage", "seniority", "education", "internships", "projects",
    "education_summary", "experience_summary",
  ]);
  assert.deepEqual(out.skills, ["Python", "Pandas", "NumPy"]);
  assert.equal(out.experience_stage, "实习");
});

test("buildResumeMessages 明确行业枚举、阶段规则与岗位方向粒度", () => {
  const messages = buildResumeMessages("简历原文");
  const prompt = messages.map((message) => message.content).join("\n");

  for (const industry of [
    "互联网/科技", "金融", "消费/零售", "制造/工业", "汽车/出行", "医疗/医药",
    "能源/化工", "地产/建筑", "物流/供应链", "传媒/文娱", "教育",
  ]) {
    assert.match(prompt, new RegExp(industry.replace("/", "\\/")));
  }
  assert.match(prompt, /在找实习/);
  assert.match(prompt, /应届生/);
  assert.match(prompt, /正式全职工作经历/);
  assert.match(prompt, /岗位方向/);
  assert.match(prompt, /最多 3 个/);
  // 两条「宁可少填」的保守约束必须留在 prompt 里：industries 与 experience_stage 都是硬过滤门。
  // live 实测过两种翻车：行业填 6 个 → 过滤器等于全开；仅凭「实习经历多」判成实习 → 严格门把
  // 往届生的岗位全拒光。所以模型侧的保守措辞和下游的代码级兜底要一起在。
  assert.match(prompt, /最多 2 个/);
  assert.match(prompt, /拿不准时空串是正确答案/);
});

test("industries 只保留权威枚举内的类目，最多 2 个（硬门不能被凑数的行业开成全开）", () => {
  // live 实测：模型给一份互联网简历吐过 6 个行业（含自造的「人工智能」）。
  const p = normalizeResumeProfile({
    industries: ["人工智能", "金融", "消费/零售", "制造/工业", "汽车/出行"],
  });
  assert.deepEqual(p.industries, ["互联网/科技", "金融"]);
});

test("industries 全是自造类目且归一不出 → 空数组（宁可不设门，也不要错误的门）", () => {
  const p = normalizeResumeProfile({ industries: ["星际贸易", "时空管理"] });
  assert.deepEqual(p.industries, []);
});
