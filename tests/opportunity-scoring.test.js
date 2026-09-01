const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { scoreOpportunity, scoreTier, buildReasons } = loadOpp("scoring");

function facts(over = {}) {
  return {
    active: true,
    summaryOk: true,
    summaryLong: false,
    sourceDisabled: false,
    excluded: false,
    freshness: "verified",
    roleTier: null,
    roleConstrained: false,
    roleMatchLabel: null,
    roleTitleHit: false,
    companyHit: false,
    companyName: null,
    location: "na",
    locationName: null,
    stage: "na",
    stageLabel: null,
    education: "na",
    industry: "na",
    industryName: null,
    skillsHit: [],
    noveltyHours: 1000, // 默认很旧，不加新鲜分
    userAction: null,
    viewed: false,
    ...over,
  };
}

test("方向分三档：标题命中 40 > 仅正文命中 30 > 相关 22", () => {
  // 三档是为了打散并列——旧的两档让真实画像的 TOP30 里出现 28 个同分岗位，排序退化成随机。
  const titleHit = scoreOpportunity(facts({ roleTier: "exact", roleTitleHit: true }), []).score;
  const bodyOnly = scoreOpportunity(facts({ roleTier: "exact" }), []).score;
  const related = scoreOpportunity(facts({ roleTier: "related" }), []).score;
  assert.equal(titleHit, 40);
  assert.equal(bodyOnly, 30);
  assert.equal(related, 22);
  assert.ok(titleHit > bodyOnly && bodyOnly > related);
});

test("目标公司命中 +15", () => {
  assert.equal(scoreOpportunity(facts({ companyHit: true }), []).score, 15);
});

test("城市 / 阶段 / 行业 三态计分", () => {
  assert.equal(scoreOpportunity(facts({ location: "match" }), []).score, 15);
  assert.equal(scoreOpportunity(facts({ location: "unknown" }), []).score, 3);
  assert.equal(scoreOpportunity(facts({ stage: "match" }), []).score, 10);
  assert.equal(scoreOpportunity(facts({ stage: "unknown" }), []).score, 3);
  assert.equal(scoreOpportunity(facts({ industry: "match" }), []).score, 10);
  assert.equal(scoreOpportunity(facts({ industry: "unknown" }), []).score, 2);
});

test("技能命中每项 +3，封顶 +15", () => {
  assert.equal(scoreOpportunity(facts({ skillsHit: ["a", "b"] }), []).score, 6);
  assert.equal(scoreOpportunity(facts({ skillsHit: ["a", "b", "c", "d", "e", "f"] }), []).score, 15);
});

test("新鲜度连续衰减：24h 内满分 10，之后线性降到第 7 天归零", () => {
  // 连续而非三档：三档意味着同档内这一项完全同分，是排序并列的另一个大来源。
  assert.equal(scoreOpportunity(facts({ noveltyHours: 10 }), []).score, 10);
  assert.equal(scoreOpportunity(facts({ noveltyHours: 24 }), []).score, 10);
  const d2 = scoreOpportunity(facts({ noveltyHours: 48 }), []).score;
  const d3 = scoreOpportunity(facts({ noveltyHours: 72 }), []).score;
  const d5 = scoreOpportunity(facts({ noveltyHours: 120 }), []).score;
  assert.ok(d2 > d3 && d3 > d5 && d5 > 0, `应严格递减: ${d2} > ${d3} > ${d5} > 0`);
  assert.equal(d2, 8.3); // (7-2)/6*10
  assert.equal(scoreOpportunity(facts({ noveltyHours: 7 * 24 }), []).score, 0);
  assert.equal(scoreOpportunity(facts({ noveltyHours: 1000 }), []).score, 0);
  assert.equal(scoreOpportunity(facts({ noveltyHours: null }), []).score, 0);
});

test("summary≥200 且 verified +5；非 verified 不加", () => {
  assert.equal(scoreOpportunity(facts({ summaryLong: true, freshness: "verified" }), []).score, 5);
  assert.equal(scoreOpportunity(facts({ summaryLong: true, freshness: "aging" }), []).score, 0);
});

test("已 viewed 未决定 -8（clamp 不为负）", () => {
  assert.equal(scoreOpportunity(facts({ roleTier: "exact", viewed: true }), []).score, 22); // 30-8
  assert.equal(scoreOpportunity(facts({ viewed: true }), []).score, 0); // 0-8 → clamp 0
});

test("degraded 每项 -2，最低 -8", () => {
  assert.equal(scoreOpportunity(facts({ roleTier: "exact" }), ["location"]).score, 28); // 30-2
  assert.equal(scoreOpportunity(facts({ roleTier: "exact" }), ["location", "stage"]).score, 26); // 30-4
  // 5 项也只扣 8（实际最多 4 项，验证 floor）
  assert.equal(scoreOpportunity(facts({ roleTier: "exact" }), ["a", "b", "c", "d", "e"]).score, 22); // 30-8
});

test("score clamp 0–100", () => {
  const big = facts({ roleTier: "exact", roleTitleHit: true, companyHit: true, location: "match", stage: "match", industry: "match", skillsHit: ["a", "b", "c", "d", "e"], noveltyHours: 1, summaryLong: true });
  // 40+15+15+10+10+15+10+5 = 120 → clamp 100
  assert.equal(scoreOpportunity(big, []).score, 100);
  assert.equal(scoreOpportunity(facts({ viewed: true }), ["a", "b", "c", "d"]).score, 0);
});

test("scoreTier 边界 29/30/44/45/69/70/100", () => {
  assert.equal(scoreTier(29), null);
  assert.equal(scoreTier(30), "explore");
  assert.equal(scoreTier(44), "explore");
  assert.equal(scoreTier(45), "related");
  assert.equal(scoreTier(69), "related");
  assert.equal(scoreTier(70), "high");
  assert.equal(scoreTier(100), "high");
});

// ---- 原因（§6.7）----

test("reasons：只展示正向、顺序 role→location→stage→industry→company→skill→freshness、最多 4", () => {
  const f = facts({
    roleTier: "exact",
    roleMatchLabel: "产品经理",
    location: "match",
    locationName: "上海",
    stage: "match",
    stageLabel: "社招",
    industry: "match",
    industryName: "互联网/科技",
    companyHit: true,
    companyName: "字节跳动",
    skillsHit: ["SQL"],
    noveltyHours: 5,
  });
  const reasons = buildReasons(f);
  assert.equal(reasons.length, 4); // 截断到 4
  assert.deepEqual(
    reasons.map((r) => r.type),
    ["role", "location", "stage", "industry"]
  );
  assert.match(reasons[0].label, /产品经理/);
  assert.match(reasons[1].label, /上海/);
});

test("reasons：unknown 不作为正向理由；freshness 用绝对可信表述", () => {
  const f = facts({ roleTier: "exact", roleMatchLabel: "数据分析", location: "unknown", noveltyHours: 5 });
  const reasons = buildReasons(f);
  // location unknown 不出现
  assert.ok(!reasons.some((r) => r.type === "location"));
  // 24h 内 → 今天首次发现
  const fr = reasons.find((r) => r.type === "freshness");
  assert.equal(fr.label, "今天首次发现");
});

test("reasons：非新但 verified → 已确认仍在招", () => {
  const f = facts({ companyHit: true, companyName: "X", noveltyHours: 1000, freshness: "verified" });
  const fr = buildReasons(f).find((r) => r.type === "freshness");
  assert.equal(fr.label, "已确认仍在招");
});
