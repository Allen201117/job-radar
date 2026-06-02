const { test } = require("node:test");
const assert = require("node:assert/strict");

const {
  parseRepoSlug,
  resolveDispatchConfig,
  validateDiscoveryDispatchInput,
  buildBrowserDiscoveryRunRecord,
  buildWorkflowDispatchRequest,
  isDispatchAccepted,
  summarizeDiscoveryRunStatus,
  extractProducedJdUrls,
} = require("../lib/discovery-dispatch");

test("parseRepoSlug accepts owner/name and full URL", () => {
  assert.deepEqual(parseRepoSlug("acme/job-radar"), { owner: "acme", name: "job-radar" });
  assert.deepEqual(parseRepoSlug("https://github.com/acme/job-radar"), {
    owner: "acme",
    name: "job-radar",
  });
  assert.deepEqual(parseRepoSlug("https://github.com/acme/job-radar.git"), {
    owner: "acme",
    name: "job-radar",
  });
});

test("parseRepoSlug rejects incomplete slugs", () => {
  assert.equal(parseRepoSlug(""), null);
  assert.equal(parseRepoSlug("acme"), null);
  assert.equal(parseRepoSlug(null), null);
});

test("resolveDispatchConfig reports missing env", () => {
  const config = resolveDispatchConfig({});
  assert.equal(config.configured, false);
  assert.deepEqual(config.missing, ["GITHUB_DISPATCH_TOKEN", "GITHUB_DISPATCH_REPO"]);
  assert.equal(config.workflowFile, "daily-crawl.yml");
  assert.equal(config.ref, "main");
});

test("resolveDispatchConfig resolves when configured", () => {
  const config = resolveDispatchConfig({
    GITHUB_DISPATCH_TOKEN: "ghp_x",
    GITHUB_DISPATCH_REPO: "acme/job-radar",
    GITHUB_DISPATCH_WORKFLOW: "crawl.yml",
    GITHUB_DISPATCH_REF: "feat/spa",
  });
  assert.equal(config.configured, true);
  assert.deepEqual(config.missing, []);
  assert.deepEqual(config.slug, { owner: "acme", name: "job-radar" });
  assert.equal(config.workflowFile, "crawl.yml");
  assert.equal(config.ref, "feat/spa");
});

test("validateDiscoveryDispatchInput requires query and clamps limit", () => {
  const empty = validateDiscoveryDispatchInput({});
  assert.equal(empty.ok, false);
  assert.ok(empty.errors.includes("query_required"));

  const ok = validateDiscoveryDispatchInput({ query: "  算法  ", limit: 999, city: " 北京 " });
  assert.equal(ok.ok, true);
  assert.equal(ok.normalized.query, "算法");
  assert.equal(ok.normalized.city, "北京");
  assert.equal(ok.normalized.limit, 60);

  const defaulted = validateDiscoveryDispatchInput({ query: "x", limit: "nope" });
  assert.equal(defaulted.normalized.limit, 30);

  const tooLong = validateDiscoveryDispatchInput({ query: "a".repeat(81) });
  assert.ok(tooLong.errors.includes("query_too_long"));
});

test("validateDiscoveryDispatchInput accepts job_type alias", () => {
  const r = validateDiscoveryDispatchInput({ query: "x", job_type: "engineering" });
  assert.equal(r.normalized.jobType, "engineering");
});

test("buildBrowserDiscoveryRunRecord produces a queued browser_discovery row", () => {
  const row = buildBrowserDiscoveryRunRecord({
    runId: "run-1",
    userId: "user-1",
    query: "算法",
    city: "",
    company: "",
    jobType: "",
    startedAt: "2026-06-02T00:00:00.000Z",
  });
  assert.equal(row.id, "run-1");
  assert.equal(row.user_id, "user-1");
  assert.equal(row.status, "queued");
  assert.equal(row.mode, "browser_discovery");
  assert.equal(row.query, "算法");
  assert.equal(row.city, null);
  assert.equal(row.started_at, "2026-06-02T00:00:00.000Z");
});

test("buildWorkflowDispatchRequest builds a valid GitHub dispatch request", () => {
  const req = buildWorkflowDispatchRequest({
    slug: { owner: "acme", name: "job-radar" },
    workflowFile: "daily-crawl.yml",
    ref: "main",
    token: "ghp_secret",
    inputs: { mode: "discovery", run_id: "run-1", query: "算法", limit: 30, city: "" },
  });
  assert.equal(
    req.url,
    "https://api.github.com/repos/acme/job-radar/actions/workflows/daily-crawl.yml/dispatches",
  );
  assert.equal(req.method, "POST");
  assert.equal(req.headers.Authorization, "Bearer ghp_secret");
  assert.equal(req.headers.Accept, "application/vnd.github+json");

  const body = JSON.parse(req.body);
  assert.equal(body.ref, "main");
  // all inputs must be strings
  assert.equal(body.inputs.limit, "30");
  assert.equal(body.inputs.run_id, "run-1");
  assert.equal(body.inputs.city, "");
  assert.equal(typeof body.inputs.limit, "string");
});

test("buildWorkflowDispatchRequest throws on missing token/slug", () => {
  assert.throws(() =>
    buildWorkflowDispatchRequest({
      slug: null,
      workflowFile: "x.yml",
      ref: "main",
      token: "t",
      inputs: {},
    }),
  );
  assert.throws(() =>
    buildWorkflowDispatchRequest({
      slug: { owner: "a", name: "b" },
      workflowFile: "x.yml",
      ref: "main",
      token: "",
      inputs: {},
    }),
  );
});

test("isDispatchAccepted treats 204 as success", () => {
  assert.equal(isDispatchAccepted(204), true);
  assert.equal(isDispatchAccepted(200), true);
  assert.equal(isDispatchAccepted(401), false);
  assert.equal(isDispatchAccepted(422), false);
});

test("summarizeDiscoveryRunStatus maps DB status to UI phases", () => {
  assert.equal(summarizeDiscoveryRunStatus({ status: "queued" }).phase, "queued");
  assert.equal(summarizeDiscoveryRunStatus({ status: "running" }).phase, "running");
  assert.equal(summarizeDiscoveryRunStatus({ status: "success" }).phase, "done");
  assert.equal(summarizeDiscoveryRunStatus({ status: "partial_success" }).phase, "done");
  assert.equal(summarizeDiscoveryRunStatus({ status: "failed" }).phase, "failed");

  const queued = summarizeDiscoveryRunStatus({ status: "queued" });
  assert.equal(queued.isTerminal, false);
  const done = summarizeDiscoveryRunStatus({
    status: "success",
    jobs_created: 12,
    jobs_updated: 3,
  });
  assert.equal(done.isTerminal, true);
  assert.equal(done.jobsCreated, 12);
  assert.equal(done.jobsUpdated, 3);
});

test("extractProducedJdUrls reads diagnostics.produced_jd_urls", () => {
  assert.deepEqual(
    extractProducedJdUrls({ diagnostics: { produced_jd_urls: ["https://a/1", "", 5, "https://a/2"] } }),
    ["https://a/1", "https://a/2"],
  );
  assert.deepEqual(extractProducedJdUrls({ diagnostics: null }), []);
  assert.deepEqual(extractProducedJdUrls({}), []);
});
