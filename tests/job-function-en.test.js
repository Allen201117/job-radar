const test = require("node:test");
const assert = require("node:assert/strict");

const { classifyJobFunction } = require("../lib/china-keyword-expansion");

test("job function recognizes English edge titles", () => {
  assert.equal(classifyJobFunction({ title: "Staff Software Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "Site Reliability Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "SRE" }), "研发");
  // 这是有意翻转的旧口径：TPM = Technical Program Manager = 技术项目经理，不是产品经理。
  // 旧规则归「产品」会把大量 TPM 岗推给产品经理用户；生产库实测 Principal Technical Program Manager、
  // Staff IT Technical Program Manager 等全落在「产品」桶，2026-09-02 明确改归「项目管理」。
  assert.equal(classifyJobFunction({ title: "Technical Program Manager" }), "项目管理");
  assert.equal(classifyJobFunction({ title: "TPM" }), "项目管理");
});
