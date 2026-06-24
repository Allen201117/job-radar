// v3 动态分区（04 spec §7 / 05 §4 §6）：按 primary signal × 强度落点；关键提醒置顶不截断；
// active 显拓展、passive 不显且门槛高；一岗只出现一次。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { groupOpportunities, resolveNoveltySince } = loadOpp("grouping");

let counter = 0;
// 构造一个已派生 signals 的 opportunity。signal 决定落点。
function opp(o = {}) {
  counter += 1;
  const sigType = o.signal ?? "STILL_OPEN";
  const isCritical = o.critical ?? false;
  return {
    job: { id: o.id || `j${counter}`, company: "C", title: "T", jd_url: `u${counter}`, status: "active" },
    score: o.score ?? 80,
    tier: o.tier ?? "high",
    reasons: [],
    freshness: o.freshness ?? "verified",
    firstSeenAt: o.firstSeenAt ?? "2026-05-01T00:00:00Z",
    lastSeenAt: "2026-06-23T00:00:00Z",
    userAction: null,
    viewed: false,
    isNew: false,
    exploreEligible: o.exploreEligible ?? false,
    signals: [{ type: sigType, label: "x", priority: 3, isCritical, evidence: {} }],
    intensity: "active",
    lastCheckedAt: null,
    officialPostedAt: null,
    deadlineAt: null,
  };
}

test("STILL_OPEN 高分进 main", () => {
  const { sections } = groupOpportunities([opp({ score: 80 })], { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.main.length, 1);
  assert.equal(sections.critical.length, 0);
});

test("关键提醒：isCritical 进 critical 区，不被 main 截断、置顶", () => {
  const crits = Array.from({ length: 12 }, () =>
    opp({ signal: "CLOSED_OR_STALE", critical: true, score: 100 })
  );
  const { sections, counts } = groupOpportunities(crits, { dailyLimit: 5, intensity: "active" });
  assert.equal(sections.critical.length, 12); // 不被 dailyLimit 截断
  assert.equal(counts.critical, 12);
});

test("CLOSED_OR_STALE 非关键（长时间未确认）进 waiting，封顶 8", () => {
  const stale = Array.from({ length: 15 }, () => opp({ signal: "CLOSED_OR_STALE", critical: false }));
  const { sections } = groupOpportunities(stale, { dailyLimit: 30, intensity: "active" });
  assert.equal(sections.main.length, 0);
  assert.equal(sections.waiting.length, 8);
});

test("active：score 30–门槛 + exploreEligible → explore（最多 5）", () => {
  const ex = Array.from({ length: 8 }, () => opp({ score: 40, exploreEligible: true }));
  const { sections } = groupOpportunities(ex, { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.explore.length, 5);
  assert.equal(sections.main.length, 0); // 40 < active 门槛 45
});

test("passive：不显拓展、门槛抬到 70、量收窄", () => {
  const opps = [
    ...Array.from({ length: 3 }, () => opp({ score: 80 })), // ≥70 进 main
    ...Array.from({ length: 5 }, () => opp({ score: 50, exploreEligible: true })), // 50<70 且 passive 无 explore → 丢弃
  ];
  const { sections } = groupOpportunities(opps, { dailyLimit: 20, intensity: "passive" });
  assert.equal(sections.main.length, 3);
  assert.equal(sections.explore.length, 0);
});

test("passive daily_limit 收窄到 ≤10", () => {
  const opps = Array.from({ length: 20 }, () => opp({ score: 90 }));
  const { sections } = groupOpportunities(opps, { dailyLimit: 30, intensity: "passive" });
  assert.equal(sections.main.length, 10);
});

test("一岗只出现一次（critical 优先于 main）", () => {
  const shared = opp({ id: "dup", signal: "DEADLINE_SOON", critical: true, score: 90 });
  const { sections } = groupOpportunities([shared], { dailyLimit: 20, intensity: "active" });
  const ids = [...sections.critical, ...sections.main, ...sections.explore, ...sections.waiting].map((o) => o.job.id);
  assert.equal(ids.length, new Set(ids).size);
  assert.equal(sections.critical.length, 1);
  assert.equal(sections.main.length, 0);
});

test("momentum 恒空（job_events 前不上）", () => {
  const { sections } = groupOpportunities([opp({ score: 80 })], { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.momentum.length, 0);
});

test("counts.by_signal 按 primary signal 计数", () => {
  const opps = [opp({ score: 80 }), opp({ score: 80 }), opp({ signal: "CLOSED_OR_STALE", critical: false })];
  const { counts } = groupOpportunities(opps, { dailyLimit: 20, intensity: "active" });
  assert.equal(counts.by_signal.STILL_OPEN, 2);
  assert.equal(counts.by_signal.CLOSED_OR_STALE, 1);
});

test("resolveNoveltySince：无上次访问 → now-72h；有则原样", () => {
  const now = new Date("2026-06-23T12:00:00.000Z");
  assert.equal(resolveNoveltySince(null, now), new Date(now.getTime() - 72 * 3600 * 1000).toISOString());
  assert.equal(resolveNoveltySince("2026-06-22T00:00:00.000Z", now), "2026-06-22T00:00:00.000Z");
});
