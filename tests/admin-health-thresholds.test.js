const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
      resolveJsonModule: true,
    },
  }).outputText;
  const module = { exports: {} };
  const scopedRequire = Module.createRequire(sourcePath);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, scopedRequire, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const H = loadTsModule(path.join("lib", "admin-health.ts"));

test("band classifies higher-is-better thresholds at exact boundaries", () => {
  assert.equal(typeof H.band, "function");
  assert.equal(H.band(0.99, H.HEALTH_THRESHOLDS.clickValidity, "higher"), "good");
  assert.equal(H.band(0.9, H.HEALTH_THRESHOLDS.clickValidity, "higher"), "warn");
  assert.equal(H.band(0.899, H.HEALTH_THRESHOLDS.clickValidity, "higher"), "bad");
  assert.equal(H.band(null, H.HEALTH_THRESHOLDS.clickValidity, "higher"), "empty");
});

test("band classifies lower-is-better thresholds at exact boundaries", () => {
  assert.equal(H.band(0.099, H.HEALTH_THRESHOLDS.thinActiveShare, "lower"), "good");
  assert.equal(H.band(0.1, H.HEALTH_THRESHOLDS.thinActiveShare, "lower"), "warn");
  assert.equal(H.band(0.251, H.HEALTH_THRESHOLDS.thinActiveShare, "lower"), "bad");
});

test("coverageBand uses one unified 90/60 threshold", () => {
  assert.equal(typeof H.coverageBand, "function");
  assert.equal(H.coverageBand(90), "good");
  assert.equal(H.coverageBand(89), "warn");
  assert.equal(H.coverageBand(60), "warn");
  assert.equal(H.coverageBand(59), "bad");
  assert.equal(H.coverageBand(null), "empty");
});

test("combined verdict cannot be green when must-apply north star is red", () => {
  assert.equal(typeof H.evaluateCombinedHealth, "function");
  const verdict = H.evaluateCombinedHealth({
    validActive: 5000,
    crawlRuns: 4,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.995,
    mustApplyHealthyCompanies: 23,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: ["字节跳动", "腾讯"],
    mustApplyBlindCompanies: [],
    coverageAvgPct: 94,
    coverageBlindSources: 0,
  });

  assert.equal(verdict.level, "critical");
  assert.equal(verdict.label, "出事");
  assert.deepEqual(verdict.actions.slice(0, 1), ["字节跳动、腾讯：必投公司零健康岗"]);
});

test("combined verdict promotes click validity below promise to a critical action", () => {
  const verdict = H.evaluateCombinedHealth({
    validActive: 1000,
    crawlRuns: 2,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.88,
    mustApplyHealthyCompanies: 30,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: [],
    mustApplyBlindCompanies: [],
    coverageAvgPct: 92,
    coverageBlindSources: 0,
  });

  assert.equal(verdict.level, "critical");
  assert.equal(verdict.actions[0], "点击有效率 88.0%（目标≥99%）");
});

test("combined verdict warns on blind spots and stays healthy when all core bands are good", () => {
  const warning = H.evaluateCombinedHealth({
    validActive: 1000,
    crawlRuns: 2,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.995,
    mustApplyHealthyCompanies: 28,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: [],
    mustApplyBlindCompanies: ["阿里巴巴"],
    coverageAvgPct: 91,
    coverageBlindSources: 0,
  });
  assert.equal(warning.level, "warning");
  assert.equal(warning.actions[0], "阿里巴巴：有岗但 72h 未核验");

  const healthy = H.evaluateCombinedHealth({
    validActive: 1000,
    crawlRuns: 2,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.995,
    mustApplyHealthyCompanies: 30,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: [],
    mustApplyBlindCompanies: [],
    coverageAvgPct: 91,
    coverageBlindSources: 0,
  });
  assert.equal(healthy.level, "healthy");
  assert.deepEqual(healthy.actions, ["核心承诺正常：必投清单、点击有效率、今日抓取都在阈值内。"]);
});

test("combined verdict uses the worst active must-apply industry band", () => {
  const verdict = H.evaluateCombinedHealth({
    validActive: 1000,
    crawlRuns: 2,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.995,
    mustApplyHealthyCompanies: 29,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: [],
    mustApplyBlindCompanies: [],
    mustApplyIndustries: [
      { industry: "互联网/科技", healthy: 29, total: 30, zeroHealthyCompanies: [], blindCompanies: [], userCount: 2 },
      { industry: "金融", healthy: 3, total: 30, zeroHealthyCompanies: ["招商银行"], blindCompanies: [], userCount: 1 },
    ],
    coverageAvgPct: 92,
    coverageBlindSources: 0,
  });
  assert.equal(verdict.bands.mustApply, "bad");
  assert.equal(verdict.level, "critical");
  assert.ok(verdict.actions.some((action) => action.includes("金融行业必投覆盖 3/30")));
});

test("single warn-band industry does not duplicate the must-apply action", () => {
  const verdict = H.evaluateCombinedHealth({
    validActive: 1000,
    crawlRuns: 2,
    crawlFailedRuns: 0,
    clickProbeValidityRate: 0.995,
    mustApplyHealthyCompanies: 26,
    mustApplyTotalCompanies: 30,
    mustApplyZeroHealthyCompanies: [],
    mustApplyBlindCompanies: [],
    mustApplyIndustries: [
      { industry: "互联网/科技", healthy: 26, total: 30, zeroHealthyCompanies: [], blindCompanies: [], userCount: 2 },
    ],
    coverageAvgPct: 92,
    coverageBlindSources: 0,
  });
  assert.equal(verdict.bands.mustApply, "warn");
  const mustApplyActions = verdict.actions.filter((action) => action.includes("必投") && action.includes("26/30"));
  assert.equal(mustApplyActions.length, 1);
  assert.ok(mustApplyActions[0].includes("互联网/科技行业必投覆盖 26/30"));
});
