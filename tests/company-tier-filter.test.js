// companyTier 筛选：jobFilterMatch 侧的多选(并集)判定，与 lib/company-tiers.classifyCompanyTier 同口径。
const { test } = require("node:test");
const assert = require("node:assert");
const { loadTs } = require("./_load-ts");
const { jobFilterMatch, DEFAULT_FILTERS } = loadTs(require("path").resolve(__dirname, "../lib/job-filter.ts"));

const mk = (company) => ({
  id: "1",
  company,
  title: "工程师",
  summary: "x".repeat(80),
  jd_url: "https://e.com/1",
  location: "北京",
  recruitment_category: "社招",
});

test("companyTier=大厂 只放行大厂", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "大厂" };
  assert.ok(jobFilterMatch(mk("字节跳动"), f) !== null);
  assert.ok(jobFilterMatch(mk("某小公司"), f) === null);
});

test("companyTier=中小厂 只放行兜底", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "中小厂" };
  assert.ok(jobFilterMatch(mk("某小公司"), f) !== null);
  assert.ok(jobFilterMatch(mk("字节跳动"), f) === null);
});

test("companyTier 多选=并集", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "大厂,外企" };
  assert.ok(jobFilterMatch(mk("字节跳动"), f) !== null);
  assert.ok(jobFilterMatch(mk("Apple"), f) !== null);
  assert.ok(jobFilterMatch(mk("某小公司"), f) === null);
});

test("companyTier 为空不筛选", () => {
  const f = { ...DEFAULT_FILTERS };
  assert.ok(jobFilterMatch(mk("字节跳动"), f) !== null);
  assert.ok(jobFilterMatch(mk("某小公司"), f) !== null);
});
