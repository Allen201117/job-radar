const test = require("node:test");
const assert = require("node:assert/strict");
const {
  ISSUE_TYPES, splitRoleTokens, findMixedSeparatorRoles,
  buildUserIssues, buildLatencyIssues, computeIssuesByType,
} = require("../scripts/ux-walkthrough/walkthrough.js");

// ux-walkthrough 的 issue 结构化（2026-09-18）：type 是有限枚举，issues_by_type 恒含全部键，
// 同一用户同一根因不重复计。本测试只覆盖纯函数，不连库、不发网络请求。

test("splitRoleTokens：单个岗位名不切分", () => {
  assert.deepEqual(splitRoleTokens("产品经理"), ["产品经理"]);
  assert.deepEqual(splitRoleTokens("AI产品经理"), ["AI产品经理"]);
});

test("splitRoleTokens：中文分号 / 空格分隔的多岗位写法", () => {
  assert.deepEqual(splitRoleTokens("销售；采购"), ["销售", "采购"]);
  assert.deepEqual(splitRoleTokens("销售 管培 运营"), ["销售", "管培", "运营"]);
});

test("splitRoleTokens：边界输入（空/null/undefined）不炸", () => {
  assert.deepEqual(splitRoleTokens(""), []);
  assert.deepEqual(splitRoleTokens(null), []);
  assert.deepEqual(splitRoleTokens(undefined), []);
  assert.deepEqual(splitRoleTokens("   "), []);
});

test("findMixedSeparatorRoles：归纳出所有含分隔符写法的 role，且不误伤正常写法", () => {
  const roles = ["产品经理", "销售；采购", "数据分析师", "销售 管培 运营"];
  assert.deepEqual(findMixedSeparatorRoles(roles), ["销售；采购", "销售 管培 运营"]);
  assert.deepEqual(findMixedSeparatorRoles([]), []);
  assert.deepEqual(findMixedSeparatorRoles(undefined), []);
  assert.deepEqual(findMixedSeparatorRoles(["产品经理", "运营"]), []);
});

test("ISSUE_TYPES：每个枚举都带人话 label", () => {
  for (const [type, meta] of Object.entries(ISSUE_TYPES)) {
    assert.ok(typeof meta.label === "string" && meta.label.length > 0, `${type} 缺人话 label`);
  }
});

test("computeIssuesByType：恒含全部枚举键，未命中的写 0（不是缺键）", () => {
  const byType = computeIssuesByType([]);
  assert.deepEqual(Object.keys(byType).sort(), Object.keys(ISSUE_TYPES).sort());
  for (const v of Object.values(byType)) assert.equal(v, 0);
});

test("computeIssuesByType：按 type 计数，未知 type 也不炸（兜底记 0 起步再加 1）", () => {
  const byType = computeIssuesByType([{ type: "zero_shown" }, { type: "zero_shown" }, { type: "direction_low" }]);
  assert.equal(byType.zero_shown, 2);
  assert.equal(byType.direction_low, 1);
  assert.equal(byType.insight_uncovered, 0);
});

test("buildUserIssues：推荐页 0 岗且非求职范围错配 → zero_shown", () => {
  const r = { user: "u1", shown: 0, scopeMismatch: false, recalled: 0, filtered: {}, roles: ["产品经理"], directionOk: null, insightCompanies: 0, insightCovered: 0, campus: null };
  const issues = buildUserIssues(r);
  assert.equal(issues.length, 1);
  assert.equal(issues[0].type, "zero_shown");
});

test("buildUserIssues：0 岗 + 求职范围错配 → 只算 scope_mismatch，不重复算 zero_shown", () => {
  const r = { user: "u1", shown: 0, scopeMismatch: true, jobScope: "overseas", recalled: 5, filtered: {}, roles: ["产品经理"], directionOk: null, insightCompanies: 0, insightCovered: 0, campus: null };
  const issues = buildUserIssues(r);
  assert.deepEqual(issues.map((i) => i.type), ["scope_mismatch"]);
});

test("buildUserIssues：方向命中低于阈值 → direction_low；命中良好则不报", () => {
  const base = { user: "u1", shown: 10, scopeMismatch: false, recalled: 10, filtered: {}, roles: ["产品经理"], insightCompanies: 0, insightCovered: 0, campus: null };
  const bad = buildUserIssues({ ...base, directionOk: 0.5 });
  assert.ok(bad.some((i) => i.type === "direction_low"));
  const good = buildUserIssues({ ...base, directionOk: 0.9 });
  assert.ok(!good.some((i) => i.type === "direction_low"));
  // 判不出方向（null）不应误报
  const unjudged = buildUserIssues({ ...base, directionOk: null });
  assert.ok(!unjudged.some((i) => i.type === "direction_low"));
});

test("buildUserIssues：role_input_format——同一用户填了多个混写岗位名只算一条，不是每个 role 一条", () => {
  const r = {
    user: "u1", shown: 10, scopeMismatch: false, recalled: 10, filtered: {},
    roles: ["销售；采购", "销售 管培 运营"], directionOk: 0.9,
    insightCompanies: 0, insightCovered: 0, campus: null,
  };
  const issues = buildUserIssues(r);
  const roleFormatIssues = issues.filter((i) => i.type === "role_input_format");
  assert.equal(roleFormatIssues.length, 1, "同一用户同一根因应只计一次");
  assert.equal(roleFormatIssues[0].mixedRoles.length, 2);
});

test("buildUserIssues：role_mismatch 拦截占比过高才报，占比低不报", () => {
  const base = { user: "u1", shown: 3, scopeMismatch: false, roles: ["产品经理"], directionOk: 0.9, insightCompanies: 0, insightCovered: 0, campus: null };
  const high = buildUserIssues({ ...base, recalled: 10, filtered: { role_mismatch: 8 } });
  assert.ok(high.some((i) => i.type === "role_mismatch_high"));
  const low = buildUserIssues({ ...base, recalled: 10, filtered: { role_mismatch: 1 } });
  assert.ok(!low.some((i) => i.type === "role_mismatch_high"));
  // recalled=0 时不能除零报错
  const zero = buildUserIssues({ ...base, recalled: 0, filtered: {} });
  assert.ok(!zero.some((i) => i.type === "role_mismatch_high"));
});

test("buildUserIssues：洞察零覆盖——只在有公司候选时才报，避免 0/0 误判", () => {
  const base = { user: "u1", shown: 5, scopeMismatch: false, recalled: 5, filtered: {}, roles: ["产品经理"], directionOk: 0.9, campus: null };
  const zeroCoverage = buildUserIssues({ ...base, insightCompanies: 3, insightCovered: 0 });
  assert.ok(zeroCoverage.some((i) => i.type === "insight_uncovered"));
  const noCompanies = buildUserIssues({ ...base, insightCompanies: 0, insightCovered: 0 });
  assert.ok(!noCompanies.some((i) => i.type === "insight_uncovered"));
});

test("buildUserIssues：校招用户必投渠道全不通 → campus_channel_broken；非校招用户不报", () => {
  const base = { user: "u1", shown: 5, scopeMismatch: false, recalled: 5, filtered: {}, roles: ["产品经理"], directionOk: 0.9, insightCompanies: 0, insightCovered: 0 };
  const broken = buildUserIssues({ ...base, campus: { industries: ["互联网"], listed: 10, healthy: 0 } });
  assert.ok(broken.some((i) => i.type === "campus_channel_broken"));
  const healthy = buildUserIssues({ ...base, campus: { industries: ["互联网"], listed: 10, healthy: 3 } });
  assert.ok(!healthy.some((i) => i.type === "campus_channel_broken"));
  const notCampus = buildUserIssues({ ...base, campus: null });
  assert.ok(!notCampus.some((i) => i.type === "campus_channel_broken"));
});

test("buildLatencyIssues：http 非 200 或超时都算失败/慢，200 且快不报", () => {
  const issues = buildLatencyIssues({
    a: { seconds: 1, http: 200 },
    b: { seconds: 12, http: 200 },
    c: { seconds: null, http: null },
    d: { seconds: 3, http: 500 },
  });
  const types = issues.map((i) => `${i.user}:${i.type}`);
  assert.deepEqual(types, ["b:api_latency", "c:api_latency", "d:api_latency"]);
});

test("buildLatencyIssues：空输入不炸", () => {
  assert.deepEqual(buildLatencyIssues({}), []);
  assert.deepEqual(buildLatencyIssues(undefined), []);
});
