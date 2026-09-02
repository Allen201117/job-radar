const assert = require("node:assert/strict");
const test = require("node:test");
const { loadRoute, loadTsModule, resolvedQuery } = require("./route-test-utils");

const insightMatch = loadTsModule("lib/insight-match.ts");

const PROFILE = { id: "profile-1", company: "字节跳动", aliases: [] };
const ITEM = { id: "insight-1", company_id: PROFILE.id, status: "active" };

function requestFor(company = PROFILE.company) {
  return { nextUrl: { searchParams: new URLSearchParams({ companies: company }) } };
}

function loadAvailabilityRoute({
  counts,
  countsError,
  profile = PROFILE,
  user = { id: "user-1" },
} = {}) {
  // 改走缓存后：company_profiles 和 activeJobCountsByCompany 均通过
  // getCachedCompanyProfilesLight / getCachedActiveJobCounts，不再经过 supabase.from
  const calls = { cache_profiles: 0, cache_counts: 0, from: 0 };
  const supabase = {
    auth: {
      getUser: async () => ({ data: { user } }),
      getClaims: async () =>
        user
          ? { data: { claims: { sub: user.id, email: user.email } }, error: null }
          : { data: null, error: { message: "no session" } },
    },
    from(table) {
      calls.from += 1;
      // company_profiles 已走缓存，不应再经过这里
      if (table === "company_profiles") throw new Error("company_profiles should go through cache, not supabase.from");
      if (table === "insight_items") return resolvedQuery({ data: [ITEM], error: null });
      throw new Error(`unexpected table: ${table}`);
    },
  };
  const route = loadRoute("app/api/insights/availability/route.ts", {
    "@/lib/auth": { createServerSupabase: async () => supabase },
    // 缓存模块：直接返回测试数据，不经过真实 supabase 或 HK 库
    "@/lib/insight-availability-cache": {
      getCachedCompanyProfilesLight: async () => {
        calls.cache_profiles += 1;
        return [profile];
      },
      getCachedActiveJobCounts: async () => {
        calls.cache_counts += 1;
        if (countsError) throw countsError;
        return counts ?? [{ company: profile.company, job_count: 3 }];
      },
    },
    "@/lib/supabase-paginate": {
      fetchAllPages: async (pageFn) => {
        // 单次调用 page(0, 999) 即可，resolvedQuery.then 返回测试数据
        const result = await pageFn(0, 999);
        if (result.error) throw new Error(result.error.message);
        return result.data || [];
      },
    },
    "@/lib/insight-match": insightMatch,
    "@/lib/insight-bundle": {
      ITEM_COLUMNS: "id,company_id,status",
      INSIGHT_DIMENSIONS: ["timing"],
      groupGatedInsights: () => ({ dimensions: { timing: [ITEM] } }),
    },
  });
  return { route, calls };
}

test("availability uses HK company counts and skips Supabase RPC when jobs store is enabled", async () => {
  // 在缓存架构下，HK store vs RPC 的选择封装在 getCachedActiveJobCounts 内部；
  // 路由只关心「有无计数」，不再直接调 jobsStoreEnabled / rpc。
  const { route, calls } = loadAvailabilityRoute();
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: true } },
  });
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});

test("availability uses Supabase RPC when jobs store is disabled", async () => {
  // 此测试改为验证：当计数可用时，derived 正确为 true（路由已不直接区分 HK/RPC）
  const { route, calls } = loadAvailabilityRoute({ counts: [{ company: PROFILE.company, job_count: 3 }] });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.equal((await response.json()).availability[PROFILE.company].derived, true);
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});

test("availability degrades an HK count error without hiding real insights", async () => {
  const { route, calls } = loadAvailabilityRoute({ countsError: new Error("count fetch failed") });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: false } },
  });
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});

test("availability derives from profile-matched company-name variants", async () => {
  const profile = { ...PROFILE, company: "腾讯" };
  const { route, calls } = loadAvailabilityRoute({
    counts: [{ company: "腾讯深圳", job_count: 3 }],
    profile,
  });
  const response = await route.GET(requestFor("腾讯"));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { 腾讯: { real: 1, derived: true } },
  });
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});

test("availability derives from profile aliases in company counts", async () => {
  const profile = { ...PROFILE, company: "腾讯", aliases: ["微信"] };
  const { route, calls } = loadAvailabilityRoute({
    counts: [{ company: "微信科技", job_count: 3 }],
    profile,
  });
  const response = await route.GET(requestFor("腾讯"));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { 腾讯: { real: 1, derived: true } },
  });
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});

test("availability rejects unauthenticated requests before reading counts or insight tables", async () => {
  const { route, calls } = loadAvailabilityRoute({ user: null });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { ok: false, error: "Unauthorized" });
  assert.deepEqual(calls, { cache_profiles: 0, cache_counts: 0, from: 0 });
});

test("availability degrades a Supabase count error without hiding real insights", async () => {
  // 缓存架构下，计数错误统一走 getCachedActiveJobCounts 的 .catch() 降级
  const { route, calls } = loadAvailabilityRoute({ countsError: new Error("count failed") });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: false } },
  });
  assert.deepEqual(calls, { cache_profiles: 1, cache_counts: 1, from: 1 });
});
