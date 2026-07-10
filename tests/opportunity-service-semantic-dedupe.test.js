const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const ROOT = path.join(__dirname, "..");

function loadTsWithMocks(absPath, mocks = {}, cache = new Map()) {
  if (cache.has(absPath)) return cache.get(absPath).exports;

  const compiled = ts.transpileModule(fs.readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const mod = { exports: {} };
  cache.set(absPath, mod);

  const dir = path.dirname(absPath);
  const baseRequire = Module.createRequire(absPath);
  const customRequire = (spec) => {
    if (spec === "server-only") return {};
    if (Object.prototype.hasOwnProperty.call(mocks, spec)) return mocks[spec];

    let base = null;
    if (spec.startsWith("@/")) base = path.join(ROOT, spec.slice(2));
    else if (spec.startsWith(".")) base = path.resolve(dir, spec);

    if (base) {
      const tsPath = base.endsWith(".ts") ? base : `${base}.ts`;
      if (fs.existsSync(tsPath)) return loadTsWithMocks(tsPath, mocks, cache);
      const jsPath = base.endsWith(".js") ? base : `${base}.js`;
      if (fs.existsSync(jsPath)) return baseRequire(jsPath);
      return baseRequire(base);
    }
    return baseRequire(spec);
  };

  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports,
    customRequire,
    mod,
    absPath,
    dir,
  );
  return mod.exports;
}

function job(overrides) {
  return {
    id: "job",
    source_id: null,
    company: "Acme",
    title: "AI Product Manager",
    location: "Shanghai",
    status: "active",
    first_seen_at: "2026-07-01T00:00:00Z",
    last_seen_at: "2026-07-10T00:00:00Z",
    enrich_checked_at: "2026-07-10T00:00:00Z",
    posted_at: null,
    deadline: null,
    jd_url: "https://example.com/job",
    ...overrides,
  };
}

async function buildFeed(recallJobs, criticalJob, dailyLimit = 20) {
  const jobs = new Map([...recallJobs, criticalJob].map((item) => [item.id, item]));
  const { buildOpportunityFeed } = loadTsWithMocks(path.join(ROOT, "lib", "opportunities", "service.ts"), {
    "./profile": { isProfileReady: () => true },
    "./eligibility": {
      computeMatchFacts: () => ({
        freshness: "verified",
        userAction: null,
        viewed: false,
        roleTier: "exact",
        companyHit: false,
      }),
      checkEligibility: () => ({ eligible: true, degraded: [] }),
    },
    "./scoring": { scoreOpportunity: () => ({ score: 90, tier: "high", reasons: [] }) },
    "./signals": {
      deriveOpportunitySignals: (_job, _facts, _profile, _now, context) => [
        context.isWatched
          ? { type: "CLOSED_OR_STALE", label: "closed", priority: 1, isCritical: true, evidence: {} }
          : { type: "STILL_OPEN", label: "open", priority: 3, isCritical: false, evidence: {} },
      ],
    },
    "./deadline": { parseDeadline: () => null },
    "../jobs-store/opportunities": {
      recallOpportunityCandidates: async () => ({ jobs: recallJobs, capped: false }),
    },
    "../jobs-store/read": {
      jobsStoreEnabled: () => true,
      jobsByIds: async (ids) => ids.map((id) => jobs.get(id)).filter(Boolean),
    },
    "./hydration": { hydrateOpportunityJobs: () => {} },
  });

  const supabase = {
    from: () => ({ select: async () => ({ data: [], error: null }) }),
  };
  const feed = await buildOpportunityFeed(
    supabase,
    { dailyLimit, experienceStage: "社招" },
    [{ job_id: criticalJob.id, action: "saved" }],
    null,
    { surface: "today", intensity: "active", now: new Date("2026-07-10T00:00:00Z") },
  );

  return feed;
}

test("service 外部 critical 按语义取代另一 ID 的普通分区岗位", async () => {
  const mainJob = job({ id: "main-id" });
  const criticalJob = job({
    id: "critical-id",
    company: " acme ",
    title: "ai-product manager",
    location: "Shanghai",
    status: "expired",
  });
  const feed = await buildFeed([mainJob], criticalJob);

  assert.deepEqual(feed.sections.critical.map((item) => item.job.id), ["critical-id"]);
  assert.deepEqual(
    [...feed.sections.main, ...feed.sections.explore, ...feed.sections.waiting].map((item) => item.job.id),
    [],
  );
  assert.equal(feed.counts.total, 1);
  assert.equal(feed.counts.critical, 1);
  assert.equal(feed.counts.main, 0);
});

test("external critical 在统一分组前去重，main 截断后仍从第 6 候选回填到 5", async () => {
  const collidingMain = job({ id: "a-colliding" });
  const fillers = Array.from({ length: 5 }, (_, index) =>
    job({
      id: `b-filler-${index}`,
      company: `Company ${index}`,
      title: `Role ${index}`,
      location: "Beijing",
    })
  );
  const criticalJob = job({
    id: "critical-id",
    company: " acme ",
    title: "ai-product manager",
    location: "Shanghai",
    status: "expired",
  });
  const feed = await buildFeed([collidingMain, ...fillers], criticalJob, 5);

  assert.equal(feed.sections.critical.length, 1);
  assert.equal(feed.sections.main.length, 5);
  assert.equal(feed.counts.total, 6);
  assert.equal(feed.counts.critical, 1);
  assert.equal(feed.counts.main, 5);
  assert.equal(feed.counts.screened, 6);
});
