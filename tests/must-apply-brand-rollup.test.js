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

  await R.getCompanyActiveAggregates();
  assert.equal(calls.length, 1);
  const normalized = calls[0].sql.toLowerCase();
  assert.match(normalized, /count\(\*\) filter[\s\S]*title ilike any/);
  assert.doesNotMatch(normalized, /summary ilike/);
  assert.match(normalized, /company not ilike/);
  assert.equal((normalized.match(/from jobs/g) || []).length, 1);
  assert.equal((normalized.match(/as brand_healthy_\d+_healthy/g) || []).length, 4);
  assert.deepEqual(calls[0].params, [
    "%蚂蚁%", "%网商银行%", ["%网商%"],
    "%吉利%", "%极氪%", ["%极氪%"],
    "%京东%", "%京东物流%", ["%京东物流%"],
    "%网易%", "%网易云音乐%", ["%云音乐%"],
  ]);
  await Promise.all([R.getCompanyActiveAggregates(), R.getCompanyActiveAggregates()]);
  await R.getCompanyActiveAggregates();
  assert.equal(calls.length, 1);
});
