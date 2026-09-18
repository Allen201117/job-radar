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

test("splitRoleTokens：边界输入（空/null/undefined）不炸", () => {
  assert.deepEqual(splitRoleTokens(""), []);
  assert.deepEqual(splitRoleTokens(null), []);
  assert.deepEqual(splitRoleTokens(undefined), []);
  assert.deepEqual(splitRoleTokens("   "), []);
});

// 2026-09-18 返工：全量真实 target_roles 对拍出的规律——
// 真问题（应切分为多岗位）全是「汉字—分隔符—汉字」；误报（不应切分）全是英文/缩写紧邻分隔符。
// 三组样本原样保留（不许为了让规则过而改样本），两个方向都必须是 0 错。
const REAL_MULTI_ROLE_SAMPLES = [
  "行政/后勤类", "教育/培训类", "文体/影视/写作/媒体类", "项目专员/助理", "行政专员/助理",
  "数字 IC 验证/设计工程师", "质量工程师 工艺工程师",
  "销售；采购", "销售 管培 运营", // 已知线上样本
];
const FALSE_POSITIVE_SINGLE_ROLE_SAMPLES = [
  "AI 数据产品经理", "AI Agent", "AIGC 内容实习生", "TikTok Shop 运营", "AI 产品经理",
  "Office/WPS", "Spring Boot", "Spring Security", "Element Plus", "RESTful API",
  "AB 实验分析", "Prompt Engineering", "Agent Workflow", "Skill 调度设计", "iDA OpenAPI",
  "Kano 优先级", "Figma 原型", "Agent 架构", "Agent Loop", "Skill 调度与自迭代",
  "business development",
];
const UNSURE_DO_NOT_FLAG_SAMPLES = ["MVP 定义", "Spec 全栈", "UI/UX设计师"];

test("splitRoleTokens：真问题组——「汉字-分隔符-汉字」必须切出 ≥2 段（0 条漏标）", () => {
  let missed = 0;
  for (const role of REAL_MULTI_ROLE_SAMPLES) {
    if (splitRoleTokens(role).length < 2) { missed += 1; console.error("漏标:", role); }
  }
  assert.equal(missed, 0, "真问题组应全部被切分，漏标数必须为 0");
});

test("splitRoleTokens：误报组——英文/缩写紧邻分隔符不许被切（0 条误报）", () => {
  let falsePositives = 0;
  for (const role of FALSE_POSITIVE_SINGLE_ROLE_SAMPLES) {
    if (splitRoleTokens(role).length > 1) { falsePositives += 1; console.error("误报:", role); }
  }
  assert.equal(falsePositives, 0, "误报组应全部保持单 token，误报数必须为 0");
});

test("splitRoleTokens：拿不准组——宁可漏判不可误报，不许被切", () => {
  let falsePositives = 0;
  for (const role of UNSURE_DO_NOT_FLAG_SAMPLES) {
    if (splitRoleTokens(role).length > 1) { falsePositives += 1; console.error("误报:", role); }
  }
  assert.equal(falsePositives, 0, "拿不准组应保持单 token（宁可漏判），误报数必须为 0");
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

test("buildLatencyIssues：http 非 200 或超时都算失败/慢，200 且快不报；归因字段是 metric 不是 user", () => {
  const issues = buildLatencyIssues({
    a: { seconds: 1, http: 200 },
    b: { seconds: 12, http: 200 },
    c: { seconds: null, http: null },
    d: { seconds: 3, http: 500 },
  });
  const metrics = issues.map((i) => `${i.metric}:${i.type}`);
  assert.deepEqual(metrics, ["b:api_latency", "c:api_latency", "d:api_latency"]);
  // user 字段是接口名的坑已修：延迟类 issue 不归因到用户，user 必须是 null，text 不拼 "null：" 前缀
  for (const i of issues) {
    assert.equal(i.user, null);
    assert.ok(!i.text.startsWith("null"), `text 不应带 null 前缀: ${i.text}`);
  }
});

test("buildLatencyIssues：空输入不炸", () => {
  assert.deepEqual(buildLatencyIssues({}), []);
  assert.deepEqual(buildLatencyIssues(undefined), []);
});

test("buildUserIssues：zero_shown 与 role_input_format 是两个不同根因，必须共存不互斥", () => {
  const r = {
    user: "u1", shown: 0, scopeMismatch: false, recalled: 0, filtered: {},
    roles: ["销售；采购"], directionOk: null, insightCompanies: 0, insightCovered: 0, campus: null,
  };
  const issues = buildUserIssues(r);
  const types = issues.map((i) => i.type);
  assert.ok(types.includes("zero_shown"), "0 岗本身是真实卡点，不该被 role_input_format 顶掉");
  assert.ok(types.includes("role_input_format"), "岗位写法问题不该被 zero_shown 顶掉");
});
