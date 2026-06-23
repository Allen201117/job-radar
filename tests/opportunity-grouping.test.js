const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { groupOpportunities, resolveNoveltySince } = loadOpp("grouping");

const SINCE = "2026-06-01T00:00:00.000Z";
const NEW_AT = "2026-06-20T00:00:00.000Z"; // > SINCE → isNew
const OLD_AT = "2026-05-01T00:00:00.000Z"; // <= SINCE → not new

let counter = 0;
function opp(o = {}) {
  counter += 1;
  const firstSeenAt = o.firstSeenAt ?? OLD_AT;
  return {
    job: { id: o.id || `j${counter}`, company: "C", title: "T", location: null, jd_url: `u${counter}`, summary: "", status: "active", first_seen_at: firstSeenAt, last_seen_at: "2026-06-23T00:00:00.000Z", source_id: "s" },
    score: o.score ?? 50,
    tier: o.tier ?? "related",
    reasons: [],
    freshness: o.freshness ?? "verified",
    firstSeenAt,
    lastSeenAt: "2026-06-23T00:00:00.000Z",
    userAction: null,
    viewed: o.viewed ?? false,
    isNew: false,
    exploreEligible: o.exploreEligible ?? false,
  };
}

test("A 新出现上限 10；counts.new_since_last_open 反映全部新增", () => {
  const opps = Array.from({ length: 12 }, () => opp({ score: 80, freshness: "verified", firstSeenAt: NEW_AT }));
  const { sections, counts } = groupOpportunities(opps, 20, SINCE);
  assert.equal(sections.new.length, 10);
  assert.equal(counts.new_since_last_open, 12);
});

test("B 高匹配填充到 dailyLimit", () => {
  const news = Array.from({ length: 3 }, () => opp({ score: 80, firstSeenAt: NEW_AT }));
  const olds = Array.from({ length: 10 }, () => opp({ score: 75, firstSeenAt: OLD_AT }));
  const { sections } = groupOpportunities([...news, ...olds], 8, SINCE);
  assert.equal(sections.new.length, 3);
  assert.equal(sections.priority.length, 5); // 3 + 5 = 8 = dailyLimit
});

test("C 拓展最多 5，且仅当 A+B 未满", () => {
  const opps = Array.from({ length: 8 }, () => opp({ score: 40, exploreEligible: true, firstSeenAt: OLD_AT }));
  const { sections } = groupOpportunities(opps, 20, SINCE);
  assert.equal(sections.new.length, 0);
  assert.equal(sections.priority.length, 0);
  assert.equal(sections.explore.length, 5);
});

test("主队列 A+B+C 不超过 dailyLimit", () => {
  const opps = [
    ...Array.from({ length: 4 }, () => opp({ score: 90, firstSeenAt: NEW_AT })),
    ...Array.from({ length: 10 }, () => opp({ score: 75, firstSeenAt: OLD_AT })),
    ...Array.from({ length: 10 }, () => opp({ score: 40, exploreEligible: true })),
  ];
  const { sections } = groupOpportunities(opps, 5, SINCE);
  assert.ok(sections.new.length + sections.priority.length + sections.explore.length <= 5);
});

test("D aging 仅在 verified 总数<5 时出现，最多 3", () => {
  const fewVerified = [
    ...Array.from({ length: 3 }, () => opp({ score: 80, freshness: "verified", firstSeenAt: NEW_AT })),
    ...Array.from({ length: 5 }, () => opp({ score: 60, freshness: "aging" })),
  ];
  const r1 = groupOpportunities(fewVerified, 20, SINCE);
  assert.equal(r1.sections.aging.length, 3);

  const manyVerified = [
    ...Array.from({ length: 6 }, () => opp({ score: 80, freshness: "verified", firstSeenAt: NEW_AT })),
    ...Array.from({ length: 5 }, () => opp({ score: 60, freshness: "aging" })),
  ];
  const r2 = groupOpportunities(manyVerified, 20, SINCE);
  assert.equal(r2.sections.aging.length, 0);
});

test("各 section 之间不重复", () => {
  const opps = [
    ...Array.from({ length: 4 }, () => opp({ score: 90, firstSeenAt: NEW_AT })),
    ...Array.from({ length: 6 }, () => opp({ score: 75, firstSeenAt: OLD_AT })),
    ...Array.from({ length: 6 }, () => opp({ score: 40, exploreEligible: true })),
  ];
  const { sections } = groupOpportunities(opps, 20, SINCE);
  const ids = [...sections.new, ...sections.priority, ...sections.explore, ...sections.aging].map((o) => o.job.id);
  assert.equal(ids.length, new Set(ids).size);
});

test("resolveNoveltySince：无上次访问 → now-72h；有则原样", () => {
  const now = new Date("2026-06-23T12:00:00.000Z");
  assert.equal(resolveNoveltySince(null, now), new Date(now.getTime() - 72 * 3600 * 1000).toISOString());
  assert.equal(resolveNoveltySince("2026-06-22T00:00:00.000Z", now), "2026-06-22T00:00:00.000Z");
});

test("isNew 按 first_seen_at > noveltySince 计算", () => {
  const opps = [opp({ score: 80, firstSeenAt: NEW_AT }), opp({ score: 80, firstSeenAt: OLD_AT })];
  const { sections } = groupOpportunities(opps, 20, SINCE);
  // 新的进 A，旧的（score>=70）进 B
  assert.equal(sections.new.length, 1);
  assert.equal(sections.new[0].firstSeenAt, NEW_AT);
  assert.equal(sections.new[0].isNew, true);
  assert.equal(sections.priority.length, 1);
  assert.equal(sections.priority[0].isNew, false);
});

test("不用低分岗位填满：score 30-44 但 exploreEligible=false 不进任何 section", () => {
  const opps = Array.from({ length: 8 }, () => opp({ score: 40, exploreEligible: false }));
  const { sections } = groupOpportunities(opps, 20, SINCE);
  assert.equal(sections.new.length + sections.priority.length + sections.explore.length, 0);
});
