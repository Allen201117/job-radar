const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const F = loadTs(path.join(__dirname, "..", "lib", "job-fields.ts"));

test("extractExperience normalizes Chinese ranges and minimum years", () => {
  assert.equal(F.extractExperience("需要 3-5 年产品经验"), "3-5年");
  assert.equal(F.extractExperience("5年以上工作经验"), "5年+");
});

test("extractExperience handles no-experience and English forms", () => {
  assert.equal(F.extractExperience("应届生或经验不限"), "应届/不限");
  assert.equal(F.extractExperience("3 to 5 years of experience"), "3-5年");
  assert.equal(F.extractExperience("5+ years of experience"), "5年+");
});

test("extractExperience returns unknown for empty or unrecognized input", () => {
  assert.equal(F.extractExperience(null), "未知");
  assert.equal(F.extractExperience("熟悉协作流程"), "未知");
});

test("extractEducation finds the highest explicit degree keyword", () => {
  assert.equal(F.extractEducation("博士优先"), "博士");
  assert.equal(F.extractEducation("硕士及以上学历"), "硕士");
  assert.equal(F.extractEducation("Bachelor degree required"), "本科");
});

test("extractEducation handles unrestricted and unknown education", () => {
  assert.equal(F.extractEducation("学历不限"), "不限");
  assert.equal(F.extractEducation(null), "未知");
  assert.equal(F.extractEducation("沟通能力强"), "未知");
});

test("extractDeadline normalizes Chinese deadline dates", () => {
  assert.equal(F.extractDeadline("申请截止：2026年7月31日"), "2026-7-31");
  assert.equal(F.extractDeadline("投递截止 2026/08/01"), "2026-08-01");
});

test("extractDeadline handles rolling and empty deadlines", () => {
  assert.equal(F.extractDeadline("长期招聘，招满即止"), "长期有效");
  assert.equal(F.extractDeadline("Rolling applications accepted"), "长期有效");
  assert.equal(F.extractDeadline(null), "未知");
  assert.equal(F.extractDeadline("请尽快投递"), "未知");
});

test("cleanDeadlineText 只放行近未来真实日期，占位/过期/远未来一律 null", () => {
  const now = new Date("2026-09-15T00:00:00Z");
  // 近未来真实日期 → 放行（归一 YYYY-MM-DD）
  assert.equal(F.cleanDeadlineText("2026-09-22", now), "2026-09-22");
  assert.equal(F.cleanDeadlineText("2027-08-31 23:59:59", now), "2027-08-31"); // 容忍时间后缀
  // 占位 / 垃圾 → null
  assert.equal(F.cleanDeadlineText("长期有效", now), null);
  assert.equal(F.cleanDeadlineText("3000-01-01", now), null); // 远未来占位
  assert.equal(F.cleanDeadlineText("2079-11-30", now), null);
  assert.equal(F.cleanDeadlineText("2030-12-31", now), null); // 超 550 天
  // 已过期 → null（留一天缓冲）
  assert.equal(F.cleanDeadlineText("2026-08-01", now), null);
  // 空 / 非日期 → null
  assert.equal(F.cleanDeadlineText("", now), null);
  assert.equal(F.cleanDeadlineText(null, now), null);
  assert.equal(F.cleanDeadlineText("未知", now), null);
});
