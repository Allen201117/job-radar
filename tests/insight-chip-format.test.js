const assert = require("node:assert/strict");
const fs = require("node:fs");
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
    },
  }).outputText;
  const module = { exports: {} };
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const F = loadTsModule(path.join("lib", "insight-chip-format.ts"));

test("formatHiringSignalChip maps momentum and intensity to short chip copy", () => {
  assert.deepEqual(
    F.formatHiringSignalChip({
      momentum: "expanding",
      intensity: "high",
      trend: 32,
      active_count: 120,
    }),
    { text: "扩张 · 高强度", tone: "positive" },
  );
  assert.deepEqual(
    F.formatHiringSignalChip({
      momentum: "tightening",
      intensity: "low",
      trend: -42,
      active_count: 8,
    }),
    { text: "收紧 · 低强度", tone: "warning" },
  );
  assert.deepEqual(
    F.formatHiringSignalChip({ momentum: "steady", trend: null, active_count: 20 }),
    { text: "平稳", tone: "neutral" },
  );
});

test("formatHiringSignalChip ignores malformed payload", () => {
  assert.equal(F.formatHiringSignalChip(null), null);
  assert.equal(F.formatHiringSignalChip({ momentum: "boom" }), null);
});

test("formatFinancialChips emits compact FY, revenue, yoy, employee chips", () => {
  assert.deepEqual(
    F.formatFinancialChips({
      fy: 2025,
      revenue: 1234000000,
      net_income: -52000000,
      revenue_yoy_pct: -7,
      employees: 26000,
    }).map((c) => c.text),
    ["FY2025", "营收 1.2B 美元", "净利 -52M 美元", "同比 -7%", "员工 2.6万"],
  );
});

test("formatFinancialChips omits empty values and keeps signs", () => {
  assert.deepEqual(
    F.formatFinancialChips({
      revenue_yoy_pct: 12,
      employees: null,
    }).map((c) => c.text),
    ["同比 +12%"],
  );
  assert.deepEqual(F.formatFinancialChips(null), []);
});
