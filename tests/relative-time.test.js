const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const { relativeTimeLabel } = loadTs(path.join(__dirname, "..", "lib", "relative-time.ts"));
const now = new Date("2026-07-13T12:00:00.000Z");

test("relativeTimeLabel handles same-day and recent day boundaries", () => {
  assert.equal(relativeTimeLabel("2026-07-13T00:00:00.000Z", now), "今天");
  assert.equal(relativeTimeLabel("2026-07-12T12:00:00.000Z", now), "昨天");
  assert.equal(relativeTimeLabel("2026-07-07T12:00:00.000Z", now), "6天前");
});

test("relativeTimeLabel handles week, month, and year boundaries", () => {
  assert.equal(relativeTimeLabel("2026-07-06T12:00:00.000Z", now), "1周前");
  assert.equal(relativeTimeLabel("2026-06-14T12:00:00.000Z", now), "4周前");
  assert.equal(relativeTimeLabel("2026-06-13T12:00:00.000Z", now), "1个月前");
  assert.equal(relativeTimeLabel("2025-07-14T12:00:00.000Z", now), "12个月前");
  assert.equal(relativeTimeLabel("2025-07-13T12:00:00.000Z", now), "1年前");
});

test("relativeTimeLabel handles future, empty, and invalid input", () => {
  assert.equal(relativeTimeLabel("2026-07-14T12:00:00.000Z", now), "今天");
  assert.equal(relativeTimeLabel(null, now), null);
  assert.equal(relativeTimeLabel("not a date", now), null);
});
