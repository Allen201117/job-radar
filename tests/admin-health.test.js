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

test("buildDailyReports merges technical runs into five human-facing operation cards", () => {
  assert.equal(typeof H.buildDailyReports, "function");
  const reports = H.buildDailyReports({
    crawl: {
      runs: 8,
      jobs_found: 120,
      jobs_created: 15,
      failed_runs: 1,
      failed_sources: 1,
      last_run_at: "2026-06-22T01:00:00Z",
    },
    discovery: {
      runs: 2,
      jobs_created: 3,
      jobs_updated: 4,
      failed_runs: 0,
      last_run_at: "2026-06-22T02:00:00Z",
    },
    insight: { today_created: 6 },
    opsRuns: [
      {
        module: "liveness_sweep",
        runs: 2,
        success: 2,
        partial: 0,
        failed: 0,
        checked: 100,
        expired: 9,
        deleted: 0,
        enriched: 0,
        companies_enriched: 0,
        retired: 0,
        last_run_at: "2026-06-22T03:00:00Z",
      },
      {
        module: "dead_link_audit",
        runs: 1,
        success: 1,
        partial: 0,
        failed: 0,
        checked: 20,
        expired: 2,
        deleted: 0,
        enriched: 0,
        companies_enriched: 0,
        retired: 0,
        last_run_at: "2026-06-22T04:00:00Z",
      },
      {
        module: "purge_expired",
        runs: 1,
        success: 1,
        partial: 0,
        failed: 0,
        checked: 0,
        expired: 0,
        deleted: 7,
        enriched: 0,
        companies_enriched: 0,
        retired: 0,
        last_run_at: "2026-06-22T05:00:00Z",
      },
      {
        module: "enrich_backlog",
        runs: 3,
        success: 2,
        partial: 1,
        failed: 0,
        checked: 80,
        expired: 0,
        deleted: 0,
        enriched: 30,
        companies_enriched: 0,
        retired: 0,
        last_run_at: "2026-06-22T06:00:00Z",
      },
      {
        module: "insight_backlog",
        runs: 2,
        success: 2,
        partial: 0,
        failed: 0,
        checked: 12,
        expired: 0,
        deleted: 0,
        enriched: 0,
        companies_enriched: 8,
        retired: 0,
        last_run_at: "2026-06-22T07:00:00Z",
      },
      {
        module: "insight_staleness",
        runs: 1,
        success: 1,
        partial: 0,
        failed: 0,
        checked: 0,
        expired: 0,
        deleted: 0,
        enriched: 0,
        companies_enriched: 0,
        retired: 5,
        last_run_at: "2026-06-22T08:00:00Z",
      },
    ],
  });

  assert.deepEqual(reports.map((report) => report.title), [
    "岗位抓取",
    "详情补全",
    "死岗治理",
    "职业洞察",
    "刷新 / 发现",
  ]);
  assert.deepEqual(
    reports.find((report) => report.key === "dead_jobs").metrics.map((metric) => [metric.label, metric.value]),
    [["核查", 120], ["判死", 11], ["清除", 7]],
  );
  assert.deepEqual(
    reports.find((report) => report.key === "insights").metrics.map((metric) => [metric.label, metric.value]),
    [["新增洞察", 6], ["富化公司", 8], ["过期下架", 5]],
  );
  assert.equal(reports.find((report) => report.key === "enrichment").status, "success");
});

test("buildDailyReports keeps ledger-only metrics unavailable before ops data accumulates", () => {
  const reports = H.buildDailyReports({
    crawl: null,
    discovery: null,
    insight: { today_created: 0 },
    opsRuns: [],
  });
  const deadJobs = reports.find((report) => report.key === "dead_jobs");
  assert.equal(deadJobs.status, "idle");
  assert.deepEqual(deadJobs.metrics.map((metric) => metric.value), [null, null, null]);
});

test("evaluateTodayHealth uses only available evidence and never invents a historical baseline", () => {
  assert.equal(typeof H.evaluateTodayHealth, "function");
  assert.deepEqual(
    H.evaluateTodayHealth({ validActive: 1000, crawlRuns: 4, crawlFailedRuns: 0 }),
    {
      level: "healthy",
      label: "健康",
      message: "今天抓取已运行，当前有可投岗位；历史波动基线仍在积累。",
    },
  );
  assert.equal(
    H.evaluateTodayHealth({ validActive: 1000, crawlRuns: 0, crawlFailedRuns: 0 }).level,
    "warning",
  );
  assert.equal(
    H.evaluateTodayHealth({ validActive: 1000, crawlRuns: 3, crawlFailedRuns: 3 }).level,
    "critical",
  );
  assert.equal(
    H.evaluateTodayHealth({
      validActive: 700,
      crawlRuns: 3,
      crawlFailedRuns: 0,
      previousValidActive: 1000,
    }).level,
    "warning",
  );
});

test("operational terms are translated to plain Chinese", () => {
  assert.equal(typeof H.translateOperationalTerm, "function");
  assert.equal(H.translateOperationalTerm("active"), "在招");
  assert.equal(H.translateOperationalTerm("expired"), "已确认撤岗");
  assert.equal(H.translateOperationalTerm("removed"), "暂时下线");
  assert.equal(H.translateOperationalTerm("partial_success"), "部分完成");
  assert.equal(H.translateOperationalTerm("unknown_value"), "未知状态");
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
    "159_admin_ops_dashboard.sql",
  );
  const migration = fs.existsSync(migrationPath) ? fs.readFileSync(migrationPath, "utf8") : "";
  assert.match(migration, /create table if not exists public\.ops_runs/i);
  assert.match(migration, /create index if not exists idx_ops_runs_module_run_date/i);
  assert.match(migration, /create or replace function public\.admin_health_snapshot/);
  assert.match(migration, /jsonb_agg/i);
  assert.match(migration, /crawl_runs/i);
  assert.match(migration, /discovery_runs/i);
  assert.match(migration, /insight_items/i);
  assert.match(migration, /insight_disputes/i);
  assert.match(migration, /events/i);
  assert.match(migration, /job_actions/i);
  assert.match(migration, /ops_runs/i);
  assert.match(migration, /revoke execute on function public\.admin_health_snapshot\(interval\) from public, anon, authenticated/i);
  assert.match(migration, /grant execute on function public\.admin_health_snapshot\(interval\) to service_role/i);
});

test("admin health page authenticates before parallel cross-database reads and renders four plain-language sections", () => {
  const pagePath = path.join(__dirname, "..", "app", "admin", "health", "page.tsx");
  const source = fs.existsSync(pagePath) ? fs.readFileSync(pagePath, "utf8") : "";
  assert.match(source, /await isAdmin\(\)/);
  assert.match(source, /redirect\("\/"\)/);
  assert.ok(source.indexOf("await isAdmin()") < source.indexOf("Promise.allSettled"));
  assert.match(source, /getJobsHealthSnapshot/);
  assert.match(source, /\.rpc\("admin_health_snapshot",\s*\{\s*p_window:\s*"7 days"\s*\}\)/s);
  assert.match(source, /Promise\.allSettled/);
  assert.match(source, /今日健康/);
  assert.match(source, /各模块每日战报/);
  assert.match(source, /岗位库体检/);
  assert.match(source, /用户与业务/);
  assert.match(source, /buildDailyReports/);
  assert.match(source, /零结果搜索率/);
  assert.match(source, /洞察抽屉打开率/);
  assert.match(source, /积累中/);
  assert.doesNotMatch(source, /expired 占全库|removed 占全库|active 从未探活|待埋点|>Source<|>Adapter<|>Partial</);
});

test("admin health loading boundary reuses structural warm-paper skeletons", () => {
  const loadingPath = path.join(__dirname, "..", "app", "admin", "health", "loading.tsx");
  const source = fs.existsSync(loadingPath) ? fs.readFileSync(loadingPath, "utf8") : "";
  assert.match(source, /MetricTilesSkeleton/);
  assert.match(source, /PanelSkeleton/);
  assert.match(source, /ProductHero/);
  assert.match(source, /bg-editorial/);
});

test("accuracy verifier checks both databases without printing connection strings", () => {
  const scriptPath = path.join(__dirname, "..", "scripts", "verify-admin-health-accuracy.mjs");
  const source = fs.existsSync(scriptPath) ? fs.readFileSync(scriptPath, "utf8") : "";
  assert.match(source, /SUPABASE_DB_URL/);
  assert.match(source, /JOBS_DATABASE_URL/);
  assert.match(source, /count_valid_active_jobs\(\)/);
  assert.match(source, /admin_health_snapshot/);
  assert.match(source, /ROLLBACK/);
  assert.doesNotMatch(source, /console\.log\([^)]*(SUPABASE_DB_URL|JOBS_DATABASE_URL)/);
});

test("all requested background workflows report to the ops ledger without replacing crawl_runs", () => {
  const files = [
    "crawler/enrich_backlog.py",
    "crawler/audit_dead_links.py",
    "crawler/insight_backlog.py",
    "crawler/insight_sweep.py",
    "crawler/discovery.py",
    "scripts/backfill_moka_summaries.py",
  ];
  for (const relPath of files) {
    const source = fs.readFileSync(path.join(__dirname, "..", relPath), "utf8");
    assert.match(source, /record_ops_run/);
  }
  const purge = fs.readFileSync(
    path.join(__dirname, "..", ".github", "workflows", "purge-expired.yml"),
    "utf8",
  );
  assert.match(purge, /delete from jobs where status = 'expired' returning 1/i);
  assert.match(purge, /\/rest\/v1\/ops_runs/);
  const crawlerDb = fs.readFileSync(path.join(__dirname, "..", "crawler", "db.py"), "utf8");
  assert.match(crawlerDb, /table\("crawl_runs"\)/);
});
