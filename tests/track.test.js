const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

// lib/track.ts 是 TS 源；按仓库既有约定（见 insight-verification.test.js）在内存里转译后加载，
// 只测纯函数部分（track() 含浏览器 API，不在此触发）。
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

const T = loadTsModule(path.join("lib", "track.ts"));

// ---------- normalizeEventName ----------
test("normalizeEventName keeps a valid name and trims surrounding space", () => {
  assert.equal(T.normalizeEventName("job_click"), "job_click");
  assert.equal(T.normalizeEventName("  search  "), "search");
});

test("normalizeEventName rejects empty, non-string, and over-length names", () => {
  assert.equal(T.normalizeEventName(""), null);
  assert.equal(T.normalizeEventName("   "), null);
  assert.equal(T.normalizeEventName(123), null);
  assert.equal(T.normalizeEventName(null), null);
  assert.equal(T.normalizeEventName(undefined), null);
  assert.equal(T.normalizeEventName("x".repeat(T.MAX_EVENT_LENGTH + 1)), null);
  assert.equal(T.normalizeEventName("x".repeat(T.MAX_EVENT_LENGTH)).length, T.MAX_EVENT_LENGTH);
});

// ---------- sanitizePayload ----------
test("sanitizePayload returns a JSON-serializable plain object", () => {
  assert.deepEqual(T.sanitizePayload({ job_id: "j1", company: "字节" }), {
    job_id: "j1",
    company: "字节",
  });
});

test("sanitizePayload coerces non-object / array / null to empty object", () => {
  assert.deepEqual(T.sanitizePayload(null), {});
  assert.deepEqual(T.sanitizePayload(undefined), {});
  assert.deepEqual(T.sanitizePayload("nope"), {});
  assert.deepEqual(T.sanitizePayload(42), {});
  assert.deepEqual(T.sanitizePayload([1, 2, 3]), {});
});

test("sanitizePayload drops non-serializable values (functions/undefined)", () => {
  const out = T.sanitizePayload({ a: 1, b: undefined, c: () => 1, d: "x" });
  assert.deepEqual(out, { a: 1, d: "x" });
});

test("sanitizePayload rejects oversized payloads", () => {
  const big = { blob: "y".repeat(T.MAX_PAYLOAD_BYTES + 10) };
  assert.deepEqual(T.sanitizePayload(big), {});
});

// ---------- parseEventInput (server-side body validation) ----------
test("parseEventInput accepts a well-formed body and sanitizes payload", () => {
  assert.deepEqual(
    T.parseEventInput({ event: " job_action ", payload: { action: "saved", bad: undefined } }),
    { event: "job_action", payload: { action: "saved" } },
  );
});

test("parseEventInput defaults a missing payload to empty object", () => {
  assert.deepEqual(T.parseEventInput({ event: "refresh_click" }), {
    event: "refresh_click",
    payload: {},
  });
});

test("parseEventInput rejects bad bodies", () => {
  assert.equal(T.parseEventInput(null), null);
  assert.equal(T.parseEventInput("string"), null);
  assert.equal(T.parseEventInput({ payload: { a: 1 } }), null);
  assert.equal(T.parseEventInput({ event: "" }), null);
  assert.equal(T.parseEventInput({ event: 7 }), null);
});

// ---------- aggregateEventCounts (admin stats) ----------
test("aggregateEventCounts groups by event and sorts by count desc", () => {
  const rows = [
    { event: "job_click" },
    { event: "search" },
    { event: "job_click" },
    { event: "job_click" },
    { event: "search" },
  ];
  assert.deepEqual(T.aggregateEventCounts(rows), [
    { event: "job_click", count: 3 },
    { event: "search", count: 2 },
  ]);
});

test("aggregateEventCounts breaks count ties by event name ascending", () => {
  const rows = [{ event: "search" }, { event: "job_click" }];
  assert.deepEqual(T.aggregateEventCounts(rows), [
    { event: "job_click", count: 1 },
    { event: "search", count: 1 },
  ]);
});

test("aggregateEventCounts ignores rows with invalid event names", () => {
  const rows = [{ event: "job_click" }, { event: "" }, { event: null }, {}, { event: "job_click" }];
  assert.deepEqual(T.aggregateEventCounts(rows), [{ event: "job_click", count: 2 }]);
});

test("aggregateEventCounts returns empty array for empty input", () => {
  assert.deepEqual(T.aggregateEventCounts([]), []);
});
