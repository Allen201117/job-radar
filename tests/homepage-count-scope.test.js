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
  // 列表计数按用户求职范围收窄；库存计数是全局合计。两者不可互换。
  assert.match(jobsPage, /countActiveForScope\(scopePrefs\)/);
  assert.match(jobsPage, /countValidActive\(\)/);
  assert.match(jobsPage, /<JobLibraryStat initialTotal=\{libraryTotal\} \/>/);
  assert.ok(!jobsPage.includes("<JobLibraryStat initialTotal={total} />"));
});

// 首屏三件套走 unstable_cache 跨用户共享，**cache key 必须带上所有影响结果集的字段**。
// 漏掉任何一项 = 把 A 用户求职范围的岗位/计数发给 B 用户（静默串味，不报错）。
// 影响结果集的就是 appendJobScopeWhere 读的那两项（lib/job-scope.ts）：job_scope + target_regions。
test("jobs 首屏缓存的 key 覆盖全部影响结果集的偏好字段", () => {
  const call = jobsPage.match(/loadJobsFirstScreen\(([\s\S]*?)\);/);
  assert.ok(call, "应经 loadJobsFirstScreen 取首屏");
  assert.match(call[1], /job_scope/, "cache key 必须带 job_scope");
  assert.match(call[1], /target_regions/, "cache key 必须带 target_regions");
  // 缓存内容不得掺入任何用户私有数据（否则跨用户共享会泄露）。
  const body = jobsPage.match(/const loadJobsFirstScreen = unstable_cache\(([\s\S]*?)\n\);/);
  assert.ok(body, "应能取到缓存函数体");
  for (const leak of ["user_id", "actions", "job_actions", "candidate_profiles", "target_keywords"]) {
    assert.ok(!body[1].includes(leak), `缓存体内不得出现用户私有字段 ${leak}`);
  }
});
