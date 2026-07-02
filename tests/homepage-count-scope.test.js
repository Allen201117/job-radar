const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const statsRoute = fs.readFileSync(
  path.resolve(__dirname, "../app/api/jobs/stats/route.ts"),
  "utf8",
);
const jobsPage = fs.readFileSync(
  path.resolve(__dirname, "../app/jobs/page.tsx"),
  "utf8",
);

test("jobs stats API uses combined valid-active count without job scope", () => {
  assert.match(statsRoute, /countValidActive\(\)/);
  assert.match(statsRoute, /rpc\("count_valid_active_jobs"\)/);
  assert.ok(!statsRoute.includes("countActiveForScope"), "stats route must not use scoped list count");
  assert.ok(!statsRoute.includes("job_scope"), "stats route must not read job_scope");
});

test("jobs page passes combined libraryTotal to JobLibraryStat", () => {
  assert.match(jobsPage, /countActiveForScope\(preferences\)/);
  assert.match(jobsPage, /countValidActive\(\)/);
  assert.match(jobsPage, /<JobLibraryStat initialTotal=\{libraryTotal\} \/>/);
  assert.ok(!jobsPage.includes("<JobLibraryStat initialTotal={total} />"));
});
