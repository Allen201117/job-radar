const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const tracker = loadTs(path.join(__dirname, "..", "lib", "admin-health-tracker.ts"));

test("daily tracker keeps no record separate from a real zero failure count", () => {
  assert.equal(tracker.dailyTrackerTone(null), "muted");
  assert.equal(tracker.dailyTrackerTone({}), "muted");
  assert.equal(tracker.dailyTrackerTone({ runs: 0, failed: 0, partial: 0 }), "success");
});

test("daily tracker gives failed runs priority over partial runs", () => {
  assert.equal(tracker.dailyTrackerTone({ runs: 3, failed: 0, partial: 1 }), "warning");
  assert.equal(tracker.dailyTrackerTone({ runs: 3, failed: 1, partial: 1 }), "danger");
});

test("nullable share distinguishes missing inputs from a real zero", () => {
  assert.equal(tracker.nullableShare(null, 30), null);
  assert.equal(tracker.nullableShare(2, null), null);
  assert.equal(tracker.nullableShare(0, 30), 0);
  assert.equal(tracker.nullableShare(3, 30), 0.1);
});
