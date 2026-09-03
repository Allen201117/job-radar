const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const A = loadTs(path.join(__dirname, "..", "lib", "admin-user-analytics.ts"));
const T = loadTs(path.join(__dirname, "..", "lib", "track.ts"));

// ── 埋点 payload 的收敛规则 ────────────────────────────────────────────────
// 看板按页面分组统计，路径必须是有限枚举，否则动态段会把分组炸成上千行。

test("页面路径归一：已知路径原样保留，未知一律归 other（不丢弃）", () => {
  assert.equal(T.normalizePagePath("/today"), "/today");
  assert.equal(T.normalizePagePath("/jobs?city=北京"), "/jobs");
  assert.equal(T.normalizePagePath("/jobs/"), "/jobs");
  assert.equal(T.normalizePagePath("/admin/health"), "/admin/health");
  // 动态段绝不能原样进统计：它会让「哪几个页面最常被打开」变成一张几千行的噪音表
  assert.equal(T.normalizePagePath("/jobs/1a2b-3c4d-uuid"), "other");
  assert.equal(T.normalizePagePath(null), "other");
  assert.equal(T.normalizePagePath(123), "other");
});

test("搜索词归一：去空白、限长、小写，便于聚合同义大小写", () => {
  assert.equal(T.normalizeSearchKeyword("  产品经理 "), "产品经理");
  assert.equal(T.normalizeSearchKeyword("Product Manager"), "product manager");
  assert.equal(T.normalizeSearchKeyword("x".repeat(100)).length, T.SEARCH_KEYWORD_MAX);
  assert.equal(T.normalizeSearchKeyword(undefined), "");
});

test("多选筛选值拆分：去重、封顶，防止一条 payload 塞进上百个值", () => {
  assert.deepEqual(T.splitFilterValues("北京,上海 深圳"), ["北京", "上海", "深圳"]);
  assert.deepEqual(T.splitFilterValues("北京，北京,北京"), ["北京"]);
  assert.equal(T.splitFilterValues(Array.from({ length: 30 }, (_, i) => `城市${i}`).join(",")).length, 8);
  assert.deepEqual(T.splitFilterValues(""), []);
});

test("搜索结果 payload：0 结果单独存布尔，筛选项计数只数真正起筛选作用的字段", () => {
  const p = T.buildSearchResultPayload(
    { keyword: "后端", city: "北京,上海", jobFunction: "研发", jobType: "社招", sortBy: "match", showIgnored: true },
    { resultCount: 0, capped: false, latencyMs: 800 },
  );
  assert.equal(p.result_count, 0);
  // zero_result 是给 SQL 用的：统计 0 结果率时不必对 jsonb 数字做类型转换
  assert.equal(p.zero_result, true);
  assert.deepEqual(p.cities, ["北京", "上海"]);
  // 排序方式、显示开关不是筛选条件，不能计入「用了几个筛选项」
  assert.equal(p.filter_count, 4);
  assert.equal(p.latency_bucket, "500_1499ms");
});

test("搜索结果 payload：脏输入不炸，计数退化成 0 而不是 NaN", () => {
  const p = T.buildSearchResultPayload(null, { resultCount: "abc" });
  assert.equal(p.result_count, 0);
  assert.equal(p.zero_result, true);
  assert.equal(p.filter_count, 0);
  assert.equal(p.latency_bucket, "pending");
});

// ── 看板派生结论 ──────────────────────────────────────────────────────────

test("读不出数据返回 null，绝不用 0 冒充「没人用」", () => {
  assert.equal(A.normalizeUserAnalytics(null), null);
  assert.equal(A.normalizeUserAnalytics("boom"), null);
});

test("缺字段的返回值也能收敛成强类型，不抛异常", () => {
  const a = A.normalizeUserAnalytics({});
  assert.equal(a.totals.registered, 0);
  assert.deepEqual(a.funnel, []);
  assert.deepEqual(a.users, []);
  assert.equal(a.retention.d7Cohort, 0);
});

test("样本不足不给百分比 —— 5 个人算出来的「40%」没有意义", () => {
  assert.equal(A.rate(2, 5), null);
  assert.equal(A.rate(2, 5 + A.MIN_SAMPLE), 2 / 15);
  assert.equal(A.formatPct(null), "—");
  assert.equal(A.formatPct(0.136), "14%");
});

test("最大的坎取「掉的人数最多」那一级，不是留存率最低那一级", () => {
  const funnel = [
    { key: "signup", label: "注册", users: 72 },
    { key: "opened", label: "打开过产品", users: 60 },
    { key: "prefs", label: "设了求职目标", users: 44 },
    { key: "official", label: "点开官网", users: 31 },
    { key: "applied", label: "标记投递", users: 4 },
  ];
  const drop = A.biggestDrop(funnel);
  // 31→4 掉 27 人，比 60→44 的 16 人多；虽然 44→31 的留存率不是最低
  assert.equal(drop.from.label, "点开官网");
  assert.equal(drop.lost, 27);
});

test("漏斗后一级人数更多时不算流失（真实存在「跳过上一步」的用户）", () => {
  const drop = A.biggestDrop([
    { key: "a", label: "设了求职目标", users: 44 },
    { key: "b", label: "看到岗位", users: 46 },
  ]);
  assert.equal(drop, null);
});

test("结论句是结论不是数字复述，且读失败时明说不下结论", () => {
  const a = A.normalizeUserAnalytics({
    totals: { registered: 72, activated: 60 },
    active_days_hist: { one: 46 },
    funnel: [
      { key: "signup", label: "注册", users: 72 },
      { key: "prefs", label: "设了求职目标", users: 44 },
    ],
  });
  const s = A.headlineSentence(a);
  assert.match(s, /72 人注册/);
  assert.match(s, /46 人只来过一天/);
  assert.match(s, /最大的坎/);
  assert.match(A.headlineSentence(null), /读不出来/);
});

test("留存与 0 结果率的红黄绿方向相反：留存越高越好，白搜越低越好", () => {
  assert.equal(A.retentionTone(0.5), "success");
  assert.equal(A.retentionTone(0.25), "warning");
  assert.equal(A.retentionTone(0.05), "danger");
  assert.equal(A.retentionTone(null), "muted");

  assert.equal(A.zeroResultTone(0.05), "success");
  assert.equal(A.zeroResultTone(0.2), "warning");
  assert.equal(A.zeroResultTone(0.5), "danger");
  assert.equal(A.zeroResultTone(null), "muted");
});

test("新埋点还没数据时要报「积累中」，不能让看板显示 0% 冒充「没人搜」", () => {
  const fresh = A.normalizeUserAnalytics({ search: { searches: 0 }, pages: [] });
  assert.deepEqual(A.pendingBlocks(fresh), ["搜索行为", "页面浏览"]);

  const flowing = A.normalizeUserAnalytics({
    search: { searches: 120 },
    pages: [{ path: "/today", views: 30, users: 5 }],
  });
  assert.deepEqual(A.pendingBlocks(flowing), []);
});
