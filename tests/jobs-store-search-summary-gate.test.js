// /jobs 候选取数「正文按需传 + 排除词下推」契约（2026-09-17，lib/jobs-store/search.ts）。
// 默认态冷路径 14~35s 的主因是 2.8 万行正文全传；职能门必拒的行根本不读正文。等价性前提见 candidateSummaryExpr 注释。
const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const S = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "search.ts"));

const baseFilters = {
  company: "", city: "", jobType: "", keyword: "", showIgnored: false, showApplied: false, showNewOnly: false,
  sortBy: "newest", capitalOrigin: "", region: "", salaryOnly: false, sponsorshipOnly: false, education: "",
  jobFunction: "", jobRole: "", experience: "", postedWithin: "", companyTier: "",
};
const prefs = (over = {}) => ({ target_roles: ["产品经理"], target_keywords: [], exclude_keywords: [], target_locations: [], ...over });

test("有目标职能且无读正文的精筛条件 → 只给同职能/其他/未分类的行传正文", () => {
  const params = [];
  const expr = S.candidateSummaryExpr(params, baseFilters, prefs());
  assert.match(expr, /case when job_function is null or job_function = '其他' or job_function = any\(\$1::text\[\]\) then summary else null end/);
  assert.deepEqual(params, [["产品"]]);
});

test("目标职能判不出 → 全传（scoreJob 没有职能门可省）；匿名且无读正文精筛 → 一行都不传", () => {
  assert.equal(S.candidateSummaryExpr([], baseFilters, prefs({ target_roles: ["AI Agent"] })), "summary");
  assert.equal(S.candidateSummaryExpr([], baseFilters, null), "null::text");
  assert.equal(S.candidateSummaryExpr([], { ...baseFilters, keyword: "产品" }, null), "summary");
});

test("命中页回补列必须含 summary（候选阶段不传正文的行，卡片摘要靠这里补）", () => {
  const fs = require("node:fs");
  const src = fs.readFileSync(path.join(__dirname, "..", "lib", "jobs-store", "search.ts"), "utf8");
  const m = src.match(/const HYDRATE_COLUMNS =\s*\n?\s*"([^"]+)"/);
  assert.ok(m && m[1].split(",").map((x) => x.trim()).includes("summary"), "HYDRATE_COLUMNS 缺 summary");
});

test("keyword / jobRole / experience 任一生效 → 全传（这三个 JS 精筛读正文）", () => {
  for (const patch of [{ keyword: "产品" }, { jobRole: "前端" }, { experience: "0-3" }]) {
    const params = [];
    assert.equal(S.candidateSummaryExpr(params, { ...baseFilters, ...patch }, prefs()), "summary");
    assert.equal(params.length, 0);
  }
});

test("排除词下推 SQL：与 scoreJob 同字段集（title + summary）、小写子串、转义 like 通配", () => {
  const conds = [];
  const params = [];
  S.appendExcludeWhere(conds, params, prefs({ exclude_keywords: ["外包", " Java ", "100%_", ""] }));
  assert.equal(conds.length, 1);
  assert.match(conds[0], /not \(lower\(coalesce\(title, ''\) \|\| ' ' \|\| coalesce\(summary, ''\)\) like any\(\$1::text\[\]\)\)/);
  assert.deepEqual(params, [["%外包%", "%java%", "%100\\%\\_%"]]);
});

test("没有排除词 → 不加条件、不发空数组", () => {
  const conds = [];
  const params = [];
  S.appendExcludeWhere(conds, params, prefs());
  S.appendExcludeWhere(conds, params, null);
  assert.deepEqual(conds, []);
  assert.deepEqual(params, []);
});

test("登录 + 按匹配度排：候选一律不传正文（正文只给命中页回补）", () => {
  const params = [];
  const expr = S.candidateSummaryExpr(params, { ...baseFilters, sortBy: "match" }, prefs({ target_roles: ["后端工程师"] }));
  assert.equal(expr, "null::text");
  assert.equal(params.length, 0);
});
