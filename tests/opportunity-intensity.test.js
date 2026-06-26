// 强度推导（04 spec §3 / 05 spec §4）：手动近期优先 > 行为自调 > 默认 active；只调推荐不动 readiness。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { resolveIntensity } = loadOpp("intensity");

const NOW = new Date("2026-06-24T12:00:00Z");
function daysAgo(d) {
  return new Date(NOW.getTime() - d * 86_400_000).toISOString();
}
function input(over = {}) {
  return {
    manual: null,
    manualAgeDays: null,
    lastOpenedAt: null,
    recentActionCount14d: 0,
    hasTargetCompanies: false,
    now: NOW,
    ...over,
  };
}

test("手动优先：近期手动设 passive → passive/user", () => {
  const r = resolveIntensity(input({ manual: "passive", manualAgeDays: 5 }));
  assert.equal(r.intensity, "passive");
  assert.equal(r.source, "user");
});

test("手动尊重窗口边界：29 天仍 user、30 天转行为自调", () => {
  assert.equal(resolveIntensity(input({ manual: "passive", manualAgeDays: 29 })).source, "user");
  // 30 天前手动 active、近 14 天无动作、长期未打开 → 行为自调 passive/auto（05 §4.2）
  const r = resolveIntensity(input({ manual: "active", manualAgeDays: 30, lastOpenedAt: daysAgo(40) }));
  assert.equal(r.intensity, "passive");
  assert.equal(r.source, "auto");
});

test("行为自调 active：近 14 天有动作 → active/auto", () => {
  const r = resolveIntensity(input({ lastOpenedAt: daysAgo(40), recentActionCount14d: 2 }));
  assert.equal(r.intensity, "active");
  assert.equal(r.source, "auto");
});

test("行为自调 active：近 3 天打开过 → active/auto", () => {
  const r = resolveIntensity(input({ lastOpenedAt: daysAgo(1) }));
  assert.equal(r.intensity, "active");
  assert.equal(r.source, "auto");
});

test("行为自调 passive：长期（>14 天）未打开、无动作 → passive/auto", () => {
  const r = resolveIntensity(input({ lastOpenedAt: daysAgo(20) }));
  assert.equal(r.intensity, "passive");
  assert.equal(r.source, "auto");
});

test("中间区（3–14 天、无动作）：有关注公司→active，无→passive", () => {
  assert.equal(resolveIntensity(input({ lastOpenedAt: daysAgo(7), hasTargetCompanies: true })).intensity, "active");
  assert.equal(resolveIntensity(input({ lastOpenedAt: daysAgo(7), hasTargetCompanies: false })).intensity, "passive");
});

test("新用户无任何信号 → 默认 active/default（蜜月期）", () => {
  const r = resolveIntensity(input());
  assert.equal(r.intensity, "active");
  assert.equal(r.source, "default");
});
