// Offline review counterexamples. No network, credentials or database access.
const path = require("node:path");
const assert = require("node:assert/strict");

const repo = path.resolve(__dirname, "../../..");
process.chdir(repo);
const { loadTs } = require(path.join(repo, "tests/_load-ts.js"));
const { buildRecallSql } = loadTs(path.join(repo, "lib/jobs-store/opportunities.ts"));
const { computeMatchFacts, checkEligibility } = loadTs(path.join(repo, "lib/opportunities/eligibility.ts"));
const { jobFilterMatch } = loadTs(path.join(repo, "lib/job-filter.ts"));

function makeJob(overrides) {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    title: "占位岗位",
    company: "示例公司",
    location: "北京",
    job_type: null,
    summary: "岗位职责清晰，面向对应方向候选人。".repeat(8),
    jd_url: "https://jobs.example.com/position/1",
    status: "active",
    source_id: null,
    first_seen_at: "2026-09-05T00:00:00.000Z",
    last_seen_at: "2026-09-05T00:00:00.000Z",
    match_score: 0,
    hidden_reason: null,
    user_action: null,
    ...overrides,
  };
}

function makeProfile(overrides) {
  return {
    targetRoles: [],
    manualTargetRoles: [],
    skills: [],
    industries: [],
    targetLocations: [],
    targetCompanies: [],
    experienceStage: "",
    targetKeywords: [],
    excludeKeywords: [],
    minSalary: null,
    jobScope: "domestic",
    ...overrides,
  };
}

const campusProfile = makeProfile({ targetRoles: ["管培生"], experienceStage: "校招" });
const campusJob = makeJob({
  title: "管培生",
  recruitment_category: "校招",
  recruitment_explicit: true,
});
const now = new Date("2026-09-06T00:00:00.000Z");
const action = { primary: null, viewed: false };
const campusFacts = computeMatchFacts(campusJob, campusProfile, undefined, action, now);
const campusEligibility = checkEligibility(campusFacts);
const campusSql = buildRecallSql(campusProfile, "2026-08-30T00:00:00.000Z", 1800, []);
const campusStagePatterns = campusSql.params.flatMap((v) =>
  Array.isArray(v) ? v.filter((x) => typeof x === "string" && x.startsWith("%")) : [],
);
const campusRecallFieldText = `${campusJob.title} ${campusJob.job_type || ""} ${campusJob.jd_url}`.toLowerCase();
const campusStageSqlCouldMatch = campusStagePatterns.some((p) =>
  campusRecallFieldText.includes(p.slice(1, -1).toLowerCase()),
);

const bodyProfile = makeProfile({ targetRoles: ["产品经理"] });
const bodyJob = makeJob({
  title: "战略项目岗",
  summary: "负责产品经理相关工作，包括用户研究、需求分析和产品规划。".repeat(6),
});
const bodyFacts = computeMatchFacts(bodyJob, bodyProfile, undefined, action, now);
const bodyEligibility = checkEligibility(bodyFacts);
const bodySearchDoc = [bodyJob.title, bodyJob.company, bodyJob.location, bodyJob.job_type || ""]
  .join(" ")
  .toLowerCase();
const bodyFilter = jobFilterMatch(bodyJob, {
  keyword: "产品经理",
  locations: [],
  companies: [],
  jobTypes: [],
  minScore: 0,
  action: "all",
  recruitmentTypes: [],
  jobScope: "all",
});

assert.equal(campusFacts.stage, "match");
assert.equal(campusEligibility.eligible, true);
assert.equal(campusStageSqlCouldMatch, false);
assert.equal(bodyEligibility.eligible, true);
assert.equal(bodySearchDoc.includes("产品经理"), false);
console.log(JSON.stringify({
  campus: {
    computedStage: campusFacts.stage,
    roleTier: campusFacts.roleTier,
    eligible: campusEligibility.eligible,
    materializedCategoryOnlyUsedByNegativeSeasonGuard:
      campusSql.sql.includes("not (recruitment_category") &&
      !campusSql.sql.includes("recruitment_explicit and recruitment_category = '校招'"),
    stagePrefilterCouldMatchRecallFields: campusStageSqlCouldMatch,
  },
  bodyRole: {
    roleTier: bodyFacts.roleTier,
    eligible: bodyEligibility.eligible,
    jobsFilterAcceptsKeyword: bodyFilter,
    materializedSearchDocContainsRole: bodySearchDoc.includes("产品经理"),
  },
}, null, 2));
