const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { safeNextPath } = loadTs(path.resolve(__dirname, "../lib/safe-next.ts"));

test("safeNextPath accepts safe internal paths unchanged", () => {
  assert.equal(safeNextPath("/today"), "/today");
  assert.equal(safeNextPath("/jobs?x=1"), "/jobs?x=1");
  assert.equal(safeNextPath("/saved"), "/saved");
});

test("safeNextPath rejects protocol-relative and absolute URLs", () => {
  assert.equal(safeNextPath("//evil.com"), "/today");
  assert.equal(safeNextPath("https://evil.com"), "/today");
  assert.equal(safeNextPath("http://x"), "/today");
  assert.equal(safeNextPath("javascript:alert(1)"), "/today");
});

test("safeNextPath rejects backslash bypass", () => {
  assert.equal(safeNextPath("/\\evil.com"), "/today");
  assert.equal(safeNextPath("\\evil.com"), "/today");
});

test("safeNextPath rejects control chars and whitespace", () => {
  assert.equal(safeNextPath("/x\ty"), "/today");
  assert.equal(safeNextPath("/x y"), "/today");
  assert.equal(safeNextPath("/x\ny"), "/today");
});

test("safeNextPath rejects empty, non-string, and relative paths", () => {
  assert.equal(safeNextPath(""), "/today");
  assert.equal(safeNextPath(null), "/today");
  assert.equal(safeNextPath(undefined), "/today");
  assert.equal(safeNextPath(123), "/today");
  assert.equal(safeNextPath("relative/path"), "/today");
});
