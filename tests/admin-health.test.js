const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadOptionalTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  if (!fs.existsSync(sourcePath)) return {};
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const H = loadOptionalTsModule(path.join("lib", "admin-health.ts"));

test("formatPercent reports one decimal and does not invent a rate for zero denominator", () => {
  assert.equal(typeof H.formatPercent, "function");
  assert.equal(H.formatPercent(1, 4), "25.0%");
  assert.equal(H.formatPercent(0, 4), "0.0%");
  assert.equal(H.formatPercent(2, 0), "—");
});

test("formatDuration renders compact human-readable seconds", () => {
  assert.equal(typeof H.formatDuration, "function");
  assert.equal(H.formatDuration(null), "—");
  assert.equal(H.formatDuration(0.4), "<1 秒");
  assert.equal(H.formatDuration(43.4), "43 秒");
  assert.equal(H.formatDuration(125.2), "2 分 5 秒");
});

test("normalizeCrawlSources derives success and partial rates from terminal non-skipped runs", () => {
  assert.equal(typeof H.normalizeCrawlSources, "function");
  assert.deepEqual(
    H.normalizeCrawlSources([
      {
        source_id: "s1",
        company: "甲公司",
        adapter_name: "moka",
        runs: 10,
        success: 6,
        partial_success: 2,
        failed: 2,
        skipped: 1,
      },
    ]),
    [
      {
        sourceId: "s1",
        company: "甲公司",
        adapterName: "moka",
        runs: 10,
        successRate: "60.0%",
        partialRate: "20.0%",
        failed: 2,
        skipped: 1,
      },
    ],
  );
});

test("normalizeDiscoveryModes joins duration and failure reasons by mode", () => {
  assert.equal(typeof H.normalizeDiscoveryModes, "function");
  assert.deepEqual(
    H.normalizeDiscoveryModes(
      [
        { mode: "company_refresh", runs: 4, completed_runs: 3, avg_duration_seconds: 92.4 },
        { mode: "official_job_discovery", runs: 2, completed_runs: 0, avg_duration_seconds: null },
      ],
      [
        { mode: "company_refresh", reason: "dispatch_failed", count: 2 },
        { mode: "official_job_discovery", reason: "provider_rate_limited", count: 1 },
      ],
    ),
    [
      {
        mode: "company_refresh",
        label: "公司库刷新",
        runs: 4,
        completedRuns: 3,
        averageDuration: "1 分 32 秒",
        failures: [{ reason: "dispatch_failed", count: 2 }],
      },
      {
        mode: "official_job_discovery",
        label: "官方源发现",
        runs: 2,
        completedRuns: 0,
        averageDuration: "—",
        failures: [{ reason: "provider_rate_limited", count: 1 }],
      },
    ],
  );
});

test("normalizeInsightDimensions returns known dimensions first and keeps unknown dimensions visible", () => {
  assert.equal(typeof H.normalizeInsightDimensions, "function");
  assert.deepEqual(
    H.normalizeInsightDimensions([
      { dimension: "culture", count: 5 },
      { dimension: "timing", count: 8 },
      { dimension: "new_dimension", count: 2 },
    ]),
    [
      { dimension: "timing", label: "时机", count: 8 },
      { dimension: "culture", label: "文化", count: 5 },
      { dimension: "new_dimension", label: "new_dimension", count: 2 },
    ],
  );
});

test("jobs health reader uses the valid-active RPC and aggregate SQL instead of loading job rows", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "lib", "jobs-store", "read.ts"),
    "utf8",
  );
  assert.match(source, /export async function getJobsHealthSnapshot/);
  assert.match(source, /count_valid_active_jobs\(\)/);
  assert.match(source, /filter\s*\(\s*where status = 'active'/i);
  assert.match(source, /enrich_checked_at is null/i);
  assert.match(source, /Asia\/Shanghai/);
  const healthFunction = source.slice(
    source.indexOf("export async function getJobsHealthSnapshot"),
    source.indexOf("/** 最新 active 一页"),
  );
  assert.doesNotMatch(healthFunction, /JOB_COLUMNS/);
});

test("Supabase health snapshot is aggregated in SQL and executable only by service_role", () => {
  const migrationPath = path.join(
    __dirname,
    "..",
    "supabase",
    "migrations",
    "158_admin_health_snapshot.sql",
  );
  const migration = fs.existsSync(migrationPath) ? fs.readFileSync(migrationPath, "utf8") : "";
  assert.match(migration, /create or replace function public\.admin_health_snapshot/);
  assert.match(migration, /jsonb_agg/i);
  assert.match(migration, /crawl_runs/i);
  assert.match(migration, /discovery_runs/i);
  assert.match(migration, /insight_items/i);
  assert.match(migration, /insight_disputes/i);
  assert.match(migration, /revoke execute on function public\.admin_health_snapshot\(interval\) from public, anon, authenticated/i);
  assert.match(migration, /grant execute on function public\.admin_health_snapshot\(interval\) to service_role/i);
});

test("admin health page authenticates before parallel cross-database reads and keeps pending metrics explicit", () => {
  const pagePath = path.join(__dirname, "..", "app", "admin", "health", "page.tsx");
  const source = fs.existsSync(pagePath) ? fs.readFileSync(pagePath, "utf8") : "";
  assert.match(source, /await isAdmin\(\)/);
  assert.match(source, /redirect\("\/"\)/);
  assert.ok(source.indexOf("await isAdmin()") < source.indexOf("Promise.allSettled"));
  assert.match(source, /getJobsHealthSnapshot/);
  assert.match(source, /\.rpc\("admin_health_snapshot",\s*\{\s*p_window:\s*"7 days"\s*\}\)/s);
  assert.match(source, /Promise\.allSettled/);
  assert.match(source, /零结果搜索率/);
  assert.match(source, /洞察抽屉打开率/);
  assert.match(source, /简历解析成功率/);
  assert.match(source, /待埋点/);
});

test("admin health loading boundary reuses structural warm-paper skeletons", () => {
  const loadingPath = path.join(__dirname, "..", "app", "admin", "health", "loading.tsx");
  const source = fs.existsSync(loadingPath) ? fs.readFileSync(loadingPath, "utf8") : "";
  assert.match(source, /MetricTilesSkeleton/);
  assert.match(source, /PanelSkeleton/);
  assert.match(source, /ProductHero/);
  assert.match(source, /bg-editorial/);
});
