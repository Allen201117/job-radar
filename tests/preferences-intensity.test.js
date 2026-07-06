// 偏好 PUT 输入校验（§8.1 / 05 §3.1）：写 radar_intensity（source=user 由路由补）；不接受 user_id；非法强度拒绝。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { parsePreferencesInput } = loadOpp("preferences-input");

test("带 user_id → validation_failed（不接受客户端 user_id）", () => {
  const r = parsePreferencesInput({ user_id: "someone", target_roles: ["x"] });
  assert.equal(r.ok, false);
  assert.equal(r.error, "validation_failed");
});

test("radar_intensity 非法值（如 radar_mode 老值）→ validation_failed", () => {
  assert.equal(parsePreferencesInput({ radar_intensity: "sprint" }).error, "validation_failed");
  assert.equal(parsePreferencesInput({ radar_intensity: 1 }).error, "validation_failed");
});

test("radar_intensity='passive' → ok 且 intensity='passive'", () => {
  const r = parsePreferencesInput({ radar_intensity: "passive", target_roles: ["产品经理"] });
  assert.equal(r.ok, true);
  assert.equal(r.value.intensity, "passive");
  assert.deepEqual(r.value.prefs.target_roles, ["产品经理"]);
});

test("未带 radar_intensity → ok 且 intensity=null（不动既有强度）", () => {
  const r = parsePreferencesInput({ target_keywords: ["AI"] });
  assert.equal(r.ok, true);
  assert.equal(r.value.intensity, null);
});

test("experience_stage 只接受空/实习/校招/社招，非法值归一为空", () => {
  const intern = parsePreferencesInput({ experience_stage: "实习" });
  assert.equal(intern.ok, true);
  assert.equal(intern.value.prefs.experience_stage, "实习");

  const none = parsePreferencesInput({ experience_stage: "" });
  assert.equal(none.ok, true);
  assert.equal(none.value.prefs.experience_stage, null);

  const bad = parsePreferencesInput({ experience_stage: "高级" });
  assert.equal(bad.ok, true);
  assert.equal(bad.value.prefs.experience_stage, null);
});

test("非对象 body → invalid_json", () => {
  assert.equal(parsePreferencesInput(null).error, "invalid_json");
  assert.equal(parsePreferencesInput("oops").error, "invalid_json");
  assert.equal(parsePreferencesInput(5).error, "invalid_json");
});

test("daily_limit clamp 5–30；数组 trim/去空/去重", () => {
  const r = parsePreferencesInput({ daily_limit: 99, target_keywords: ["AI", "ai", " 数据 ", "数据", ""] });
  assert.equal(r.value.prefs.daily_limit, 30);
  assert.deepEqual(r.value.prefs.target_keywords, ["AI", "数据"]);
});
