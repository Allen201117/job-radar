const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { hydrateOpportunityJobs } = loadOpp("hydration");

function opportunity(id, summary = "short") {
  return {
    job: { id, summary, jd_url: "", salary_text: null },
    score: 80,
    tier: "high",
    reasons: [],
    freshness: "verified",
    firstSeenAt: null,
    lastSeenAt: null,
    userAction: null,
    viewed: false,
    isNew: false,
    exploreEligible: false,
  };
}

test("hydrateOpportunityJobs replaces selected recall rows with complete jobs", () => {
  const selected = opportunity("job-1");
  const sections = { new: [selected], priority: [], explore: [], aging: [] };
  const full = {
    id: "job-1",
    summary: "完整岗位正文",
    jd_url: "https://official.example/job-1",
    salary_text: "30-40K",
    deadline: "2026-07-01",
  };

  hydrateOpportunityJobs(sections, [full]);

  assert.equal(selected.job.summary, "完整岗位正文");
  assert.equal(selected.job.jd_url, "https://official.example/job-1");
  assert.equal(selected.job.salary_text, "30-40K");
  assert.equal(selected.job.deadline, "2026-07-01");
});

test("hydrateOpportunityJobs leaves a candidate unchanged when the full row is absent", () => {
  const selected = opportunity("missing", "candidate summary");
  const sections = { new: [selected], priority: [], explore: [], aging: [] };

  hydrateOpportunityJobs(sections, []);

  assert.equal(selected.job.summary, "candidate summary");
});
