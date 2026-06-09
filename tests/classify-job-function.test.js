const test = require("node:test");
const assert = require("node:assert/strict");
const { classifyJobFunction } = require("../lib/china-keyword-expansion");

// P1-A 标签精度硬化：职能标签必须与 JD 强相关（角色锚定），研发信号压过"产品"裸词。
// 用户实锤问题：标题含"产品"二字的研发岗被误打成"产品"标签。

test("研发岗含'产品'二字不再被误判为产品（角色锚定，研发优先）", () => {
  assert.equal(classifyJobFunction({ title: "产品研发工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "产品测试工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "智能产品开发" }), "研发");
  assert.equal(classifyJobFunction({ title: "硬件产品工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "产品安全工程师" }), "研发");
});

test("产品设计师归设计（不归产品）", () => {
  assert.equal(classifyJobFunction({ title: "产品设计师" }), "设计");
});

test("真·产品角色仍准确归产品（回归）", () => {
  assert.equal(classifyJobFunction({ title: "产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "AI 产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "高级产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "数据产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "产品运营" }), "产品");
});

test("其它职能分类回归不受影响", () => {
  assert.equal(classifyJobFunction({ title: "算法工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "Product Engineer" }), "研发");
  assert.equal(classifyJobFunction({ title: "数据分析师" }), "数据");
  assert.equal(classifyJobFunction({ title: "视觉设计师" }), "设计");
  assert.equal(classifyJobFunction({ title: "" }), "其他");
});
