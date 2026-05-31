const assert = require("node:assert/strict");
const test = require("node:test");

const { mapApiSearchJobsToScoredJobs } = require("../lib/client-job-mapping");

test("maps API search jobs into action-safe scored jobs", () => {
  const jobs = mapApiSearchJobsToScoredJobs(
    [
      {
        id: "job-1",
        sourceId: "source-1",
        company: "Apple",
        title: "Data Engineer",
        location: "Cupertino",
        type: "社招",
        summary: "Build data products.",
        jdUrl: "https://jobs.apple.com/en-us/details/1/data-engineer",
        applyUrl: "https://jobs.apple.com/en-us/details/1/data-engineer",
        salary: "官网未披露",
        postedAt: "2026-05-01",
        firstSeenAt: "2026-05-02",
        match: { score: 55 },
      },
    ],
    "data",
    "2026-05-21T00:00:00.000Z",
  );

  assert.equal(jobs.length, 1);
  assert.equal(jobs[0].id, "job-1");
  assert.equal(jobs[0].source_id, "source-1");
  assert.equal(jobs[0].match_score, 55);
  assert.deepEqual(jobs[0].matched_keywords, ["data"]);
  assert.equal(jobs[0].jd_url, "https://jobs.apple.com/en-us/details/1/data-engineer");
});

test("drops API search jobs that cannot support user actions or official detail navigation", () => {
  const jobs = mapApiSearchJobsToScoredJobs(
    [
      {
        id: "",
        company: "Apple",
        title: "No persisted id",
        jdUrl: "https://jobs.apple.com/en-us/details/1/no-id",
      },
      {
        id: "job-2",
        company: "Apple",
        title: "No detail URL",
        jdUrl: "",
      },
    ],
    "data",
    "2026-05-21T00:00:00.000Z",
  );

  assert.deepEqual(jobs, []);
});
