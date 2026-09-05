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
      scope: "domestic",
      activeTotal: 1,
      healthy: 1,
      new7d: 1,
      checked72h: 1,
      brandRollups: {},
    },
    {
      company: "父公司集团",
      scope: "domestic",
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
  // 必投覆盖要分国内/海外算 → 主聚合必须按 (company, job_scope) 拆行
  assert.match(main, /group by company, job_scope/);

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
  // rollup 也必须按 scope 拆，否则同一家的国内行与海外行会共用一份 rollup、双重计入
  assert.match(rollup, /group by company, job_scope/);
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


// ⚠️ 这条守的是「指标诚实」：清单分国内/海外两份，岗位也分，两边必须对齐。
// 2026-09-05 之前 computeMustApplyCoverage 不看 job_scope，于是拿另一半的岗位背书：
//   · 国内清单里的松下记 234 个健康岗判「已覆盖」，实际全在美国堪萨斯、中国岗 0
//   · 海外清单里的星巴克记 1,935 个判「已覆盖海外」，实际 9,078 个岗全在中国
test("must-apply coverage only counts jobs in the same scope as the list", () => {
  const R = loadReader();
  const list = [{ name: "松下", pattern: "%松下%" }];
  const aggregates = [
    { company: "松下 Panasonic", scope: "overseas", activeTotal: 234, healthy: 234, new7d: 3, checked72h: 200, brandRollups: {} },
    { company: "松下 Panasonic", scope: "domestic", activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0, brandRollups: {} },
  ];
  const domestic = R.computeMustApplyCoverage(list, aggregates, "domestic");
  assert.equal(domestic[0].healthy, 0, "国内清单不许把美国岗算成已覆盖");
  assert.equal(domestic[0].activeTotal, 0);

  const overseas = R.computeMustApplyCoverage(list, aggregates, "overseas");
  assert.equal(overseas[0].healthy, 234, "海外那半照常算");

  // 不传 scope 时按国内算（与 mustApplyUnion 的默认一致），不能退回「全都算」
  assert.equal(R.computeMustApplyCoverage(list, aggregates)[0].healthy, 0);
});

// 父门户 rollup 同理：品牌岗也要按 scope 分，别让海外岗把国内品牌撑成「已覆盖」
test("parent portal rollup is scoped too", () => {
  const R = loadReader();
  const list = [{ name: "某品牌", pattern: "%品牌%", parentPattern: "%父公司%", brandTokens: ["品牌"] }];
  const rollup = { activeTotal: 9, healthy: 9, new7d: 9, checked72h: 9 };
  const aggregates = [
    { company: "父公司集团", scope: "overseas", activeTotal: 9, healthy: 9, new7d: 9, checked72h: 9, brandRollups: { "%品牌%": rollup } },
    { company: "父公司集团", scope: "domestic", activeTotal: 0, healthy: 0, new7d: 0, checked72h: 0, brandRollups: {} },
  ];
  assert.equal(R.computeMustApplyCoverage(list, aggregates, "domestic")[0].parentPortalHealthy, 0);
  assert.equal(R.computeMustApplyCoverage(list, aggregates, "overseas")[0].parentPortalHealthy, 9);
});

// 校招供给用的是国内清单 → 只能拿国内岗算，否则「某家校招已打通」会被海外岗撑起来
test("campus supply inputs are scoped to domestic", async () => {
  const R = loadReader(async () => [
    { company: "某大厂", job_scope: "overseas", active_total: 50, healthy: 50, new_7d: 0, checked_72h: 0, campus_jobs: 40, intern_jobs: 5, social_jobs: 5 },
    { company: "某大厂", job_scope: "domestic", active_total: 3, healthy: 3, new_7d: 0, checked_72h: 0, campus_jobs: 1, intern_jobs: 2, social_jobs: 0 },
  ]);
  const [row] = await R.getCampusSupplyInputs([{ name: "某大厂", pattern: "%某大厂%" }]);
  assert.deepEqual(row, { company: "某大厂", campusJobs: 1, internJobs: 2, socialJobs: 0 });
});
