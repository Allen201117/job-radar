const assert = require("node:assert/strict");
const test = require("node:test");
const { jsonResponse, loadRoute, resolvedQuery } = require("./route-test-utils");

const USER = { id: "user-1", email: "user@example.com" };
process.env.SUPABASE_URL = "https://example.supabase.co";
process.env.SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key";

function authenticatedSupabase(role = "admin") {
  return {
    auth: { getUser: async () => ({ data: { user: USER } }) },
    from(table) {
      if (table === "profiles") {
        return resolvedQuery({ data: { role }, error: null });
      }
      return resolvedQuery();
    },
  };
}

function commonStatusMocks(overrides = {}) {
  return {
    "@/lib/auth": {
      createServerSupabase: async () => authenticatedSupabase(),
    },
    "@/lib/apiAuth": {
      requireUser: async () => ({ user: USER, supabase: authenticatedSupabase() }),
      assertOwnership: () => null,
    },
    "@/lib/live-search": {
      __esModule: true,
      default: { toApiJob: (job) => job },
    },
    "@/lib/discovery-dispatch": {
      __esModule: true,
      default: {
        summarizeDiscoveryRunStatus: (run) => ({
          status: run.status,
          phase: run.status,
          isTerminal: false,
          jobsCreated: 0,
          jobsUpdated: 0,
          candidatesFound: 0,
          failureReason: null,
          errorMessage: null,
          startedAt: run.started_at,
          finishedAt: run.finished_at,
        }),
        extractProducedJdUrls: () => [],
      },
    },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => false,
      jobsByUrls: async () => [],
    },
    "@supabase/supabase-js": {
      createClient: () => overrides.service,
    },
    "@/lib/supabaseService": {
      createServiceClient: () => overrides.service,
    },
    ...overrides.mocks,
  };
}

test("shared requireUser returns 401 when Supabase has no authenticated user", async () => {
  const apiAuth = loadRoute("lib/apiAuth.ts", {
    "./auth": {
      createServerSupabase: async () => ({
        auth: { getUser: async () => ({ data: { user: null } }) },
      }),
    },
  });

  const result = await apiAuth.requireUser();

  assert.equal(result.error.status, 401);
  assert.equal((await result.error.json()).error, "Unauthorized");
});

test("shared requireAdmin returns 403 for a non-admin profile", async () => {
  const apiAuth = loadRoute("lib/apiAuth.ts", {
    "./auth": {
      createServerSupabase: async () => authenticatedSupabase("user"),
    },
  });

  const result = await apiAuth.requireAdmin();

  assert.equal(result.error.status, 403);
  assert.equal((await result.error.json()).error, "forbidden");
});

test("shared assertOwnership rejects rows owned by another user", async () => {
  const apiAuth = loadRoute("lib/apiAuth.ts", {
    "./auth": { createServerSupabase: async () => authenticatedSupabase() },
  });

  const error = apiAuth.assertOwnership({ user_id: "user-2" }, USER.id);

  assert.equal(error.status, 403);
  assert.equal((await error.json()).error, "forbidden");
  assert.equal(apiAuth.assertOwnership({ user_id: USER.id }, USER.id), null);
});

test("discovery status returns 401 through the shared requireUser guard", async () => {
  const service = {
    from: () => resolvedQuery({ data: null, error: null }),
  };
  const route = loadRoute("app/api/discovery/status/route.ts", commonStatusMocks({
    service,
    mocks: {
      "@/lib/apiAuth": {
        requireUser: async () => ({
          error: jsonResponse({ ok: false, error: "Unauthorized" }, { status: 401 }),
        }),
        assertOwnership: () => null,
      },
    },
  }));

  const response = await route.GET({
    nextUrl: new URL("http://localhost/api/discovery/status?runId=run-1"),
  });

  assert.equal(response.status, 401);
  assert.equal((await response.json()).error, "Unauthorized");
});

test("insights admin returns 403 through the shared requireAdmin guard", async () => {
  const route = loadRoute("app/api/insights/admin/route.ts", {
    "@/lib/auth": {
      createServerSupabase: async () => authenticatedSupabase("admin"),
    },
    "@/lib/apiAuth": {
      requireAdmin: async () => ({
        error: jsonResponse({ ok: false, error: "forbidden" }, { status: 403 }),
      }),
    },
    "@/lib/supabaseService": {
      createServiceClient: () => ({ from: () => resolvedQuery() }),
    },
    "@/lib/insight-verification": {
      evaluateInsight: () => ({ displayable: true }),
      passesDeidentifiedGate: () => true,
      passesGradeGate: () => true,
      passesAssertionLint: () => true,
      hasTimeWindow: () => true,
    },
    "@/lib/insight-bundle": {
      INSIGHT_DIMENSIONS: ["timing"],
      ITEM_COLUMNS: "id",
      flattenSources: () => [],
    },
    "@/lib/industries": { normalizeIndustry: () => null },
  });

  const response = await route.GET();

  assert.equal(response.status, 403);
  assert.equal((await response.json()).error, "forbidden");
});

test("discovery status rejects another user's run through assertOwnership", async () => {
  let ownershipChecks = 0;
  const foreignRun = {
    id: "run-foreign",
    user_id: "user-2",
    status: "queued",
    diagnostics: {},
  };
  const service = {
    from: () => resolvedQuery({ data: foreignRun, error: null }),
  };
  const mocks = commonStatusMocks({
    service,
    mocks: {
      "@/lib/apiAuth": {
        requireUser: async () => ({ user: USER, supabase: authenticatedSupabase() }),
        assertOwnership: (row, userId) => {
          ownershipChecks += 1;
          return row?.user_id === userId
            ? null
            : jsonResponse({ ok: false, error: "forbidden" }, { status: 403 });
        },
      },
    },
  });
  const route = loadRoute("app/api/discovery/status/route.ts", mocks);

  const response = await route.GET({
    nextUrl: new URL("http://localhost/api/discovery/status?runId=run-foreign"),
  });

  assert.equal(response.status, 403);
  assert.equal(ownershipChecks, 1);
});

test("stale discovery self-heal update is scoped by run id, owner, and status", async () => {
  const readQuery = resolvedQuery({
    data: {
      id: "run-stale",
      user_id: USER.id,
      status: "running",
      diagnostics: { last_update_at: "2020-01-01T00:00:00.000Z" },
      created_at: "2020-01-01T00:00:00.000Z",
    },
    error: null,
  });
  const updateQuery = resolvedQuery();
  const service = {
    from() {
      return readQuery.filters.length === 0 ? readQuery : updateQuery;
    },
  };
  let fromCalls = 0;
  service.from = () => {
    fromCalls += 1;
    return fromCalls === 1 ? readQuery : updateQuery;
  };
  const route = loadRoute("app/api/discovery/status/route.ts", commonStatusMocks({ service }));

  const response = await route.GET({
    nextUrl: new URL("http://localhost/api/discovery/status?runId=run-stale"),
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(response.status, 200);
  assert.deepEqual(updateQuery.filters, [
    ["id", "run-stale"],
    ["user_id", USER.id],
    ["status", "running"],
  ]);
});

test("non-admin cannot resolve another user's dispute", async () => {
  const service = {
    from: () =>
      resolvedQuery({
        data: { id: "dispute-1", item_id: "item-1", reporter_user_id: "user-2", status: "open" },
        error: null,
      }),
  };
  const route = loadRoute("app/api/insights/dispute/resolve/route.ts", {
    "@/lib/auth": {
      createServerSupabase: async () => authenticatedSupabase("admin"),
    },
    "@/lib/apiAuth": {
      requireAdmin: async () => ({
        error: jsonResponse({ ok: false, error: "forbidden" }, { status: 403 }),
      }),
    },
    "@/lib/supabaseService": { createServiceClient: () => service },
  });

  const response = await route.POST({
    json: async () => ({ dispute_id: "dispute-1", resolution: "rejected" }),
  });

  assert.equal(response.status, 403);
  assert.equal((await response.json()).error, "forbidden");
});
