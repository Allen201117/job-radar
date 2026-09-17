// /today 取数链的性能契约（2026-09-18 立）。
//
// 这两条契约守的都是「省下来的东西不许把正确性一起省掉」：
//   ① job_actions 只取雷达链真正读的 4 列 —— 但**必须真的是那 4 列**，退回 `select("*")`
//      或漏一列都要当场红。漏列不报错、只是某个字段变 undefined（强度推导会静默变样）。
//   ② source 元信息改成跨实例全表快照之后，快照取不到时**必须**退回按 id 取。
//      不退回的后果是 `checkEligibility` 的 `source_disabled` 硬门整体失效 ——
//      被禁用源的岗从「明确拒绝」变成「元信息未知」而放行，这是静默放宽用户条件（F10 同类）。
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const ts = require("typescript");
const { loadTs } = require("./_load-ts");

const ROOT = path.join(__dirname, "..");
const { loadRadarContext, RADAR_ACTION_COLUMNS } = loadTs(
  path.join(ROOT, "lib", "opportunities", "context.ts"),
);

// ── ① job_actions 的取数列 ─────────────────────────────────────────────
test("job_actions 只取雷达链会读的 4 列，绝不退回 select(*)", async () => {
  const selects = {};
  const supabase = {
    from(table) {
      const chain = {
        select: (cols) => {
          selects[table] = cols;
          return chain;
        },
        eq: () => chain,
        maybeSingle: async () => ({ data: null, error: null }),
        then: (resolve, reject) => Promise.resolve({ data: [], error: null }).then(resolve, reject),
      };
      return chain;
    },
  };
  await loadRadarContext(supabase, "u1");

  assert.equal(selects.job_actions, RADAR_ACTION_COLUMNS, "job_actions 必须用 RADAR_ACTION_COLUMNS 取数");
  assert.notEqual(selects.job_actions, "*", "退回 select(*) 会把 job_snapshot 等没人读的列跨太平洋拉回来");
  assert.deepEqual(
    RADAR_ACTION_COLUMNS.split(",").map((s) => s.trim()).sort(),
    ["action", "created_at", "job_id", "updated_at"],
    "改这张表的取数列 = 改雷达链的行为，必须同步改 lib/opportunities/types.ts 的 RadarJobAction",
  );
});

test("loadRadarContext 可以把这一段的耗时与字节写进 [today-page] 账本", async () => {
  const supabase = {
    from() {
      const chain = {
        select: () => chain,
        eq: () => chain,
        maybeSingle: async () => ({ data: { user_id: "u1" }, error: null }),
        then: (resolve, reject) =>
          Promise.resolve({ data: [{ job_id: "j1", action: "saved" }], error: null }).then(resolve, reject),
      };
      return chain;
    },
  };
  const stats = { ms: 0, bytes: 0, actionRows: 0 };
  await loadRadarContext(supabase, "u1", stats);
  assert.equal(stats.actionRows, 1);
  assert.ok(stats.bytes > 0, "字节数是这条链最稳的观测量，不能恒为 0");
  assert.ok(stats.ms >= 0);
});

// ── ② source 元信息快照与兜底 ───────────────────────────────────────────
function loadServiceWithMocks(mocks, cache = new Map()) {
  const absPath = path.join(ROOT, "lib", "opportunities", "service.ts");
  return loadWithMocks(absPath, mocks, cache);
}

function loadWithMocks(absPath, mocks, cache) {
  if (cache.has(absPath)) return cache.get(absPath).exports;
  const compiled = ts.transpileModule(fs.readFileSync(absPath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
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
      if (fs.existsSync(tsPath)) return loadWithMocks(tsPath, mocks, cache);
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

const DISABLED_SOURCE = {
  id: "src-disabled",
  company: "Acme",
  adapter_name: "acme",
  crawl_method: "http",
  last_checked_at: "2026-09-18T00:00:00Z",
  enabled: false,
};

const RECALL_JOB = {
  id: "job-1",
  source_id: "src-disabled",
  company: "Acme",
  title: "产品经理",
  status: "active",
  first_seen_at: "2026-09-17T00:00:00Z",
  last_seen_at: "2026-09-18T00:00:00Z",
  jd_url: "https://example.com/j1",
};

/** 记录 sources 被按 id 查了几次（兜底路径的唯一足迹）。 */
function supabaseSpy(rows) {
  const calls = [];
  return {
    calls,
    client: {
      from(table) {
        const chain = {
          select: () => chain,
          in: async (_col, ids) => {
            calls.push({ table, ids });
            return { data: rows, error: null };
          },
        };
        return chain;
      },
    },
  };
}

async function runFeed({ snapshot }, spy) {
  let sawSourceMeta;
  const { buildOpportunityFeed } = loadServiceWithMocks({
    "./source-meta": {
      SOURCE_META_COLUMNS: "id, company, adapter_name, crawl_method, last_checked_at, enabled",
      loadSourceMetaSnapshot: async () => snapshot,
    },
    "./profile": { isProfileReady: () => true },
    "./eligibility": {
      // 只把 sourceMeta 透出来：本测试关心的是「硬门拿没拿到元信息」，不是打分。
      computeMatchFacts: (_job, _profile, meta) => {
        sawSourceMeta = meta;
        return { freshness: "verified", userAction: null, viewed: false, roleTier: "exact", companyHit: false };
      },
      checkEligibility: () => ({ eligible: true, degraded: [] }),
    },
    "./scoring": { scoreOpportunity: () => ({ score: 90, tier: "high", reasons: [] }) },
    "./signals": { deriveOpportunitySignals: () => [] },
    "./deadline": { parseDeadline: () => null },
    "../jobs-store/opportunities": {
      recallOpportunityCandidates: async () => ({ jobs: [RECALL_JOB], capped: false }),
    },
    "../jobs-store/read": { jobsStoreEnabled: () => true, jobsByIds: async () => [] },
    "./hydration": { hydrateOpportunityJobs: () => {} },
  });
  await buildOpportunityFeed(
    spy.client,
    { dailyLimit: 20, experienceStage: "社招" },
    [],
    null,
    { surface: "today", intensity: "active", now: new Date("2026-09-18T01:00:00Z") },
  );
  return sawSourceMeta;
}

test("快照命中时零 Supabase 往返，且硬门拿得到该源的元信息", async () => {
  const spy = supabaseSpy([DISABLED_SOURCE]);
  const meta = await runFeed({ snapshot: new Map([[DISABLED_SOURCE.id, DISABLED_SOURCE]]) }, spy);
  assert.equal(spy.calls.length, 0, "命中跨实例快照就不该再按 id 打一次悉尼");
  assert.equal(meta?.enabled, false, "source_disabled 硬门要能读到 enabled=false");
});

test("快照取不到必须退回按 id 取，绝不当成「这批岗没有元信息」", async () => {
  const spy = supabaseSpy([DISABLED_SOURCE]);
  const meta = await runFeed({ snapshot: null }, spy);
  assert.equal(spy.calls.length, 1, "快照为 null 时必须走兜底，否则 source_disabled 硬门整体失效");
  assert.deepEqual(spy.calls[0].ids, [DISABLED_SOURCE.id]);
  assert.equal(meta?.enabled, false);
});
