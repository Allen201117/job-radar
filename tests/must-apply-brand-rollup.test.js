const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const ROOT = path.join(__dirname, "..");

function loadTsWithMocks(absPath, mocks = {}, cache = new Map()) {
  if (cache.has(absPath)) return cache.get(absPath).exports;
  const compiled = ts.transpileModule(fs.readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
      resolveJsonModule: true,
    },
  }).outputText;
  const mod = { exports: {} };
  cache.set(absPath, mod);
  const dir = path.dirname(absPath);
  const baseRequire = Module.createRequire(absPath);
  const customRequire = (spec) => {
    if (spec === "server-only") return {};
    if (Object.prototype.hasOwnProperty.call(mocks, spec)) return mocks[spec];
    let base = null;
    if (spec.startsWith("@/")) base = path.join(ROOT, spec.slice(2));
    else if (spec.startsWith(".")) base = path.resolve(dir, spec);
    if (base) {
      const tsPath = base.endsWith(".ts") ? base : `${base}.ts`;
      if (fs.existsSync(tsPath)) return loadTsWithMocks(tsPath, mocks, cache);
      const jsPath = base.endsWith(".js") ? base : `${base}.js`;
      if (fs.existsSync(jsPath)) return baseRequire(jsPath);
      return baseRequire(base);
    }
    return baseRequire(spec);
  };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports, customRequire, mod, absPath, dir,
  );
  return mod.exports;
}

function loadReader(query = async () => []) {
  return loadTsWithMocks(path.join(ROOT, "lib", "jobs-store", "read.ts"), {
    "./client": { jobsQuery: query, jobsScalar: async () => 0 },
    "./types": { JOB_COLUMNS: "*" },
    "@/lib/job-scope": { appendJobScopeWhere() {} },
    "@/lib/campus-zone": { campusAdmission: () => null },
  });
}

test("parent portal title rollup needs 3 healthy jobs and never uses summary matching", async () => {
  const calls = [];
  const R = loadReader(async (sql, params) => {
    calls.push({ sql, params });
    return [];
  });
  const list = [
    { name: "达标品牌", pattern: "%达标%", parentPattern: "%父公司%", brandTokens: ["品牌"] },
    { name: "不足品牌", pattern: "%不足%", parentPattern: "%父公司%", brandTokens: ["不足"] },
    { name: "普通公司", pattern: "%普通%" },
  ];
  const rows = R.computeMustApplyCoverage(list, [
    {
      company: "达标品牌",
      activeTotal: 1,
      healthy: 1,
      new7d: 1,
      checked72h: 1,
      brandRollups: {},
    },
    {
      company: "父公司集团",
      activeTotal: 9,
      healthy: 9,
      new7d: 9,
      checked72h: 9,
      brandRollups: {
        "%达标%": { activeTotal: 4, healthy: 3, new7d: 2, checked72h: 3 },
        "%不足%": { activeTotal: 5, healthy: 2, new7d: 4, checked72h: 2 },
      },
    },
  ]);
  assert.equal(rows[0].healthy, 4);
  assert.equal(rows[0].activeTotal, 5);
  assert.equal(rows[0].new7d, 3);
  assert.equal(rows[0].checked72h, 4);
  assert.equal(rows[0].parentPortalHealthy, 3);
  assert.equal(rows[0].coveredViaParentPortal, true);
  assert.equal(rows[1].healthy, 0);
  assert.equal(rows[1].parentPortalHealthy, 0);
  assert.equal(rows[2].healthy, 0);
  assert.equal(rows[2].coveredViaParentPortal, false);

  // 主聚合只返回一家不含父公司关键词的公司 → 没有门户要 rollup，第二条查询根本不该发
  await R.getCompanyActiveAggregates();
  assert.equal(calls.length, 1, "没有父公司门户时不该多发 rollup 查询");
  const main = calls[0].sql.toLowerCase();
  // 主聚合必须干净：不带任何品牌 rollup 的 ilike，否则性能修复就白做了
  // （rollup 谓词混在主聚合里，31 万 active 行每行都要跑 16 个 ilike，实测 1.1s → 5.8s）
  assert.doesNotMatch(main, /brand_healthy_/);
  assert.doesNotMatch(main, /ilike/);
  assert.equal(calls[0].params, undefined);
  assert.equal((main.match(/from jobs/g) || []).length, 1);

  // 缓存 + in-flight 合并仍然生效
  await Promise.all([R.getCompanyActiveAggregates(), R.getCompanyActiveAggregates()]);
  await R.getCompanyActiveAggregates();
  assert.equal(calls.length, 1);
});

// rollup 拆成第二条查询后：只把主聚合里「像父公司门户」的公司名送进去，且按**精确公司名**取
// （走 jobs_active_company_idx；实测 ilike 全扫 1040ms → 精确名 227ms）。
test("brand rollup is a second query keyed by exact company name", async () => {
  const calls = [];
  const R = loadReader(async (sql, params) => {
    calls.push({ sql, params });
    if (/company = any/.test(sql)) {
      return [{
        company: "京东集团",
        brand_healthy_2_active: 4, brand_healthy_2_healthy: 3, brand_healthy_2_new_7d: 2, brand_healthy_2_checked_72h: 3,
      }];
    }
    return [
      { company: "京东集团", active_total: 9, healthy: 9, new_7d: 9, checked_72h: 9 },
      { company: "京东物流", active_total: 3, healthy: 3, new_7d: 1, checked_72h: 2 },
      { company: "毫不相干公司", active_total: 7, healthy: 6, new_7d: 5, checked_72h: 4 },
    ];
  });
  const aggregates = await R.getCompanyActiveAggregates();
  assert.equal(calls.length, 2);
  const rollup = calls[1].sql.toLowerCase();
  assert.match(rollup, /where status = 'active' and company = any\(\$1::text\[\]\)/);
  assert.doesNotMatch(rollup, /company ilike any/);
  // 归属判定仍由 SQL 里的 ilike 谓词决定，JS 只负责挑「送哪些公司名进去」
  assert.match(rollup, /count\(\*\) filter[\s\S]*title ilike any/);
  assert.doesNotMatch(rollup, /summary ilike/);
  assert.match(rollup, /company not ilike/);
  assert.equal((rollup.match(/as brand_healthy_\d+_healthy/g) || []).length, 4);
  // 只送命中父公司 pattern 的公司名（京东集团/京东物流命中 %京东%，不相干的不送）
  assert.deepEqual(calls[1].params[0], ["京东集团", "京东物流"]);
  assert.deepEqual(calls[1].params.slice(1), [
    "%蚂蚁%", "%网商银行%", ["%网商%"],
    "%吉利%", "%极氪%", ["%极氪%"],
    "%京东%", "%京东物流%", ["%京东物流%"],
    "%网易%", "%网易云音乐%", ["%云音乐%"],
  ]);

  // rollup 行按 company 回挂；没命中的公司每个 pattern 都是 0，主聚合数字不受影响
  const parent = aggregates.find((a) => a.company === "京东集团");
  const other = aggregates.find((a) => a.company === "毫不相干公司");
  assert.deepEqual(parent.brandRollups["%京东物流%"], { activeTotal: 4, healthy: 3, new7d: 2, checked72h: 3 });
  for (const pattern of Object.keys(parent.brandRollups)) {
    assert.deepEqual(other.brandRollups[pattern], { activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0 });
  }
  assert.equal(other.activeTotal, 7);
  assert.equal(other.healthy, 6);
});

test("北极星覆盖按 pattern + 别名匹配，同一行公司只计一次", async () => {
  // 库里用英文名记着这家公司（壳牌=Shell / 大陆集团=Continental）时，只按中文 pattern 匹配
  // 会让「有源有岗」的公司在北极星上显示 0 —— 而「有岗但指标显示 0」比「真没岗」更危险：
  // 它会驱动人去重复补源（2026-09-04 因此插了第二条壳牌源，同一个岗在库里存了两行）。
  const R = loadReader();
  const list = [
    { name: "大陆集团", pattern: "%大陆集团%", aliases: ["%Continental%"] },
    { name: "壳牌", pattern: "%壳牌%", aliases: ["%Shell%"] },
    { name: "无别名公司", pattern: "%无别名%" },
  ];
  const agg = (company, n) => ({
    company, activeTotal: n, healthy: n, new7d: n, checked72h: n,
    campusJobs: 0, internJobs: 0, socialJobs: 0, brandRollups: {},
  });
  const rows = R.computeMustApplyCoverage(list, [
    agg("Continental", 425),
    agg("大陆集团（中国）", 3),
    agg("Shell", 21),
    agg("无别名公司", 5),
    agg("Continental Grain 不相干", 0),
  ]);
  const by = Object.fromEntries(rows.map((row) => [row.name, row]));
  // pattern 与别名各命中一行 → 相加，不是二选一
  assert.equal(by["大陆集团"].healthy, 428);
  assert.equal(by["壳牌"].healthy, 21);
  // 没写别名的公司行为逐字不变
  assert.equal(by["无别名公司"].healthy, 5);
});

test("同时命中 pattern 与别名的同一行公司不会被重复累加", async () => {
  const R = loadReader();
  const rows = R.computeMustApplyCoverage(
    [{ name: "拜耳", pattern: "%拜耳%", aliases: ["%Bayer%"] }],
    [{
      company: "拜耳 Bayer", activeTotal: 76, healthy: 76, new7d: 1, checked72h: 2,
      campusJobs: 0, internJobs: 0, socialJobs: 0, brandRollups: {},
    }],
  );
  assert.equal(rows[0].healthy, 76);
  assert.equal(rows[0].activeTotal, 76);
});
