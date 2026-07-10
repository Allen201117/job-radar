const assert = require("node:assert/strict");
const test = require("node:test");
const { jsonResponse, loadRoute, resolvedQuery } = require("./route-test-utils");

const USER = { id: "verified-user" };
const JOB_ID = "00000000-0000-4000-8000-000000000001";
const JOB = {
  id: JOB_ID,
  jd_url: "https://jobs.example.com/roles/1",
  source_id: "source-1",
  status: "active",
  enrich_checked_at: null,
};
const SOURCE = {
  id: "source-1",
  adapter_name: "workday",
  source_url: "https://jobs.example.com",
};

function unauthorizedError() {
  return jsonResponse({ ok: false, error: "Unauthorized" }, { status: 401 });
}

function livenessMocks(calls, overrides = {}) {
  const sourceQuery = {
    select() {
      return this;
    },
    eq() {
      return this;
    },
    in() {
      return this;
    },
    maybeSingle: async () => ({ data: SOURCE, error: null }),
    then(resolve, reject) {
      return Promise.resolve({ data: [SOURCE], error: null }).then(resolve, reject);
    },
  };
  const service = {
    from(table) {
      if (table === "sources") {
        return sourceQuery;
      }
      return resolvedQuery({ data: null, error: null });
    },
  };

  return {
    "@/lib/apiAuth": {
      hasSessionCookie: () => true,
      requireUser: async () => ({ error: unauthorizedError() }),
    },
    "@/lib/auth": {
      getRequestUser: async () => ({ id: "cookie-only-user" }),
    },
    "@/lib/supabaseService": {
      createServiceClient: () => {
        calls.createServiceClient += 1;
        return service;
      },
    },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => true,
      jobsByIds: async () => {
        calls.jobsByIds += 1;
        return [JOB];
      },
    },
    "@/lib/jobs-store/write": {
      markJobExpiredById: async () => {
        calls.markJobExpiredById += 1;
      },
      touchJobCheckedById: async () => {
        calls.touchJobCheckedById += 1;
      },
    },
    "@/lib/liveness-client": {
      __esModule: true,
      default: {
        livenessSupported: () => true,
        checkLiveness: async () => {
          calls.checkLiveness += 1;
          return "alive";
        },
      },
    },
    "@/lib/opportunities/action-input": {
      isUuid: () => true,
    },
    "@/lib/track": {
      trackServerEvent: async () => {},
    },
    ...overrides,
  };
}

function zeroCalls() {
  return {
    createServiceClient: 0,
    requestJson: 0,
    jobsByIds: 0,
    checkLiveness: 0,
    markJobExpiredById: 0,
    touchJobCheckedById: 0,
  };
}

test("liveness POST routes reject unverified requests before parsing, probing, or writing", async () => {
  const calls = zeroCalls();
  const mocks = livenessMocks(calls);
  const batchRoute = loadRoute("app/api/jobs/liveness-check/route.ts", mocks);
  const singleRoute = loadRoute("app/api/jobs/[jobId]/liveness/route.ts", mocks);
  const request = {
    json: async () => {
      calls.requestJson += 1;
      return { ids: [JOB_ID] };
    },
  };

  const batchResponse = await batchRoute.POST(request);
  const singleResponse = await singleRoute.POST(request, { params: { jobId: JOB_ID } });

  assert.equal(batchResponse.status, 401);
  assert.equal(singleResponse.status, 401);
  assert.deepEqual(calls, zeroCalls());
});

test("authenticated single-job liveness event uses the verified user id", async () => {
  const calls = zeroCalls();
  const tracked = [];
  const mocks = livenessMocks(calls, {
    "@/lib/apiAuth": {
      hasSessionCookie: () => true,
      requireUser: async () => ({ user: USER }),
    },
    "@/lib/track": {
      trackServerEvent: async (...args) => tracked.push(args),
    },
  });
  const route = loadRoute("app/api/jobs/[jobId]/liveness/route.ts", mocks);

  const response = await route.POST({}, { params: { jobId: JOB_ID } });

  assert.equal(response.status, 200);
  assert.equal((await response.json()).result, "alive");
  assert.equal(tracked.length, 1);
  assert.equal(tracked[0][1], USER.id);
  assert.equal(tracked[0][2], "job_liveness_at_click");
});
