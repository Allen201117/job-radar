// 分层核验 SLA（01 spec §2 / 04 spec §5）：meetsVerifyTier 按 enrich_checked_at 年龄分层；
// 从未核验（NULL）不算 verified、today/search 一律不通过、admin 无时限放行。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { meetsVerifyTier } = loadOpp("freshness");

const NOW = new Date("2026-06-24T12:00:00Z");
function job(hoursAgo) {
  if (hoursAgo === null) return { enrich_checked_at: null };
  return { enrich_checked_at: new Date(NOW.getTime() - hoursAgo * 3_600_000).toISOString() };
}

test("today tier：≤24h 通过、verified", () => {
  const r = meetsVerifyTier(job(10), "today", NOW);
  assert.equal(r.ok, true);
  assert.equal(r.freshness, "verified");
  assert.ok(Math.abs(r.checkedAgeHours - 10) < 0.001);
});

test("today tier：26h 前 → 不通过（超 24h），freshness=aging", () => {
  const r = meetsVerifyTier(job(26), "today", NOW);
  assert.equal(r.ok, false);
  assert.equal(r.freshness, "aging");
});

test("search tier：26h 前仍通过（≤72h），但 freshness=aging（标待确认）", () => {
  const r = meetsVerifyTier(job(26), "search", NOW);
  assert.equal(r.ok, true);
  assert.equal(r.freshness, "aging");
});

test("search tier：80h 前 → 不通过（超 72h），stale", () => {
  const r = meetsVerifyTier(job(80), "search", NOW);
  assert.equal(r.ok, false);
  assert.equal(r.freshness, "stale");
});

test("从未核验（enrich_checked_at=NULL）：today/search 都不通过，freshness=unknown，age=null", () => {
  for (const tier of ["today", "search"]) {
    const r = meetsVerifyTier(job(null), tier, NOW);
    assert.equal(r.ok, false, `${tier} 不该把从未核验当通过`);
    assert.equal(r.freshness, "unknown");
    assert.equal(r.checkedAgeHours, null);
  }
});

test("admin tier：无时限——即便从未核验也放行，但 freshness 仍 unknown（禁写仍在招）", () => {
  const nullR = meetsVerifyTier(job(null), "admin", NOW);
  assert.equal(nullR.ok, true);
  assert.equal(nullR.freshness, "unknown");
  const oldR = meetsVerifyTier(job(500), "admin", NOW);
  assert.equal(oldR.ok, true);
  assert.equal(oldR.freshness, "stale");
});

test("非法时间戳 → 当作从未核验（unknown，不通过 today）", () => {
  const r = meetsVerifyTier({ enrich_checked_at: "not-a-date" }, "today", NOW);
  assert.equal(r.ok, false);
  assert.equal(r.freshness, "unknown");
  assert.equal(r.checkedAgeHours, null);
});
