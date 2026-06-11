const test = require("node:test");
const assert = require("node:assert/strict");
const { keywordMatchTier } = require("../lib/china-keyword-expansion");

// P1-B 两层关键词匹配：tier-1 精确（标题/摘要含概念组词）+ tier-2 相关（同职能、未被兄弟细分组认领）。
// 解决 88% 空摘要导致的召回崩：标题泛而无摘要的研发岗（"高级软件工程师"）也能进"后端"的相关层。

test("精确层：标题/摘要直接命中概念组 → exact", () => {
  assert.equal(keywordMatchTier({ title: "后端开发工程师" }, "后端"), "exact");
  assert.equal(keywordMatchTier({ title: "Java 服务端研发" }, "后端"), "exact");
  assert.equal(
    keywordMatchTier({ title: "算法工程师", summary: "build ranking models" }, "算法"),
    "exact",
  );
});

test("相关层：同职能、标题无字面命中、未被兄弟组认领 → related", () => {
  // 研发职能、标题没"后端"字样、也不是前端/算法/测试等明确细分 → 算"后端"的相关岗
  assert.equal(keywordMatchTier({ title: "高级软件工程师" }, "后端"), "related");
  assert.equal(keywordMatchTier({ title: "技术专家" }, "后端"), "related");
});

test("兄弟组排除：明确是前端的岗不进'后端'的相关层 → null", () => {
  assert.equal(keywordMatchTier({ title: "前端开发工程师" }, "后端"), null);
  assert.equal(keywordMatchTier({ title: "算法工程师" }, "前端"), null);
});

test("不同职能 → null", () => {
  assert.equal(keywordMatchTier({ title: "产品经理" }, "后端"), null);
  assert.equal(keywordMatchTier({ title: "财务专员" }, "算法"), null);
});

test("无职能映射的查询（实习/投研）→ 只可能精确，相关层不滥召", () => {
  // "实习"是招聘类型不是职能 → 标题无"实习"字样的软件岗不该被算相关
  assert.equal(keywordMatchTier({ title: "软件工程师" }, "实习"), null);
});

test("空关键词 → exact（不做关键词过滤，全放行）", () => {
  assert.equal(keywordMatchTier({ title: "任意岗位" }, ""), "exact");
});

// ——— 双向跨职能精度 + 正文召回（治"pm↔算法"互串）———
// 根因：JD 正文常顺带提到别职能的词（算法岗写"产品"、产品岗写"算法"）→ 拿词撞正文造成误召。
// 修法：正文命中过「职能门」——岗位职能须与查询职能相容；function=null 的泛组（工程师/软件）只匹配标题。

test("跨职能精度：pm 不再误召正文含'产品'的算法/数据岗（用户原始痛点）", () => {
  const algo = { title: "推荐算法工程师", summary: "负责推荐产品的算法模型，机器学习" };
  const data = { title: "数据分析师", summary: "SQL 业务分析，支撑产品决策" };
  assert.equal(keywordMatchTier(algo, "pm"), null, "正文有'产品'的算法岗不应命中 pm");
  assert.equal(keywordMatchTier(data, "pm"), null, "正文有'产品'的数据岗不应命中 pm");
});

test("跨职能精度（反向）：算法 不再误召正文提'算法'的产品/设计岗", () => {
  const pm = { title: "产品经理", summary: "了解算法优先，负责需求管理" };
  const design = { title: "视觉设计师", summary: "了解算法者优先" };
  assert.equal(keywordMatchTier(pm, "算法"), null, "PM 岗正文提'算法'不应命中'算法'");
  assert.equal(keywordMatchTier(design, "算法"), null);
});

test("正文召回：同职能、正文具体词点明角色 → 仍 exact（标题没体现也召回）", () => {
  // 用户明确要求：很多岗位关键词不在标题里，正文表达也要召回。
  const campusPm = { title: "2024 届校园招聘", summary: "产品经理方向，负责需求管理" };
  const seniorAlgo = { title: "资深工程师", summary: "负责推荐算法与模型训练" };
  assert.equal(keywordMatchTier(campusPm, "pm"), "exact", "正文含'产品经理'且同职能应命中");
  assert.equal(keywordMatchTier(seniorAlgo, "算法"), "exact", "正文含'算法'且同职能应命中");
});

test("真岗位仍精确命中（标题命中）", () => {
  assert.equal(keywordMatchTier({ title: "策略产品经理" }, "pm"), "exact");
  assert.equal(keywordMatchTier({ title: "Senior Product Manager" }, "pm"), "exact");
});

test("function=null 泛组（工程师/软件）只匹配标题，不撞正文", () => {
  // 标题无"工程师/engineer"、仅正文顺带提到 → 不应命中（否则"与 engineer 协作"全中）。
  assert.equal(
    keywordMatchTier({ title: "项目协调员", summary: "与 engineer 团队协作" }, "工程师"),
    null,
  );
  // 标题命中（含跨语言英文标题）→ exact，召回不丢。
  assert.equal(keywordMatchTier({ title: "Backend Engineer" }, "工程师"), "exact");
});
