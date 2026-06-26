const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

// 这里只覆盖「自定义输入校验」纯逻辑（§18.6 的 400 系列）。
// 401（未登录）由各路由首行 requireUser() 保证；「不能改别人 action / 读别人请求」由
// set_job_primary_action(auth.uid()) + RLS 保证——都需 Next/Supabase 运行时，不在 node --test 内重测。
const { parseActionInput, parseRadarOpenInput, isUuid } = loadOpp("action-input");

const UUID = "11111111-1111-1111-1111-111111111111";

test("isUuid 基本判定", () => {
  assert.equal(isUuid(UUID), true);
  assert.equal(isUuid("nope"), false);
});

test("parseActionInput: 非法 jobId → invalid_job_id", () => {
  const r = parseActionInput("not-a-uuid", { action: "saved" });
  assert.equal(r.ok, false);
  assert.equal(r.error, "invalid_job_id");
});

test("parseActionInput: 非法 action → invalid_action", () => {
  assert.equal(parseActionInput(UUID, { action: "lol" }).error, "invalid_action");
});

test("parseActionInput: ignored 无/非法 reason → reason_required", () => {
  assert.equal(parseActionInput(UUID, { action: "ignored" }).error, "reason_required");
  assert.equal(parseActionInput(UUID, { action: "ignored", reason_code: "bogus" }).error, "reason_required");
});

test("parseActionInput: ignored 合法 reason → ok（非 other 不带 text）", () => {
  const r = parseActionInput(UUID, { action: "ignored", reason_code: "role_mismatch", reason_text: "x" });
  assert.equal(r.ok, true);
  assert.equal(r.value.action, "ignored");
  assert.equal(r.value.reasonCode, "role_mismatch");
  assert.equal(r.value.reasonText, null);
});

test("parseActionInput: other 保留 trim 后的 reason_text", () => {
  const r = parseActionInput(UUID, { action: "ignored", reason_code: "other", reason_text: "  太远了  " });
  assert.equal(r.ok, true);
  assert.equal(r.value.reasonText, "太远了");
});

test("parseActionInput: reason_text 超 200 → reason_text_too_long", () => {
  const r = parseActionInput(UUID, { action: "ignored", reason_code: "other", reason_text: "x".repeat(201) });
  assert.equal(r.ok, false);
  assert.equal(r.error, "reason_text_too_long");
});

test("parseActionInput: §3.4 客户端传 job_snapshot → validation_failed(400)", () => {
  const r = parseActionInput(UUID, { action: "saved", job_snapshot: { company: "伪造" } });
  assert.equal(r.ok, false);
  assert.equal(r.error, "validation_failed");
});

test("parseActionInput: §3.4 客户端传 user_id → validation_failed(400)", () => {
  const r = parseActionInput(UUID, { action: "saved", user_id: "11111111-1111-1111-1111-111111111111" });
  assert.equal(r.ok, false);
  assert.equal(r.error, "validation_failed");
});

test("parseActionInput: saved 清空 reason；action=null 允许", () => {
  const s = parseActionInput(UUID, { action: "saved", reason_code: "role_mismatch" });
  assert.equal(s.value.reasonCode, null);
  assert.equal(s.value.reasonText, null);
  const n = parseActionInput(UUID, { action: null });
  assert.equal(n.ok, true);
  assert.equal(n.value.action, null);
});

test("parseRadarOpenInput: 缺失/未来>5min generated_at → invalid_generated_at", () => {
  const now = Date.UTC(2026, 5, 23, 12, 0, 0);
  assert.equal(parseRadarOpenInput({}, now).error, "invalid_generated_at");
  const future = new Date(now + 10 * 60 * 1000).toISOString();
  assert.equal(parseRadarOpenInput({ generated_at: future, feed_count: 5 }, now).error, "invalid_generated_at");
});

test("parseRadarOpenInput: feed_count 越界 → invalid_feed_count", () => {
  const now = Date.UTC(2026, 5, 23, 12, 0, 0);
  const g = new Date(now - 1000).toISOString();
  assert.equal(parseRadarOpenInput({ generated_at: g, feed_count: 31 }, now).error, "invalid_feed_count");
  assert.equal(parseRadarOpenInput({ generated_at: g, feed_count: -1 }, now).error, "invalid_feed_count");
  assert.equal(parseRadarOpenInput({ generated_at: g, feed_count: "x" }, now).error, "invalid_feed_count");
});

test("parseRadarOpenInput: 合法 → ok", () => {
  const now = Date.UTC(2026, 5, 23, 12, 0, 0);
  const g = new Date(now - 1000).toISOString();
  const r = parseRadarOpenInput({ generated_at: g, feed_count: 12 }, now);
  assert.equal(r.ok, true);
  assert.equal(r.value.feedCount, 12);
});
