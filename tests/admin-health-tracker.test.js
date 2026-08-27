const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const tracker = loadTs(path.join(__dirname, "..", "lib", "admin-health-tracker.ts"));

// 反向哨兵：dailyTrackerTone 是被删掉的「第二套判据」（热力图专用、与模块卡方向相反，
// 线上造成过「热力图全红 vs 模块卡全绿」）。全站唯一判据是 admin-health 的 moduleVerdict。
test("热力图不许再有自己的一套判据：dailyTrackerTone 必须保持删除状态", () => {
  assert.equal(tracker.dailyTrackerTone, undefined);
});

test("nullable share distinguishes missing inputs from a real zero", () => {
  assert.equal(tracker.nullableShare(null, 30), null);
  assert.equal(tracker.nullableShare(2, null), null);
  assert.equal(tracker.nullableShare(0, 30), 0);
  assert.equal(tracker.nullableShare(3, 30), 0.1);
});
