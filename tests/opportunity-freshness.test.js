const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const Module = require("node:module");

// 即时转译加载 TS 引擎模块（与 tests/scoring.test.js 同套路）。
function loadModule(rel) {
  const sourcePath = path.join(__dirname, "..", "lib", "opportunities", rel);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const mod = { exports: {} };
  const scopedRequire = Module.createRequire(sourcePath);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(mod.exports, scopedRequire, mod, sourcePath, path.dirname(sourcePath));
  return mod.exports;
}

const { freshnessState } = loadModule("freshness.ts");

const NOW = new Date("2026-06-23T12:00:00.000Z");
const hoursAgo = (h) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();

test("http SLA: verified<=18h, aging<=36h, stale>36h", () => {
  assert.equal(freshnessState(hoursAgo(17), "http", NOW), "verified");
  assert.equal(freshnessState(hoursAgo(18), "http", NOW), "verified"); // 边界含
  assert.equal(freshnessState(hoursAgo(19), "http", NOW), "aging");
  assert.equal(freshnessState(hoursAgo(36), "http", NOW), "aging"); // 边界含
  assert.equal(freshnessState(hoursAgo(37), "http", NOW), "stale");
});

test("playwright SLA: verified<=36h, aging<=72h, stale>72h", () => {
  assert.equal(freshnessState(hoursAgo(35), "playwright", NOW), "verified");
  assert.equal(freshnessState(hoursAgo(40), "playwright", NOW), "aging");
  assert.equal(freshnessState(hoursAgo(73), "playwright", NOW), "stale");
});

test("manual / 未知 method SLA: verified<=72h", () => {
  assert.equal(freshnessState(hoursAgo(70), "manual", NOW), "verified");
  assert.equal(freshnessState(hoursAgo(70), null, NOW), "verified"); // null method 走 manual SLA
  assert.equal(freshnessState(hoursAgo(70), "weird-unknown", NOW), "verified");
  assert.equal(freshnessState(hoursAgo(145), "manual", NOW), "stale");
});

test("无 last_seen_at / 非法时间 → unknown", () => {
  assert.equal(freshnessState(null, "http", NOW), "unknown");
  assert.equal(freshnessState("", "http", NOW), "unknown");
  assert.equal(freshnessState("not-a-date", "http", NOW), "unknown");
});
