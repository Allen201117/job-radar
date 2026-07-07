// 点击有效率四护栏聚合（01 spec §5.3 / 05 §5.3）：可探源有效率 + 覆盖率 + unknown 占比 + 按 adapter 拆分。
// 关键：只报「可探源 99%」=不通过（分母偷窄）——必须四个数一起算得出。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function load(rel) {
  const sourcePath = path.join(__dirname, "..", rel);
  const src = fs.readFileSync(sourcePath, "utf8");
  const out = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText;
  const m = { exports: {} };
  const scopedRequire = Module.createRequire(sourcePath);
  new Function("exports", "require", "module", "__filename", "__dirname", out)(
    m.exports,
    scopedRequire,
    m,
    sourcePath,
    path.dirname(sourcePath),
  );
  return m.exports;
}
const { computeClickValidityMetrics } = load("lib/admin-health.ts");

function ev(event, payload) {
  return { event, payload };
}

test("可探源有效率 = alive/(alive+dead)，分母排除 unknown", () => {
  const rows = [
    ev("opportunity_official_opened", { job_id: "a", adapter: "wt" }),
    ev("job_liveness_at_click", { adapter: "wt", result: "alive" }),
    ev("job_liveness_at_click", { adapter: "wt", result: "alive" }),
    ev("job_liveness_at_click", { adapter: "wt", result: "dead" }),
    ev("job_liveness_at_click", { adapter: "wt", result: "unknown" }),
  ];
  const m = computeClickValidityMetrics(rows);
  assert.equal(m.alive, 2);
  assert.equal(m.dead, 1);
  assert.equal(m.unknown, 1);
  assert.ok(Math.abs(m.probeValidityRate - 2 / 3) < 1e-9); // unknown 不进分母
});

test("覆盖率 = (alive+dead)/总点击；unknown 占比 = unknown/总核验", () => {
  const rows = [
    ev("opportunity_official_opened", {}),
    ev("opportunity_official_opened", {}),
    ev("opportunity_official_opened", {}),
    ev("opportunity_official_opened", {}),
    ev("job_liveness_at_click", { adapter: "hotjob", result: "alive" }),
    ev("job_liveness_at_click", { adapter: "hotjob", result: "dead" }),
    ev("job_liveness_at_click", { adapter: "hotjob", result: "unknown" }),
  ];
  const m = computeClickValidityMetrics(rows);
  assert.equal(m.totalOpens, 4);
  assert.equal(m.livenessTotal, 3);
  assert.ok(Math.abs(m.coverageRate - 2 / 4) < 1e-9); // (alive+dead)/opens
  assert.ok(Math.abs(m.unknownRate - 1 / 3) < 1e-9);
});

test("按 adapter 拆分有效率", () => {
  const rows = [
    ev("job_liveness_at_click", { adapter: "wt", result: "alive" }),
    ev("job_liveness_at_click", { adapter: "wt", result: "dead" }),
    ev("job_liveness_at_click", { adapter: "workday", result: "alive" }),
    ev("job_liveness_at_click", { adapter: "workday", result: "alive" }),
  ];
  const m = computeClickValidityMetrics(rows);
  const wt = m.byAdapter.find((a) => a.adapter === "wt");
  const wd = m.byAdapter.find((a) => a.adapter === "workday");
  assert.equal(wt.validityRate, 0.5);
  assert.equal(wd.validityRate, 1);
});

test("分母为 0 → null（不假装 100%）", () => {
  const m = computeClickValidityMetrics([ev("opportunity_official_opened", {})]);
  assert.equal(m.probeValidityRate, null); // 无 alive/dead
  assert.equal(m.unknownRate, null); // 无核验
  assert.equal(m.coverageRate, 0); // 4 opens 0 verdicts → 0（有分母）
});

test("空输入安全", () => {
  const m = computeClickValidityMetrics([]);
  assert.equal(m.totalOpens, 0);
  assert.equal(m.livenessTotal, 0);
  assert.equal(m.probeValidityRate, null);
});
