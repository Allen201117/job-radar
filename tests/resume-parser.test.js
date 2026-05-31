const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildPreferencesFromResumeProfile,
  parseResumeText,
  validateResumeUploadInput,
} = require("../lib/resume-parser");

test("parses a Chinese resume into a candidate profile", () => {
  const profile = parseResumeText(`
    张三
    目标岗位：数据分析实习生 / 商业分析
    期望城市：上海，北京
    教育经历：复旦大学 统计学 本科 2023-2027
    实习经历：某互联网公司 数据分析实习生，负责 SQL 看板、Python 自动化和 A/B 实验分析。
    技能：Python, SQL, Tableau, 机器学习
  `);

  assert.equal(profile.headline, "数据分析实习生 / 商业分析");
  assert.deepEqual(profile.target_locations, ["上海", "北京"]);
  assert.deepEqual(profile.target_roles, ["数据分析", "商业分析"]);
  assert.deepEqual(profile.skills, ["Python", "SQL", "Tableau", "机器学习", "A/B 实验"]);
  assert.equal(profile.seniority, "实习");
  assert.equal(profile.experience_stage, "实习");
  assert.ok(profile.education.some((item) => item.includes("复旦大学")));
  assert.ok(profile.experience.some((item) => item.includes("数据分析实习生")));
  assert.match(profile.education_summary, /复旦大学/);
  assert.match(profile.experience_summary, /数据分析实习生/);
});

test("builds user preferences from a resume profile without noisy fields", () => {
  const profile = parseResumeText(`
    求职意向：产品经理校招，北京
    项目：AI 产品原型，用户研究，数据分析
    技能：SQL, Figma, Python
  `);

  assert.deepEqual(buildPreferencesFromResumeProfile(profile), {
    target_locations: ["北京"],
    target_roles: ["产品经理"],
    target_keywords: ["SQL", "Figma", "Python", "AI 产品", "用户研究", "数据分析"],
  });
});

test("validates upload inputs conservatively", () => {
  assert.deepEqual(validateResumeUploadInput({
    fileName: "resume.txt",
    fileType: "text/plain",
    fileSize: 1024,
    text: "Python SQL 数据分析",
  }), { ok: true, reason: null });

  assert.deepEqual(validateResumeUploadInput({
    fileName: "resume.pdf",
    fileType: "application/pdf",
    fileSize: 1024,
    text: "",
  }), {
    ok: false,
    reason: "unsupported_file_type",
  });

  assert.deepEqual(validateResumeUploadInput({
    fileName: "resume.txt",
    fileType: "text/plain",
    fileSize: 2 * 1024 * 1024,
    text: "x",
  }), {
    ok: false,
    reason: "file_too_large",
  });
});
