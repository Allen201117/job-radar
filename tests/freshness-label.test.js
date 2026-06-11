const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const compiled = ts.transpileModule(fs.readFileSync(sourcePath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    module.exports,
    require,
    module,
    sourcePath,
    path.dirname(sourcePath),
  );
  return module.exports;
}

const { freshnessLabel } = loadTsModule(path.join("lib", "utils.ts"));

const DAY = 86_400_000;
const daysAgo = (n) => new Date(Date.now() - n * DAY).toISOString();

test("今天确认在招（last_seen 就在当下）", () => {
  const r = freshnessLabel(new Date().toISOString());
  assert.equal(r.label, "今天确认在招");
  assert.equal(r.stale, false);
});

test("3 天前确认在招（新鲜，不告警）", () => {
  const r = freshnessLabel(daysAgo(3));
  assert.equal(r.label, "3 天前确认在招");
  assert.equal(r.stale, false);
});

test("15 天 → 超过 14 天告警，stale=true", () => {
  const r = freshnessLabel(daysAgo(15));
  assert.equal(r.label, "14+ 天未确认，可能已下线");
  assert.equal(r.stale, true);
});

test("null → 空 label，不告警", () => {
  const r = freshnessLabel(null);
  assert.equal(r.label, "");
  assert.equal(r.stale, false);
});
