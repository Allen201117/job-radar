const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadRoute, resolvedQuery } = require("./route-test-utils");

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");

const jobLibraryStat = read("../components/JobLibraryStat.tsx");
const tagInput = read("../components/TagInput.tsx");
const preferenceForm = read("../components/PreferenceForm.tsx");
const resumeProfilePanel = read("../components/ResumeProfilePanel.tsx");
const navbar = read("../components/Navbar.tsx");
const appliedPage = read("../app/applied/page.tsx");

function tagInputCalls(source) {
  return source.match(/<TagInput\b[\s\S]*?\/>/g) ?? [];
}

function assertTagInputLabels(source, expectedCount, context, expectedFragments) {
  const calls = tagInputCalls(source);
  assert.equal(calls.length, expectedCount, `${context} TagInput call count changed; audit every call`);
  calls.forEach((call, index) => {
    assert.match(call, /ariaLabel=["'][^"']+["']/, `${context} TagInput #${index + 1} needs ariaLabel`);
  });

  const labels = calls.map((call) => call.match(/ariaLabel=["']([^"']+)["']/)?.[1]);
  assert.equal(new Set(labels).size, expectedCount, `${context} aria labels must identify each business field`);
  for (const expected of expectedFragments) {
    assert.ok(labels.some((label) => label.includes(expected)), `missing ${context} aria label: ${expected}`);
  }
}

function createStatsSupabase({ rpcResult, recentResult, sourcesResult } = {}) {
  return {
    rpc: async () => rpcResult ?? { data: 12, error: null },
    from(table) {
      if (table === "jobs") return resolvedQuery(recentResult ?? { count: 8, error: null });
      if (table === "sources") return resolvedQuery(sourcesResult ?? { count: 5, error: null });
      throw new Error(`unexpected table: ${table}`);
    },
  };
}

function loadStatsRoute({ storeEnabled = false, supabase, countValidActive, countRecentActive } = {}) {
  return loadRoute("app/api/jobs/stats/route.ts", {
    "@/lib/auth": {
      createServerSupabase: async () => supabase ?? createStatsSupabase(),
    },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => storeEnabled,
      countValidActive: countValidActive ?? (async () => 12),
      countRecentActive: countRecentActive ?? (async () => 8),
    },
  });
}

async function assertUncachedStatsFailure(response) {
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { ok: false, error: "stats_failed" });
  const cacheControl = response.headers.get("cache-control");
  assert.equal(cacheControl, "no-store");
  assert.ok(!cacheControl.includes("public"));
  assert.ok(!cacheControl.includes("s-maxage"));
}

test("jobs stats GET returns its real body with a one-minute CDN cache policy", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    supabase: createStatsSupabase({ sourcesResult: { count: 5, error: null } }),
    countValidActive: async () => 12,
    countRecentActive: async () => 8,
  });

  const response = await route.GET();

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    validActive: 12,
    recent24h: 8,
    sources: 5,
  });
  assert.equal(
    response.headers.get("cache-control"),
    "public, s-maxage=60, stale-while-revalidate=300",
  );
});

for (const scenario of [
  { name: "valid-active RPC", key: "rpcResult" },
  { name: "recent jobs query", key: "recentResult" },
  { name: "sources query", key: "sourcesResult" },
]) {
  test(`jobs stats returns an uncached 500 when the Supabase ${scenario.name} fails`, async () => {
    const supabase = createStatsSupabase({
      [scenario.key]: { data: null, count: null, error: new Error(`${scenario.name} failed`) },
    });
    const route = loadStatsRoute({ supabase });

    await assertUncachedStatsFailure(await route.GET());
  });
}

test("jobs stats returns an uncached 500 when the HK jobs store rejects", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    countValidActive: async () => {
      throw new Error("jobs store failed");
    },
  });

  await assertUncachedStatsFailure(await route.GET());
});

test("jobs stats returns an uncached 500 when the HK recent-active count rejects", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    countRecentActive: async () => {
      throw new Error("recent jobs store failed");
    },
  });

  await assertUncachedStatsFailure(await route.GET());
});

test("job library stats wires the tested lifecycle helpers and keeps manual refresh accessible", () => {
  assert.match(
    jobLibraryStat,
    /import\s+\{\s*createJobStatsRefresher\s*,\s*installVisiblePolling\s*\}\s+from\s+["']@\/lib\/job-stats-refresh["']/,
  );
  assert.match(jobLibraryStat, /const\s+POLL_INTERVAL_MS\s*=\s*(?:60_000|60000)\s*;/);
  assert.match(jobLibraryStat, /createJobStatsRefresher\s*\(\s*\{/);
  assert.match(jobLibraryStat, /installVisiblePolling\s*\(\s*\{/);
  assert.match(jobLibraryStat, /documentLike:\s*document/);
  assert.match(jobLibraryStat, /windowLike:\s*window/);
  assert.match(jobLibraryStat, /intervalMs:\s*POLL_INTERVAL_MS/);
  assert.match(jobLibraryStat, /cleanupPolling\s*\(\s*\)/);
  assert.match(jobLibraryStat, /refresher\.dispose\s*\(\s*\)/);
  assert.match(jobLibraryStat, /aria-label=["']立即刷新岗位库计数["']/);
  assert.match(jobLibraryStat, /轮询间隔\s*\{POLL_INTERVAL_MS\s*\/\s*1000\}s/);
  assert.doesNotMatch(jobLibraryStat, />\s*轮询间隔 12s\s*</);
  assert.doesNotMatch(jobLibraryStat, /fetch\(\s*["']\/api\/jobs\/stats["']\s*,\s*\{[\s\S]*?cache\s*:\s*["']no-store["']/);
  const statusText = jobLibraryStat.match(/const\s+statusText\s*=([\s\S]*?);/)?.[1];
  assert.ok(statusText, "could not locate statusText");
  assert.ok(statusText.includes("定时刷新"), "status copy must describe scheduled refresh");
  assert.ok(!statusText.includes("实时刷新"), "status copy must not claim real-time refresh");
});

test("TagInput requires and applies a business-specific accessible name", () => {
  const propsBody = tagInput.match(/interface\s+Props\s*\{([^}]*)\}/)?.[1];
  assert.ok(propsBody, "could not locate TagInput Props");
  assert.match(propsBody, /ariaLabel\s*:\s*string\s*;/);
  assert.match(tagInput, /function\s+TagInput\s*\(\s*\{[\s\S]*?ariaLabel[\s\S]*?\}\s*:\s*Props\s*\)/);
  assert.match(tagInput, /<input\b[\s\S]*?aria-label=\{ariaLabel\}[\s\S]*?\/>/);
});

test("all six preference TagInput calls have distinct explicit aria labels", () => {
  assertTagInputLabels(
    preferenceForm,
    6,
    "PreferenceForm",
    ["目标城市", "目标岗位", "关注公司", "命中关键词", "排除关键词", "目标行业"],
  );
});

test("all four resume TagInput calls have distinct explicit aria labels", () => {
  assertTagInputLabels(
    resumeProfilePanel,
    4,
    "ResumeProfilePanel",
    ["目标岗位", "期望城市", "技能", "行业"],
  );
});

test("mobile menu backdrop is hidden, non-semantic, and still closes the menu", () => {
  const backdrop = navbar.match(
    /<(?:button|div)\b(?:(?!<(?:button|div)\b)[\s\S])*?className=["'][^"']*fixed inset-0 top-14[^"']*["'][\s\S]*?\/>/,
  )?.[0];

  assert.ok(backdrop, "could not locate the mobile menu backdrop");
  assert.match(backdrop, /^<div\b/);
  assert.match(backdrop, /aria-hidden=["']true["']/);
  assert.match(backdrop, /onClick=\{\(\)\s*=>\s*setMenuOpen\(false\)\}/);
  assert.doesNotMatch(backdrop, /\b(?:role|tabIndex|type|aria-label)=/);

  const hamburger = navbar.match(
    /<button\b(?:(?!<button\b)[\s\S])*?aria-label=\{menuOpen\s*\?\s*["']关闭菜单["']\s*:\s*["']打开菜单["']\}[\s\S]*?<\/button>/,
  )?.[0];
  assert.ok(hamburger, "could not locate the mobile hamburger button");
  assert.match(hamburger, /aria-expanded=\{menuOpen\}/);
});

test("applied empty state explains the real action and has one primary Today CTA", () => {
  assert.match(appliedPage, /import\s+Link\s+from\s+["']next\/link["'];/);
  const emptyState = appliedPage.match(
    /if\s*\(!actions\s*\|\|\s*actions\.length\s*===\s*0\)\s*\{[\s\S]*?\n\s*\}/,
  )?.[0];

  assert.ok(emptyState, "could not locate the no-applied-jobs empty state");
  assert.ok(emptyState.includes("点击「标记投递」"), "empty-state copy must name the actual action");
  assert.match(
    emptyState,
    /<EmptyPanel\b[\s\S]*?action=\{[\s\S]*?<Link\s+href=["']\/today["']\s+className=["']btn-ink["']>[\s\S]*?返回今日机会[\s\S]*?<\/Link>[\s\S]*?\}/,
  );
  assert.equal((appliedPage.match(/返回今日机会/g) ?? []).length, 1, "Today CTA must be unique");
});
