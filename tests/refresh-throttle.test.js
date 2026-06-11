const assert = require("node:assert/strict");
const test = require("node:test");

const { evaluateRefreshThrottle, DEFAULT_COOLDOWN_MS } = require("../lib/refresh-throttle");

const NOW = Date.parse("2026-06-11T10:00:00Z");
const ago = (ms) => new Date(NOW - ms).toISOString();

test("空历史 → 放行 dispatch", () => {
  assert.equal(evaluateRefreshThrottle([], NOW).action, "dispatch");
  assert.equal(evaluateRefreshThrottle(null, NOW).action, "dispatch");
});

test("有在飞 run（running）→ 复用，不重复 dispatch", () => {
  const runs = [{ id: "r1", status: "running", created_at: ago(30 * 1000) }];
  const res = evaluateRefreshThrottle(runs, NOW);
  assert.equal(res.action, "reuse");
  assert.equal(res.run.id, "r1");
});

test("有 queued run → 复用（快速连点幂等）", () => {
  const runs = [{ id: "q1", status: "queued", created_at: ago(2 * 1000) }];
  assert.equal(evaluateRefreshThrottle(runs, NOW).action, "reuse");
});

test("冷却窗口内刚结束 → cooldown + 合理 Retry-After", () => {
  const runs = [{ id: "d1", status: "success", created_at: ago(3 * 60 * 1000) }];
  const res = evaluateRefreshThrottle(runs, NOW);
  assert.equal(res.action, "cooldown");
  // 10min 冷却 - 已过 3min ≈ 剩 7min
  assert.ok(res.retryAfterSec > 6 * 60 && res.retryAfterSec <= 7 * 60, `retryAfter=${res.retryAfterSec}`);
});

test("冷却窗口外（>10min 前结束）→ 放行", () => {
  const runs = [{ id: "old", status: "success", created_at: ago(11 * 60 * 1000) }];
  assert.equal(evaluateRefreshThrottle(runs, NOW).action, "dispatch");
});

test("stale 在飞 run（>20min，CI 崩溃）→ 不复用，放行重刷", () => {
  const runs = [{ id: "stuck", status: "running", created_at: ago(25 * 60 * 1000) }];
  assert.equal(evaluateRefreshThrottle(runs, NOW).action, "dispatch");
});

test("在飞优先于冷却：既有 running 又有刚结束 → reuse", () => {
  const runs = [
    { id: "fin", status: "success", created_at: ago(1 * 60 * 1000) },
    { id: "run", status: "running", created_at: ago(20 * 1000) },
  ];
  const res = evaluateRefreshThrottle(runs, NOW);
  assert.equal(res.action, "reuse");
  assert.equal(res.run.id, "run");
});

test("failed run 不算在飞，且在冷却窗内仍 cooldown", () => {
  const runs = [{ id: "f", status: "failed", created_at: ago(60 * 1000) }];
  const res = evaluateRefreshThrottle(runs, NOW);
  assert.equal(res.action, "cooldown");
});

test("可调冷却窗口", () => {
  const runs = [{ id: "x", status: "success", created_at: ago(30 * 1000) }];
  assert.equal(evaluateRefreshThrottle(runs, NOW, { cooldownMs: 10 * 1000 }).action, "dispatch");
  assert.equal(evaluateRefreshThrottle(runs, NOW, { cooldownMs: 60 * 1000 }).action, "cooldown");
});

test("坏时间戳被忽略，不炸", () => {
  const runs = [{ id: "bad", status: "running", created_at: "not-a-date" }];
  assert.equal(evaluateRefreshThrottle(runs, NOW).action, "dispatch");
});
