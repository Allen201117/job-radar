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
