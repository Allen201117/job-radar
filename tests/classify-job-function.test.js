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

// 领域降级门：机械/工艺/化工等「非软件工程」岗仅靠泛词（开发/技术/工程师）落入研发，
// 应归「其他」而非软件「研发」桶——否则被「算法/AI/数据」类查询经相关层误召。
// 用户实锤：「工艺技术开发（机械/自动化）」被打成研发 + 误命中「AI 数据产品经理」。
test("非软件工程岗（机械/工艺/化工…）不再误判为软件研发", () => {
  assert.equal(classifyJobFunction({ title: "工艺技术开发（机械/自动化）" }), "其他");
  assert.equal(classifyJobFunction({ title: "机械工程师" }), "其他");
  assert.equal(classifyJobFunction({ title: "化工工艺开发" }), "其他");
  assert.equal(classifyJobFunction({ title: "材料研发工程师" }), "其他");
  assert.equal(classifyJobFunction({ title: "焊接技术工程师" }), "其他");
});

test("带软件信号的交叉岗仍判研发（保守降级，不误伤机器人/嵌入式等）", () => {
  // 机械臂/自动驾驶/嵌入式等：有工业标记但带软件/算法信号 → 仍是软件研发。
  assert.equal(classifyJobFunction({ title: "机械臂算法工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "工业自动化测试开发" }), "研发");
  assert.equal(classifyJobFunction({ title: "汽车嵌入式软件工程师" }), "研发");
});

// 标题权威优先：job_type / summary 不得把标题已说清的职能带偏。
// 用户实锤：B站「数据科学家」挂在部门 job_type=「产品运营类」下，旧实现拼全文 → 误判「产品」→
// 匹配上「AI 数据产品经理」推给产品经理用户。标题「数据科学家」应判「数据」。
test("标题优先：job_type/summary 不带偏标题已明确的职能", () => {
  assert.equal(
    classifyJobFunction({ title: "商业化-数据科学家（AI Agent 开发方向）", job_type: "产品运营类" }),
    "数据",
    "数据科学家挂在产品运营部门下，仍应判数据（不被 job_type 带偏成产品）",
  );
  assert.equal(
    classifyJobFunction({ title: "算法工程师", job_type: "产品技术", summary: "与产品经理协作" }),
    "研发",
    "算法工程师标题清晰，不被 job_type/summary 的产品字样带偏",
  );
  // 「职能」例外：招聘活动标签标题（命中「招聘」）退回看正文真实角色 → 产品经理仍可召回。
  assert.equal(
    classifyJobFunction({ title: "2024 届校园招聘", summary: "产品经理方向，负责需求管理" }),
    "产品",
    "招聘标签标题退回正文，summary 的产品经理仍可召回",
  );
  // 真 HR 岗：标题就是招聘角色，正文不翻盘 → 仍判职能（不被例外误伤）。
  assert.equal(classifyJobFunction({ title: "招聘专员", summary: "负责候选人寻访" }), "职能");
});
