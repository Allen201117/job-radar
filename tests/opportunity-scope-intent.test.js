// 求职范围 vs 用户自己说过的地点（lib/opportunities/scope-intent.ts，2026-09-28）。
// 线上现象：「全都要」+ 成都 + 销售 + 无英文简历 → 美国岗压过同方向的成都岗（San Jose 80 分 vs 成都 71 分），
// 「海外」画像只召回 1 个岗也不回落国内。
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { loadOpp, loadTs } = require("./_load-ts");

const {
  targetCitiesAllDomestic,
  overseasLocationUnstated,
  canFallbackToDomestic,
  shouldTryDomesticFallback,
  mergeDomesticFallback,
  scopeFallbackNotice,
  THIN_OVERSEAS_FEED,
} = loadOpp("scope-intent");
const { computeMatchFacts, checkEligibility } = loadOpp("eligibility");
const { scoreOpportunity } = loadOpp("scoring");
const { buildRecallSql } = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"));

const NOW = new Date("2026-09-28T04:00:00.000Z");
const hoursAgo = (h) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();
const SOURCE = { id: "s1", crawl_method: "http", enabled: true };
const noAction = { primary: null, viewed: false };

function profile(over = {}) {
  return {
    userId: "u",
    jobScope: "domestic",
    targetRegions: [],
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
function job(over = {}) {
  return {
    id: "j",
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
const DEFAULT_REGIONS = ["US", "SG", "Remote"]; // 顶栏切换后服务端补的默认值（线上 18 个非国内画像全是它）
const allChengdu = (over = {}) =>
  profile({ jobScope: "all", targetRegions: DEFAULT_REGIONS, targetLocations: ["成都"], targetRoles: ["销售"], experienceStage: "社招", ...over });

const usJob = (over = {}) =>
  job({
    id: "us",
    title: "Senior Sales Engineer, Enterprise",
    company: "Zscaler",
    location: "San Jose, California, United States",
    country_code: "US",
    job_scope: "overseas",
    summary: "We are looking for a sales engineer with 5+ years of experience selling enterprise security. " + "y".repeat(200),
    ...over,
  });
const chengduJob = (over = {}) =>
  job({
    id: "cd",
    title: "大客户销售",
    company: "示例科技",
    location: "成都",
    country_code: "CN",
    job_scope: "domestic",
    summary: "负责成都区域大客户的开拓与维护，完成销售目标，维护客户关系。" + "好".repeat(200),
    ...over,
  });

function scored(j, p) {
  const f = computeMatchFacts(j, p, SOURCE, noAction, NOW);
  const e = checkEligibility(f);
  assert.equal(e.eligible, true, `${j.title} 应放行，实际 ${e.reason}`);
  return { facts: f, ...scoreOpportunity(f, e.degraded) };
}

// ---- 判定：目标城市是不是全在国内 ----

test("targetCitiesAllDomestic：全是大陆城市才算；空、含香港/新加坡/判不出的都不算", () => {
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: ["成都"] })), true);
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: ["北京", "上海", "深圳"] })), true);
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: [] })), false);
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: ["北京", "香港"] })), false);
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: ["上海", "新加坡"] })), false);
  assert.equal(targetCitiesAllDomestic(profile({ targetLocations: ["珠三角"] })), false);
});

test("overseasLocationUnstated：只管「全都要」；「海外」「国内」、没填城市、填了海外城市都不管", () => {
  assert.equal(overseasLocationUnstated(allChengdu()), true);
  assert.equal(overseasLocationUnstated(allChengdu({ jobScope: "overseas" })), false);
  assert.equal(overseasLocationUnstated(allChengdu({ jobScope: "domestic" })), false);
  assert.equal(overseasLocationUnstated(allChengdu({ targetLocations: [] })), false);
  assert.equal(overseasLocationUnstated(allChengdu({ targetLocations: ["成都", "新加坡"] })), false);
});

// ---- stage-2：地点三态 ----

test("全都要 + 城市全在国内：默认地区里的海外岗地点算 unknown（放行轻罚），卡片不再写「目标城市 US」", () => {
  const f = computeMatchFacts(usJob(), allChengdu(), SOURCE, noAction, NOW);
  assert.equal(f.location, "unknown");
  assert.equal(f.locationName, null);
  const { reasons } = scored(usJob(), allChengdu());
  assert.ok(!reasons.some((r) => r.label.startsWith("目标城市")), JSON.stringify(reasons));
  assert.equal(
    computeMatchFacts(usJob({ country_code: "SG", location: "Singapore" }), allChengdu(), SOURCE, noAction, NOW).location,
    "unknown",
  );
});

test("全都要 + 城市全在国内：默认地区以外的海外岗照旧拒（只改「算不算命中」，不改范围）", () => {
  const ca = usJob({ country_code: "CA", location: "Toronto, Canada" });
  assert.equal(computeMatchFacts(ca, allChengdu(), SOURCE, noAction, NOW).location, "mismatch");
});

test("全都要 + 城市全在国内：国内岗仍按城市判（成都 match、北京 mismatch）", () => {
  assert.equal(computeMatchFacts(chengduJob(), allChengdu(), SOURCE, noAction, NOW).location, "match");
  assert.equal(computeMatchFacts(chengduJob({ location: "北京" }), allChengdu(), SOURCE, noAction, NOW).location, "mismatch");
});

test("「海外」画像与城市含海外地名的「全都要」画像：默认地区命中照旧算 match（口径不变）", () => {
  assert.equal(computeMatchFacts(usJob(), allChengdu({ jobScope: "overseas" }), SOURCE, noAction, NOW).location, "match");
  assert.equal(
    computeMatchFacts(usJob(), allChengdu({ targetLocations: ["成都", "新加坡"] }), SOURCE, noAction, NOW).location,
    "match",
  );
});

test("复现线上排序：同方向的成都岗排在美国岗前面（改前 San Jose 80 > 成都 71）", () => {
  const us = scored(usJob(), allChengdu());
  const cd = scored(chengduJob(), allChengdu());
  assert.equal(us.facts.roleTier, "exact", "美国岗方向仍要命中（它照样会展示，只是不再压过本地岗）");
  assert.ok(cd.score > us.score, `成都 ${cd.score} 应高于 San Jose ${us.score}`);
});

// ---- 回落：什么时候补国内岗 ----

test("canFallbackToDomestic：非国内 + 城市全在国内 + 没有英文简历，三件都成立才行", () => {
  const p = allChengdu({ jobScope: "overseas" });
  assert.equal(canFallbackToDomestic(p, null), true);
  assert.equal(canFallbackToDomestic(p, { has_en_resume: false }), true);
  assert.equal(canFallbackToDomestic(p, { has_en_resume: true }), false);
  assert.equal(canFallbackToDomestic(allChengdu({ jobScope: "domestic" }), null), false);
  assert.equal(canFallbackToDomestic(allChengdu({ jobScope: "overseas", targetLocations: [] }), null), false);
  assert.equal(canFallbackToDomestic(allChengdu({ jobScope: "overseas", targetLocations: ["新加坡"] }), null), false);
});

test("shouldTryDomesticFallback：「海外」少于 10 个就补，「全都要」只在 0 个时补", () => {
  assert.equal(THIN_OVERSEAS_FEED, 10);
  const overseas = allChengdu({ jobScope: "overseas" });
  assert.equal(shouldTryDomesticFallback(overseas, null, 0), true);
  assert.equal(shouldTryDomesticFallback(overseas, null, 1), true);
  assert.equal(shouldTryDomesticFallback(overseas, null, 9), true);
  assert.equal(shouldTryDomesticFallback(overseas, null, 10), false);
  assert.equal(shouldTryDomesticFallback(overseas, { has_en_resume: true }, 1), false);
  const all = allChengdu();
  assert.equal(shouldTryDomesticFallback(all, null, 0), true);
  assert.equal(shouldTryDomesticFallback(all, null, 1), false);
});

// ---- 合并：原范围的岗在前，国内补在后 ----

const opp = (id, over = {}) => ({ job: { id }, signals: [{ type: "STILL_OPEN" }], score: 60, ...over });
function feed(sections, counts = {}) {
  const full = { critical: [], main: [], explore: [], momentum: [], waiting: [], ...sections };
  const total = Object.values(full).reduce((n, a) => n + a.length, 0);
  return {
    generated_at: NOW.toISOString(),
    profile_ready: true,
    candidate_capped: false,
    last_opened_at: null,
    stage: "实习",
    intensity: "active",
    counts: { total, critical: full.critical.length, main: full.main.length, by_signal: {}, ...counts },
    sections: full,
  };
}

test("mergeDomesticFallback：原范围的卡排最前，国内卡接在后面，关键提醒去重、不算进「找到几个」", () => {
  const alert = opp("saved-1", { signals: [{ type: "CLOSED_OR_STALE", isCritical: true }] });
  const scoped = feed({ critical: [alert], main: [opp("sg-1")] }, { screened: 1, filtered: { inactive: 0, mismatch: 1, low_score: 0, thin: 0 } });
  const domestic = feed(
    { critical: [alert], main: [opp("cn-1"), opp("cn-2")], explore: [opp("cn-3")] },
    { screened: 345, filtered: { inactive: 2, mismatch: 300, low_score: 5, thin: 1 } },
  );
  const out = mergeDomesticFallback(scoped, domestic, "overseas");
  assert.ok(out);
  assert.deepEqual(out.feed.sections.critical.map((o) => o.job.id), ["saved-1"]);
  assert.deepEqual(out.feed.sections.main.map((o) => o.job.id), ["sg-1", "cn-1", "cn-2"]);
  assert.deepEqual(out.feed.sections.explore.map((o) => o.job.id), ["cn-3"]);
  assert.deepEqual(out.fallback, { scope: "overseas", scopedCount: 1, addedCount: 3 });
  assert.equal(out.feed.counts.total, 5);
  assert.equal(out.feed.counts.main, 3);
  assert.equal(out.feed.counts.critical, 1);
  assert.deepEqual(out.feed.counts.by_signal, { CLOSED_OR_STALE: 1, STILL_OPEN: 4 });
  assert.equal(out.feed.counts.screened, 346);
  assert.deepEqual(out.feed.counts.filtered, { inactive: 2, mismatch: 301, low_score: 5, thin: 1 });
  // 输入不被改写（页面拿 null 时还要用原 feed）
  assert.deepEqual(scoped.sections.main.map((o) => o.job.id), ["sg-1"]);
});

test("mergeDomesticFallback：国内一个新岗都补不出来 → null（不回落、不出横幅）", () => {
  const alert = opp("saved-1", { signals: [{ type: "CLOSED_OR_STALE", isCritical: true }] });
  assert.equal(mergeDomesticFallback(feed({ main: [opp("sg-1")] }), feed({}), "overseas"), null);
  assert.equal(mergeDomesticFallback(feed({ critical: [alert] }), feed({ critical: [alert] }), "overseas"), null);
});

test("scopeFallbackNotice：0 个时说「按国内展示」，有几个时把两个数都说出来", () => {
  const zero = scopeFallbackNotice({ scope: "all", scopedCount: 0, addedCount: 12 });
  assert.match(zero, /全都要/);
  assert.match(zero, /按国内范围展示/);
  assert.match(zero, /英文简历/);
  const some = scopeFallbackNotice({ scope: "overseas", scopedCount: 1, addedCount: 8 });
  assert.match(some, /海外岗位里只找到 1 个对口机会/);
  assert.match(some, /补上了 8 个国内/);
});

// ---- stage-1：召回层内排序与 stage-2 同口径 ----

// 三档的地点排序表达式 `(case when A then 0 when B then 1 else 2 end)` → [A, B]。
// 按「(case when 」切段再在段内匹配，免得懒匹配跨过相邻的另一个 case 表达式。
function placeCases(sql) {
  return sql
    .split("(case when ")
    .slice(1)
    .map((seg) => seg.match(/^(.*?) then 0 when (.*?) then 1 else 2 end\)/))
    .filter(Boolean)
    .map((m) => [m[1], m[2]]);
}

test("召回：全都要 + 城市全在国内 → 层内城市在前、目标地区其次（否则城市岗被海外岗挤出层份额）", () => {
  const built = buildRecallSql(allChengdu({ targetCompanies: ["字节跳动"] }), "2026-09-21T00:00:00.000Z", 900);
  const cases = placeCases(built.sql).filter(([, second]) => second.startsWith("(job_scope = 'overseas'"));
  assert.ok(cases.length >= 3, `应有 role/company/cityNew 三层用到地点排序：${cases.length}`);
  for (const [first] of cases) assert.match(first, /^search_doc @@ to_tsquery/);
});

test("召回：「海外」画像、城市含海外地名的「全都要」画像 → 仍是目标地区在前（口径不变）", () => {
  for (const p of [allChengdu({ jobScope: "overseas" }), allChengdu({ targetLocations: ["成都", "新加坡"] })]) {
    const built = buildRecallSql(p, "2026-09-21T00:00:00.000Z", 900);
    const cases = placeCases(built.sql);
    assert.ok(cases.length > 0);
    for (const [first] of cases) assert.match(first, /^\(job_scope = 'overseas'/, JSON.stringify(p.targetLocations));
  }
});

test("/today 页接的是 scope-intent 的回落判定与合并，不再只认 0 岗", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "app", "today", "page.tsx"), "utf8");
  assert.match(src, /shouldTryDomesticFallback\(/);
  assert.match(src, /mergeDomesticFallback\(/);
  assert.match(src, /scopeFallbackNotice\(/);
  assert.doesNotMatch(src, /shouldFallbackToDomestic/);
});
