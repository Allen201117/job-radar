const assert = require("node:assert/strict");
const test = require("node:test");

const {
  classifyJobFunction,
  jobMatchesChinaKeyword,
  keywordMatchUnits,
} = require("../lib/china-keyword-expansion");

// ——— 组合意图：单元间 AND、单元内 OR ———

test("'AI PM' 拆成两个概念单元（AI ∧ 产品）", () => {
  const units = keywordMatchUnits("AI PM");
  assert.equal(units.length, 2, "应识别为 AI + 产品 两个单元");
});

test("'AI PM' 只召回 AI 产品经理，不召回纯算法岗或纯产品岗", () => {
  const aiPm = { title: "AI 产品经理", summary: "负责大模型产品方向" };
  const pureAlgo = { title: "推荐算法工程师", summary: "召回排序" };
  const purePm = { title: "电商产品经理", summary: "交易链路" };

  assert.equal(jobMatchesChinaKeyword(aiPm, "AI PM"), true);
  assert.equal(jobMatchesChinaKeyword(pureAlgo, "AI PM"), false, "纯算法岗不应命中");
  assert.equal(jobMatchesChinaKeyword(purePm, "AI PM"), false, "纯产品岗不应命中");
});

test("单关键词保持宽召回（向后兼容）", () => {
  const algo = { title: "机器学习工程师" };
  assert.equal(jobMatchesChinaKeyword(algo, "算法"), true);
  assert.equal(jobMatchesChinaKeyword(algo, "AI"), true);
});

test("空查询匹配一切", () => {
  assert.equal(jobMatchesChinaKeyword({ title: "任意" }, ""), true);
});

test("散词（非概念组）按 AND 处理", () => {
  const job = { title: "前端工程师", company: "字节跳动" };
  assert.equal(jobMatchesChinaKeyword(job, "前端 字节"), true);
  assert.equal(jobMatchesChinaKeyword(job, "前端 腾讯"), false, "公司不匹配应过滤");
});

// ——— 岗位职能粗分类 ———

test("职能分类覆盖主要桶", () => {
  assert.equal(classifyJobFunction({ title: "AI 产品经理" }), "产品");
  assert.equal(classifyJobFunction({ title: "推荐算法工程师" }), "研发");
  assert.equal(classifyJobFunction({ title: "前端开发" }), "研发");
  assert.equal(classifyJobFunction({ title: "视觉设计师" }), "设计");
  assert.equal(classifyJobFunction({ title: "数据分析师" }), "数据");
  assert.equal(classifyJobFunction({ title: "用户运营" }), "运营");
  assert.equal(classifyJobFunction({ title: "品牌营销经理" }), "市场");
  assert.equal(classifyJobFunction({ title: "销售经理" }), "销售");
  assert.equal(classifyJobFunction({ title: "供应链管理" }), "供应链");
  assert.equal(classifyJobFunction({ title: "HR Business Partner" }), "职能");
  assert.equal(classifyJobFunction({ title: "" }), "其他");
});

test("产品经理优先于算法字样（避免错分研发）", () => {
  assert.equal(classifyJobFunction({ title: "AI 产品经理", summary: "了解算法" }), "产品");
});
