const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadRoute, loadTsModule, resolvedQuery } = require("./route-test-utils");

// 洞察路由要用 jobs-store 的两份列清单。真模块连着 pg（server-only），这里把常量原值从源码里读出来喂给桩，不手抄一份。
const JOBS_READ_SRC = fs.readFileSync(path.join(__dirname, "..", "lib", "jobs-store", "read.ts"), "utf8");
const INSIGHT_DERIVE_COLUMNS = /export const INSIGHT_DERIVE_COLUMNS =\s*"([^"]+)"/.exec(JOBS_READ_SRC)[1];
const INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE = JSON.parse(
  /export const INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE = (\[[^\]]*\])/.exec(JOBS_READ_SRC)[1],
);

const USER = { id: "user-1", email: "user@example.com" };
const ADMIN = { id: "admin-1", email: "admin@example.com" };
const submissionModule = loadTsModule("lib/insight-submission.ts");

function emptyDimensions() {
  return {
    timing: [],
    hiring: [],
    listing: [],
    compensation_intensity: [],
    path: [],
    culture: [],
  };
}

function chain(result, onCall = {}) {
  const filters = [];
  const calls = [];
  const query = {
    filters,
    calls,
    select(...args) {
      calls.push(["select", ...args]);
      return this;
    },
    insert(payload) {
      calls.push(["insert", payload]);
      if (onCall.insert) onCall.insert(payload);
      return this;
    },
    update(payload) {
      calls.push(["update", payload]);
      if (onCall.update) onCall.update(payload);
      return this;
    },
    eq(column, value) {
      filters.push(["eq", column, value]);
      return this;
    },
    neq(column, value) {
      filters.push(["neq", column, value]);
      return this;
    },
    // 数据层过滤走 not(column,"in","(a,b)")（见 lib/insight-bundle 的 DATA_LAYER_ORIGINS_FILTER）。
    not(column, operator, value) {
      filters.push(["not", column, operator, value]);
      return this;
    },
    in(column, value) {
      filters.push(["in", column, value]);
      return this;
    },
    or(filterStr) {
      filters.push(["or", filterStr]);
      return this;
    },
    order(column, options) {
      calls.push(["order", column, options]);
      return this;
    },
    limit(value) {
      calls.push(["limit", value]);
      return this;
    },
    single: async () => result,
    maybeSingle: async () => result,
    then(resolve, reject) {
      return Promise.resolve(result).then(resolve, reject);
    },
  };
  return query;
}

function insightRouteMocks(service, supabase) {
  return {
    "@/lib/apiAuth": {
      requireUser: async () => ({ user: USER, supabase }),
      requireAdmin: async () => ({ user: ADMIN, supabase }),
    },
    "@/lib/supabaseService": {
      createServiceClient: () => service,
    },
    "@/lib/insight-match": {
      findCompanyProfile: (profiles, company) =>
        (profiles || []).find((p) => p.company === company || (p.aliases || []).includes(company)) || null,
    },
    "@/lib/insight-submission": submissionModule,
    "@/lib/insight-verification": {
      evaluateInsight: () => ({ displayable: true, outdated: false, failure_reason: null }),
      resolveInsightFailure: () => null,
    },
    "@/lib/insight-bundle": {
      INSIGHT_DIMENSIONS: ["timing", "hiring", "listing", "compensation_intensity", "path", "culture"],
      ITEM_COLUMNS: "id",
      emptyDimensions,
      groupGatedInsights: () => ({ dimensions: emptyDimensions(), evaluations: [] }),
    },
    "@/lib/insight-derive": {
      deriveCompanyInsights: () => emptyDimensions(),
    },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => false,
      activeJobsByCompanies: async () => [],
      INSIGHT_DERIVE_COLUMNS,
      INSIGHT_DERIVE_COLUMNS_NOT_IN_SUPABASE,
    },
    "@/lib/insight-availability-cache": {
      // 让 getCachedCompanyProfilesLight 委托给传入的 supabase mock（与旧 supabase.from 语义一致）
      getCachedCompanyProfilesLight: async () => {
        try {
          const result = await supabase.from("company_profiles").select("id,company,aliases,display_name,headcount_band");
          return (result && result.data) || [];
        } catch { return []; }
      },
      getCachedActiveJobCounts: async () => [],
    },
    "@/lib/discovery-dispatch": {
      __esModule: true,
      default: {
        buildWorkflowDispatchRequest: () => ({}),
        resolveDispatchConfig: () => ({ configured: false, missing: [] }),
        isDispatchAccepted: () => false,
      },
    },
    "@/lib/insight-enrich-now": {
      __esModule: true,
      default: {
        buildInsightEnrichRunRecord: () => ({}),
        buildInsightWorkflowInputs: () => ({}),
        evaluateInsightEnrichDispatch: () => ({ action: "skip", reason: "test" }),
      },
    },
  };
}

test("submit API validates consent before inserting", async () => {
  const route = loadRoute("app/api/insights/submit/route.ts", insightRouteMocks(
    { from: () => resolvedQuery() },
    { from: () => resolvedQuery(), auth: { getUser: async () => ({ data: { user: USER } }) } },
  ));

  const response = await route.POST({
    json: async () => ({
      company: "字节跳动",
      dimension: "culture",
      topic: "culture",
      rating: 4,
      content: "团队节奏较快，但反馈直接。",
      consent: false,
    }),
  });

  assert.equal(response.status, 422);
  assert.equal((await response.json()).error, "consent_required");
});

test("submit API inserts a pending user-owned submission and does not return user_id", async () => {
  let inserted = null;
  const service = {
    from(table) {
      if (table === "company_profiles") return chain({ data: [], error: null });
      if (table === "insight_submissions") {
        return chain(
          { data: { id: "sub-1", status: "pending" }, error: null },
          { insert: (payload) => { inserted = payload; } },
        );
      }
      return resolvedQuery();
    },
  };
  const route = loadRoute("app/api/insights/submit/route.ts", insightRouteMocks(
    service,
    { from: () => resolvedQuery(), auth: { getUser: async () => ({ data: { user: USER } }) } },
  ));

  const response = await route.POST({
    json: async () => ({
      company: "字节跳动",
      dimension: "culture",
      topic: "culture",
      rating: 4,
      content: "团队节奏较快，但反馈直接。",
      consent: true,
    }),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.contributed, true);
  assert.equal(body.user_id, undefined);
  assert.equal(inserted.user_id, USER.id);
  assert.equal(inserted.status, "pending");
});

test("admin submissions API lists pending submissions", async () => {
  const rows = [{ id: "sub-1", company: "字节跳动", status: "pending", created_at: "2026-07-02T00:00:00.000Z" }];
  const service = {
    from(table) {
      assert.equal(table, "insight_submissions");
      return chain({ data: rows, error: null });
    },
  };
  const route = loadRoute("app/api/insights/admin/submissions/route.ts", insightRouteMocks(
    service,
    { from: () => resolvedQuery() },
  ));

  const response = await route.GET({ nextUrl: new URL("http://localhost/api/insights/admin/submissions") });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.deepEqual(body.submissions, rows);
});

test("admin submissions API approves with moderation metadata", async () => {
  let updated = null;
  let filters = null;
  const service = {
    from(table) {
      assert.equal(table, "insight_submissions");
      const q = chain({ data: { id: "sub-1" }, error: null }, {
        update: (payload) => { updated = payload; },
      });
      filters = q.filters;
      return q;
    },
  };
  const route = loadRoute("app/api/insights/admin/submissions/route.ts", insightRouteMocks(
    service,
    { from: () => resolvedQuery() },
  ));

  const response = await route.PATCH({
    json: async () => ({ id: "sub-1", status: "approved", reason: "ok" }),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.equal(updated.status, "approved");
  assert.equal(updated.moderation.reviewer_id, ADMIN.id);
  assert.equal(updated.moderation.reason, "ok");
  assert.deepEqual(filters, [["eq", "id", "sub-1"]]);
});

test("GET /api/insights：Supabase 兜底取数带齐派生要读的列，但不带那张表没有的招聘类型两列", async () => {
  // 那张表没有 recruitment_category / recruitment_explicit：select 里带上任何一个，PostgREST 整条报 42703，
  // 兜底一行都取不到（香港库不可用时抽屉的派生统计全空）。
  let jobsQuery = null;
  const supabase = {
    from(table) {
      const query = chain({ data: [], error: null });
      if (table === "jobs") jobsQuery = query;
      return query;
    },
  };
  const service = { from: () => chain({ data: [], error: null }) };
  const route = loadRoute("app/api/insights/route.ts", insightRouteMocks(service, supabase));

  const response = await route.GET({ nextUrl: new URL("http://localhost/api/insights?company=acme") });

  assert.equal(response.status, 200);
  assert.ok(jobsQuery, "桩里香港库是关的，应该走到 Supabase 兜底");
  const cols = jobsQuery.calls.find((call) => call[0] === "select")[1].split(",");
  for (const c of ["company", "title", "job_type", "posted_at", "first_seen_at", "status", "experience", "education"]) {
    assert.ok(cols.includes(c), "兜底取数少了 " + c);
  }
  assert.equal(cols.includes("recruitment_category"), false);
  assert.equal(cols.includes("recruitment_explicit"), false);
  // 清单里确实有这两列（香港库那条路要取），兜底只是把它们去掉
  assert.ok(INSIGHT_DERIVE_COLUMNS.includes("recruitment_category"));
});

test("GET /api/insights returns anonymized first-party aggregate after the threshold", async () => {
  const firstPartyRows = Array.from({ length: 5 }, (_, i) => ({
    id: `sub-${i + 1}`,
    company: "字节跳动",
    company_id: "company-1",
    user_id: `user-${i + 1}`,
    dimension: "culture",
    topic: "culture",
    rating: 4,
    content: `匿名反馈 ${i + 1}`,
    payload: {},
    status: "approved",
    moderation: { reviewer_id: "admin-1" },
    employment_verified: false,
    created_at: "2026-07-02T00:00:00.000Z",
    updated_at: "2026-07-02T00:00:00.000Z",
  }));
  const supabase = {
    from(table) {
      if (table === "company_profiles") {
        return chain({ data: [{ id: "company-1", company: "字节跳动", aliases: [] }], error: null });
      }
      if (table === "jobs") return chain({ data: [], error: null });
      if (table === "insight_items") return chain({ data: [], error: null });
      return chain({ data: [], error: null });
    },
  };
  const service = {
    from(table) {
      if (table === "recruitment_cycle_observations") return chain({ data: [], error: null });
      assert.equal(table, "insight_submissions");
      return chain({ data: firstPartyRows, error: null });
    },
  };
  const route = loadRoute("app/api/insights/route.ts", insightRouteMocks(service, supabase));

  const response = await route.GET({
    nextUrl: new URL("http://localhost/api/insights?company=%E5%AD%97%E8%8A%82%E8%B7%B3%E5%8A%A8"),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.first_party.visible, true);
  assert.equal(body.first_party.summary.count, 5);
  assert.equal(body.first_party.items[0].user_id, undefined);
  assert.equal(body.first_party.items[0].moderation, undefined);
});
