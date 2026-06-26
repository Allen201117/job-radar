// 信号派生（04 spec §6 / 05 spec §6）：STILL_OPEN 需 ≤24h 核验；DEADLINE 窗口；CLOSED_OR_STALE；
// 从未核验不冒充 STILL_OPEN；NEWLY_DISCOVERED/MOMENTUM 不上（依赖 job_events）。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { deriveOpportunitySignals, primarySignal } = loadOpp("signals");

const NOW = new Date("2026-06-28T12:00:00Z");
function checkedHoursAgo(h) {
  return new Date(NOW.getTime() - h * 3_600_000).toISOString();
}
function job(over = {}) {
  return { status: "active", enrich_checked_at: checkedHoursAgo(2), posted_at: null, deadline: null, ...over };
}
const FACTS = { freshness: "verified", stageLabel: null };
const PROFILE = { experienceStage: "社招" };

function types(sigs) {
  return sigs.map((s) => s.type);
}

test("active + ≤24h 核验 → STILL_OPEN（最近确认仍在招）", () => {
  const sigs = deriveOpportunitySignals(job(), FACTS, PROFILE, NOW);
  assert.ok(types(sigs).includes("STILL_OPEN"));
  assert.equal(primarySignal(sigs).label, "最近确认仍在招");
});

test("从未核验（enrich_checked_at=null）→ 不出 STILL_OPEN，出 CLOSED_OR_STALE「长时间未确认」", () => {
  const sigs = deriveOpportunitySignals(job({ enrich_checked_at: null }), FACTS, PROFILE, NOW);
  assert.ok(!types(sigs).includes("STILL_OPEN"));
  assert.equal(primarySignal(sigs).type, "CLOSED_OR_STALE");
  assert.equal(primarySignal(sigs).label, "长时间未确认");
  assert.equal(primarySignal(sigs).isCritical, false);
});

test("超 24h 核验（26h）→ 不 STILL_OPEN，长时间未确认", () => {
  const sigs = deriveOpportunitySignals(job({ enrich_checked_at: checkedHoursAgo(26) }), FACTS, PROFILE, NOW);
  assert.ok(!types(sigs).includes("STILL_OPEN"));
  assert.ok(types(sigs).includes("CLOSED_OR_STALE"));
});

test("status=expired + 被关注 → CLOSED_OR_STALE「可能已关闭」isCritical=true", () => {
  const sigs = deriveOpportunitySignals(job({ status: "expired" }), FACTS, PROFILE, NOW, { isWatched: true });
  const c = sigs.find((s) => s.type === "CLOSED_OR_STALE");
  assert.equal(c.label, "可能已关闭");
  assert.equal(c.isCritical, true);
  // 关闭岗不出 STILL_OPEN
  assert.ok(!types(sigs).includes("STILL_OPEN"));
});

test("status=expired 未被关注 → 可能已关闭，isCritical=false", () => {
  const sigs = deriveOpportunitySignals(job({ status: "expired" }), FACTS, PROFILE, NOW, { isWatched: false });
  assert.equal(sigs.find((s) => s.type === "CLOSED_OR_STALE").isCritical, false);
});

test("DEADLINE_SOON：社招窗口 7 天内触发，primary 高于 STILL_OPEN", () => {
  const sigs = deriveOpportunitySignals(job({ deadline: "2026-07-01" }), FACTS, PROFILE, NOW); // 3 天后
  assert.ok(types(sigs).includes("DEADLINE_SOON"));
  assert.equal(primarySignal(sigs).type, "DEADLINE_SOON"); // 优先级高于 STILL_OPEN
});

test("DEADLINE：社招 8 天不触发；校招 14 天内触发且 isCritical", () => {
  const far = deriveOpportunitySignals(job({ deadline: "2026-07-08" }), FACTS, PROFILE, NOW); // 10 天 > 7
  assert.ok(!types(far).includes("DEADLINE_SOON"));
  const campus = deriveOpportunitySignals(
    job({ deadline: "2026-07-08" }),
    { freshness: "verified", stageLabel: "校招" },
    { experienceStage: "校招" },
    NOW
  );
  const d = campus.find((s) => s.type === "DEADLINE_SOON");
  assert.ok(d, "校招 14 天窗内应触发");
  assert.equal(d.isCritical, true);
});

test("含糊截止（长期有效）不触发 DEADLINE_SOON", () => {
  const sigs = deriveOpportunitySignals(job({ deadline: "长期有效" }), FACTS, PROFILE, NOW);
  assert.ok(!types(sigs).includes("DEADLINE_SOON"));
});

test("NEWLY_DISCOVERED / COMPANY_MOMENTUM 当前不产出（依赖 job_events）", () => {
  const sigs = deriveOpportunitySignals(job({ posted_at: NOW.toISOString() }), FACTS, PROFILE, NOW);
  assert.ok(!types(sigs).includes("NEWLY_DISCOVERED"));
  assert.ok(!types(sigs).includes("COMPANY_MOMENTUM"));
});

test("每个 active 岗 signals.length ≥ 1", () => {
  assert.ok(deriveOpportunitySignals(job(), FACTS, PROFILE, NOW).length >= 1);
  assert.ok(deriveOpportunitySignals(job({ enrich_checked_at: null }), FACTS, PROFILE, NOW).length >= 1);
});
