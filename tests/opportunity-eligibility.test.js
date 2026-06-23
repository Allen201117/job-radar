const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { computeMatchFacts, checkEligibility } = loadOpp("eligibility");

const NOW = new Date("2026-06-23T12:00:00.000Z");
const hoursAgo = (h) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();

// 默认「全 na、合格、verified」的事实，逐项覆写测试 checkEligibility 的纯判定
function facts(over = {}) {
  return {
    active: true,
    summaryOk: true,
    sourceDisabled: false,
    excluded: false,
    freshness: "verified",
    roleTier: null,
    roleConstrained: false,
    roleMatchLabel: null,
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
    noveltyHours: 10,
    userAction: null,
    viewed: false,
    ...over,
  };
}

// ---- checkEligibility：硬门顺序、拒绝原因、degraded 累积 ----

test("status 非 active → reject inactive", () => {
  assert.deepEqual(checkEligibility(facts({ active: false })), { eligible: false, reason: "inactive" });
});

test("summary 过短 → reject thin_summary", () => {
  assert.deepEqual(checkEligibility(facts({ summaryOk: false })), { eligible: false, reason: "thin_summary" });
});

test("source 明确停用 → reject source_disabled", () => {
  assert.deepEqual(checkEligibility(facts({ sourceDisabled: true })), { eligible: false, reason: "source_disabled" });
});

test("freshness stale / unknown → reject stale", () => {
  assert.equal(checkEligibility(facts({ freshness: "stale" })).eligible, false);
  assert.equal(checkEligibility(facts({ freshness: "stale" })).reason, "stale");
  assert.equal(checkEligibility(facts({ freshness: "unknown" })).reason, "stale");
});

test("命中排除词 → reject excluded", () => {
  assert.deepEqual(checkEligibility(facts({ excluded: true })), { eligible: false, reason: "excluded" });
});

test("已 saved/ignored/applied → reject already_actioned（主队列）", () => {
  for (const a of ["saved", "ignored", "applied"]) {
    assert.deepEqual(checkEligibility(facts({ userAction: a })), { eligible: false, reason: "already_actioned" });
  }
});

test("仅 viewed 不拒绝", () => {
  const r = checkEligibility(facts({ viewed: true }));
  assert.equal(r.eligible, true);
});

test("用户设了方向：exact / related 放行，全不匹配拒绝", () => {
  assert.equal(checkEligibility(facts({ roleConstrained: true, roleTier: "exact" })).eligible, true);
  assert.equal(checkEligibility(facts({ roleConstrained: true, roleTier: "related" })).eligible, true);
  assert.deepEqual(checkEligibility(facts({ roleConstrained: true, roleTier: null })), {
    eligible: false,
    reason: "role_mismatch",
  });
});

test("用户没设方向（roleConstrained=false）→ 不跑方向门", () => {
  assert.equal(checkEligibility(facts({ roleConstrained: false, roleTier: null })).eligible, true);
});

test("location: unknown→degrade, mismatch→reject", () => {
  const deg = checkEligibility(facts({ location: "unknown" }));
  assert.equal(deg.eligible, true);
  assert.ok(deg.degraded.includes("location"));
  assert.deepEqual(checkEligibility(facts({ location: "mismatch" })), { eligible: false, reason: "location_mismatch" });
});

test("stage: unknown→degrade, mismatch→reject", () => {
  assert.ok(checkEligibility(facts({ stage: "unknown" })).degraded.includes("stage"));
  assert.equal(checkEligibility(facts({ stage: "mismatch" })).reason, "stage_mismatch");
});

test("education: unknown→degrade, mismatch→reject", () => {
  assert.ok(checkEligibility(facts({ education: "unknown" })).degraded.includes("education"));
  assert.equal(checkEligibility(facts({ education: "mismatch" })).reason, "education_mismatch");
});

test("industry: 命中目标公司则绕过行业拒绝（也不计 degrade）", () => {
  const r = checkEligibility(facts({ companyHit: true, industry: "mismatch" }));
  assert.equal(r.eligible, true);
  assert.ok(!r.degraded.includes("industry"));
  const r2 = checkEligibility(facts({ companyHit: true, industry: "unknown" }));
  assert.ok(!r2.degraded.includes("industry"));
});

test("industry: 未命中公司时 unknown→degrade, mismatch→reject", () => {
  assert.ok(checkEligibility(facts({ industry: "unknown" })).degraded.includes("industry"));
  assert.equal(checkEligibility(facts({ industry: "mismatch" })).reason, "industry_mismatch");
});

test("硬门按顺序返回第一个拒绝原因", () => {
  // active 在 summary 之前
  assert.equal(checkEligibility(facts({ active: false, summaryOk: false })).reason, "inactive");
  // excluded 在 role 之前
  assert.equal(checkEligibility(facts({ excluded: true, roleConstrained: true, roleTier: null })).reason, "excluded");
});

test("多个 degrade 一起累积", () => {
  const r = checkEligibility(facts({ location: "unknown", stage: "unknown", education: "unknown", industry: "unknown" }));
  assert.equal(r.eligible, true);
  assert.deepEqual([...r.degraded].sort(), ["education", "industry", "location", "stage"]);
});

// ---- computeMatchFacts：与真实 matcher 接线 ----

function job(over = {}) {
  return {
    id: "j1",
    source_id: "s1",
    company: "示例公司",
    title: "",
    location: null,
    job_type: null,
    summary: "x".repeat(80),
    jd_url: "https://e/job/1",
    apply_url: null,
    salary_text: null,
    posted_at: null,
    experience: null,
    education: null,
    deadline: null,
    first_seen_at: hoursAgo(10),
    last_seen_at: hoursAgo(5),
    status: "active",
    content_hash: null,
    created_at: "",
    ...over,
  };
}
function rprofile(over = {}) {
  return {
    userId: "u",
    targetRoles: [],
    targetKeywords: [],
    excludeKeywords: [],
    targetLocations: [],
    targetCompanies: [],
    targetIndustries: [],
    skills: [],
    experienceStage: "",
    seniority: null,
    highestEducation: null,
    dailyLimit: 20,
    ...over,
  };
}
const noAction = { primary: null, viewed: false };

test("computeMatchFacts: 方向 exact + roleMatchLabel", () => {
  const f = computeMatchFacts(job({ title: "产品经理" }), rprofile({ targetRoles: ["产品经理"] }), { id: "s1", crawl_method: "http", enabled: true }, noAction, NOW);
  assert.equal(f.roleTier, "exact");
  assert.equal(f.roleConstrained, true);
  assert.equal(f.roleMatchLabel, "产品经理");
});

test("computeMatchFacts: 不同职能 → roleTier null", () => {
  const f = computeMatchFacts(job({ title: "产品经理" }), rprofile({ targetRoles: ["后端工程师"] }), undefined, noAction, NOW);
  assert.equal(f.roleTier, null);
});

test("computeMatchFacts: 排除词命中（逐字对齐 crawler）", () => {
  const f = computeMatchFacts(job({ title: "销售经理" }), rprofile({ excludeKeywords: ["销售"] }), undefined, noAction, NOW);
  assert.equal(f.excluded, true);
});

test("computeMatchFacts: summary 去空白 ≥60 才算有效", () => {
  assert.equal(computeMatchFacts(job({ summary: "短" }), rprofile(), undefined, noAction, NOW).summaryOk, false);
  assert.equal(computeMatchFacts(job({ summary: "y".repeat(60) }), rprofile(), undefined, noAction, NOW).summaryOk, true);
  assert.equal(computeMatchFacts(job({ summary: "   " + "y".repeat(59) }), rprofile(), undefined, noAction, NOW).summaryOk, false);
});

test("computeMatchFacts: location 三态 + na", () => {
  assert.equal(computeMatchFacts(job({ location: "上海" }), rprofile({ targetLocations: ["上海"] }), undefined, noAction, NOW).location, "match");
  assert.equal(computeMatchFacts(job({ location: null }), rprofile({ targetLocations: ["上海"] }), undefined, noAction, NOW).location, "unknown");
  assert.equal(computeMatchFacts(job({ location: "北京" }), rprofile({ targetLocations: ["上海"] }), undefined, noAction, NOW).location, "mismatch");
  assert.equal(computeMatchFacts(job({ location: "北京" }), rprofile({ targetLocations: [] }), undefined, noAction, NOW).location, "na");
});

test("computeMatchFacts: freshness 接 source crawl_method + last_seen", () => {
  assert.equal(computeMatchFacts(job({ last_seen_at: hoursAgo(17) }), rprofile(), { id: "s1", crawl_method: "http", enabled: true }, noAction, NOW).freshness, "verified");
  assert.equal(computeMatchFacts(job({ last_seen_at: hoursAgo(40) }), rprofile(), { id: "s1", crawl_method: "http", enabled: true }, noAction, NOW).freshness, "stale");
});

test("computeMatchFacts: sourceDisabled / active / novelty / 公司命中", () => {
  assert.equal(computeMatchFacts(job(), rprofile(), { id: "s1", crawl_method: "http", enabled: false }, noAction, NOW).sourceDisabled, true);
  assert.equal(computeMatchFacts(job(), rprofile(), undefined, noAction, NOW).sourceDisabled, false);
  assert.equal(computeMatchFacts(job({ status: "expired" }), rprofile(), undefined, noAction, NOW).active, false);
  assert.equal(Math.round(computeMatchFacts(job({ first_seen_at: hoursAgo(10) }), rprofile(), undefined, noAction, NOW).noveltyHours), 10);
  const f = computeMatchFacts(job({ company: "字节跳动" }), rprofile({ targetCompanies: ["字节跳动"] }), undefined, noAction, NOW);
  assert.equal(f.companyHit, true);
  assert.equal(f.companyName, "字节跳动");
});

test("computeMatchFacts: 公司命中用 normalizeCompany exact（剥尾缀命中、子串不误命中）", () => {
  // 剥「有限公司」尾缀后命中
  assert.equal(
    computeMatchFacts(job({ company: "字节跳动有限公司" }), rprofile({ targetCompanies: ["字节跳动"] }), undefined, noAction, NOW).companyHit,
    true,
  );
  // 子串不再误命中：目标"字节" ≠ 岗位"字节跳动"
  assert.equal(
    computeMatchFacts(job({ company: "字节跳动" }), rprofile({ targetCompanies: ["字节"] }), undefined, noAction, NOW).companyHit,
    false,
  );
  // 不同公司不合并
  assert.equal(
    computeMatchFacts(job({ company: "腾讯" }), rprofile({ targetCompanies: ["字节跳动"] }), undefined, noAction, NOW).companyHit,
    false,
  );
});

test("computeMatchFacts: 主动作 + viewed 透传", () => {
  const f = computeMatchFacts(job(), rprofile(), undefined, { primary: "saved", viewed: true }, NOW);
  assert.equal(f.userAction, "saved");
  assert.equal(f.viewed, true);
});
