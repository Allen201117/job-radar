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
  storeEnabled,
  storeCounts,
  rpcCounts,
  profile = PROFILE,
  user = { id: "user-1" },
} = {}) {
  const calls = { store: 0, rpc: 0, from: 0 };
  const supabase = {
    auth: { getUser: async () => ({ data: { user } }) },
    from(table) {
      calls.from += 1;
      if (table === "company_profiles") return resolvedQuery({ data: [profile], error: null });
      if (table === "insight_items") return resolvedQuery({ data: [ITEM], error: null });
      throw new Error(`unexpected table: ${table}`);
    },
    rpc: async (name) => {
      calls.rpc += 1;
      assert.equal(name, "active_job_counts_by_company");
      return rpcCounts ?? { data: [{ company: PROFILE.company, job_count: 3 }], error: null };
    },
  };
  const route = loadRoute("app/api/insights/availability/route.ts", {
    "@/lib/auth": { createServerSupabase: async () => supabase },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => storeEnabled,
      activeJobCountsByCompany: async () => {
        calls.store += 1;
        if (storeCounts instanceof Error) throw storeCounts;
        return storeCounts ?? [{ company: PROFILE.company, job_count: 3 }];
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
  const { route, calls } = loadAvailabilityRoute({ storeEnabled: true });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: true } },
  });
  assert.deepEqual(calls, { store: 1, rpc: 0, from: 2 });
});

test("availability uses Supabase RPC when jobs store is disabled", async () => {
  const { route, calls } = loadAvailabilityRoute({ storeEnabled: false });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.equal((await response.json()).availability[PROFILE.company].derived, true);
  assert.deepEqual(calls, { store: 0, rpc: 1, from: 2 });
});

test("availability degrades an HK count error without hiding real insights", async () => {
  const { route, calls } = loadAvailabilityRoute({
    storeEnabled: true,
    storeCounts: new Error("HK count failed"),
  });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: false } },
  });
  assert.deepEqual(calls, { store: 1, rpc: 0, from: 2 });
});

test("availability derives from profile-matched company count variants", async () => {
  const profile = { ...PROFILE, company: "腾讯" };
  const { route, calls } = loadAvailabilityRoute({
    storeEnabled: true,
    storeCounts: [{ company: "腾讯深圳", job_count: 3 }],
    profile,
  });
  const response = await route.GET(requestFor("腾讯"));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { 腾讯: { real: 1, derived: true } },
  });
  assert.deepEqual(calls, { store: 1, rpc: 0, from: 2 });
});

test("availability rejects unauthenticated requests before reading counts or insight tables", async () => {
  const { route, calls } = loadAvailabilityRoute({
    storeEnabled: true,
    user: null,
  });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { ok: false, error: "Unauthorized" });
  assert.deepEqual(calls, { store: 0, rpc: 0, from: 0 });
});

test("availability degrades a Supabase count error without hiding real insights", async () => {
  const { route, calls } = loadAvailabilityRoute({
    storeEnabled: false,
    rpcCounts: { data: null, error: new Error("RPC count failed") },
  });
  const response = await route.GET(requestFor());

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    availability: { [PROFILE.company]: { real: 1, derived: false } },
  });
  assert.deepEqual(calls, { store: 0, rpc: 1, from: 2 });
});
