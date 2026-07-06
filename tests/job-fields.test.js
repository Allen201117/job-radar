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
