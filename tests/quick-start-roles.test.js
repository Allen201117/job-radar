const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const fs = require("node:fs");
const { loadTs } = require("./_load-ts");

const {
  QUICK_START_ROLES,
  QUICK_START_MAX_ROLES,
  isQuickStartRole,
  quickStartRolesByBucket,
} = loadTs(path.join(__dirname, "..", "lib", "quick-start-roles.ts"));
const { keywordMatchTier, JOB_FUNCTION_BUCKETS } = require("../lib/china-keyword-expansion.js");

// 「一键设目标」把用户选的词直接写进 user_preferences.target_roles，之后整个看板都按它筛。
// 所以这里钉死的核心不变量只有一条，但它是全部：
// **每个可选词都必须真的能匹配上岗位**——否则用户点完得到的是一个更空的看板，比不设目标还糟。

test("每个可选方向词都能命中「词本身」这种最基本的岗位标题", () => {
  assert.ok(QUICK_START_ROLES.length >= 20, `方向词太少：${QUICK_START_ROLES.length}`);
  const dead = [];
  for (const role of QUICK_START_ROLES) {
    const tier = keywordMatchTier(
      { title: `${role.value}工程师`, summary: "", company: "", job_type: "" },
      role.value,
    );
    if (!tier) dead.push(role.value);
  }
  assert.deepStrictEqual(dead, [], `这些词匹配不上任何岗位，不能让用户选：${dead.join(", ")}`);
});

test("不许把职能桶名当方向词——桶名匹配不上真实岗位标题", () => {
  // 这条是本模块存在的理由：2026-09-06 差点直接用 JOB_FUNCTION_BUCKETS 做「一键设目标」的选项。
  assert.strictEqual(
    keywordMatchTier({ title: "后台开发", summary: "", company: "", job_type: "" }, "研发"),
    null,
    "如果「研发」哪天能匹配上「后台开发」了，这条断言可以放宽——但要先确认，别直接删",
  );
  assert.ok(
    keywordMatchTier({ title: "后台开发", summary: "", company: "", job_type: "" }, "后端"),
    "「后端」必须能匹配「后台开发」，否则方向词的选法要重来",
  );
  const values = new Set(QUICK_START_ROLES.map((r) => r.value));
  const leaked = JOB_FUNCTION_BUCKETS.filter((b) => values.has(b) && b !== "设计" && b !== "运营" && b !== "市场" && b !== "销售" && b !== "供应链" && b !== "财务");
  assert.deepStrictEqual(leaked, [], `这些桶名混进了方向词：${leaked.join(", ")}`);
});

test("白名单只认清单里的词，挡掉任意文本", () => {
  for (const role of QUICK_START_ROLES) assert.ok(isQuickStartRole(role.value), role.value);
  for (const bad of ["", "  ", "研发工程师随便写", "drop table", null, undefined, 42, {}]) {
    assert.strictEqual(isQuickStartRole(bad), false, `不该放行：${JSON.stringify(bad)}`);
  }
});

test("按职能桶分组：桶顺序与筛选器一致，且不出现空桶", () => {
  const groups = quickStartRolesByBucket();
  assert.ok(groups.length > 0);
  for (const g of groups) assert.ok(g.roles.length > 0, `${g.bucket} 是空桶`);
  const order = groups.map((g) => g.bucket);
  const expected = JOB_FUNCTION_BUCKETS.filter((b) => order.includes(b));
  assert.deepStrictEqual(order, expected, "分组顺序必须沿用 JOB_FUNCTION_BUCKETS");
  // 分组是对全集的重排，不能丢词也不能多词
  const flat = groups.flatMap((g) => g.roles.map((r) => r.value)).sort();
  assert.deepStrictEqual(flat, QUICK_START_ROLES.map((r) => r.value).sort());
});

test("值与显示名分离：写库的一律是词库规范词", () => {
  const ios = QUICK_START_ROLES.find((r) => r.value === "ios");
  if (ios) assert.strictEqual(ios.label, "iOS", "ios 应显示成 iOS，但写库仍是 ios");
  for (const role of QUICK_START_ROLES) {
    assert.strictEqual(role.value, role.value.trim());
    assert.ok(role.label.length > 0);
  }
});

test("选择上限是个正数且被 UI 与 API 共用", () => {
  assert.ok(Number.isInteger(QUICK_START_MAX_ROLES) && QUICK_START_MAX_ROLES > 0);
  const api = fs.readFileSync(
    path.join(__dirname, "..", "app", "api", "preferences", "quick-start", "route.ts"),
    "utf8",
  );
  assert.ok(api.includes("QUICK_START_MAX_ROLES"), "API 必须用同一个上限，别各写一份");
  assert.ok(api.includes("isQuickStartRole"), "API 必须走白名单校验，不能直接落库");
  assert.ok(
    api.includes("MUST_APPLY_INDUSTRIES.includes"),
    "industry 也必须白名单校验（与必投清单同口径）",
  );
});

test("快捷通道只并集追加，绝不整份替换偏好", () => {
  const api = fs.readFileSync(
    path.join(__dirname, "..", "app", "api", "preferences", "quick-start", "route.ts"),
    "utf8",
  );
  // 用 parsePreferencesInput 会把没传的字段归一成空数组 → 抹掉简历解析出来的城市/技能。
  // 只看 import 语句，别扫全文：注释里正是在解释「为什么不用它」，扫全文会自己咬自己。
  const imports = api.split("\n").filter((l) => /^\s*import\b/.test(l)).join("\n");
  assert.ok(!imports.includes("parsePreferencesInput"), "不得复用整份替换的 PUT 解析器");
  assert.ok(api.includes("mergeUnique"), "必须并集追加");
});
