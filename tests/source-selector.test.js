const test = require("node:test");
const assert = require("node:assert/strict");
const { selectRelevantSources } = require("../lib/live-search");

// P2-A 源选择器：按用户筛选项从 sources 表挑最相关的若干源去定向刷新；
// 标出哪些能内联秒回(httpx)、哪些是浏览器源(走异步)。决定 on-demand "定向刷新已知源"。

const SOURCES = [
  { company: "百度", adapter_name: "baidu", industry: "互联网", enabled: true },
  { company: "京东", adapter_name: "jd", industry: "电商", enabled: true },
  { company: "Anthropic", adapter_name: "greenhouse", industry: "AI", enabled: true },
  { company: "蔚来", adapter_name: "nio_feishu", industry: "汽车", enabled: true }, // 浏览器源
  { company: "某北森客户", adapter_name: "beisen", industry: "制造", enabled: true }, // 浏览器源
  { company: "停用源", adapter_name: "baidu", industry: "x", enabled: false },
];

test("公司精确筛选 → 只返回命中该公司的源", () => {
  const r = selectRelevantSources(SOURCES, { company: "京东" });
  assert.equal(r.length, 1);
  assert.equal(r[0].source.company, "京东");
});

test("关键词命中行业 → 该源入选", () => {
  const r = selectRelevantSources(SOURCES, { keyword: "电商" });
  assert.ok(r.some((x) => x.source.company === "京东"));
});

test("live 标记：httpx 适配器 true，浏览器适配器 false", () => {
  const r = selectRelevantSources(SOURCES, {});
  assert.equal(r.find((x) => x.source.adapter_name === "baidu").live, true);
  assert.equal(r.find((x) => x.source.adapter_name === "nio_feishu").live, false);
});

test("停用源被排除", () => {
  const r = selectRelevantSources(SOURCES, {});
  assert.ok(!r.some((x) => x.source.enabled === false));
});

test("cap 限制返回数量", () => {
  const r = selectRelevantSources(SOURCES, {}, { cap: 2 });
  assert.equal(r.length, 2);
});
