const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const H = loadTs(path.join(__dirname, "..", "lib", "admin-health.ts"));

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

test("normalizeCoverageSnapshot classifies measurable, blind, and under-covered sources", () => {
  assert.equal(typeof H.normalizeCoverageSnapshot, "function");
  assert.deepEqual(
    H.normalizeCoverageSnapshot({
      measurable: "3",
      blind: 1,
      avg_coverage_pct: 67,
      under_count: 2,
      under_sources: [
        {
          company: "乙公司",
          adapter: "hotjob",
          reported_total: 0,
          fetched: 5,
          coverage_pct: null,
          last_run_at: "2026-07-07T01:00:00Z",
        },
        {
          company: "甲公司",
          adapter: "moka",
          reported_total: 100,
          fetched: 39,
          coverage_pct: 39,
          last_run_at: "2026-07-07T02:00:00Z",
        },
        {
          company: "丙公司",
          adapter: "workday",
          reported_total: 100,
          fetched: 120,
          coverage_pct: 120,
          last_run_at: "2026-07-07T03:00:00Z",
        },
      ],
    }),
    {
      measurable: 3,
      blind: 1,
      avgCoveragePct: 67,
      underCount: 2,
      underSources: [
        {
          company: "乙公司",
          adapter: "hotjob",
          reportedTotal: 0,
          fetched: 5,
          coveragePct: null,
          lastRunAt: "2026-07-07T01:00:00Z",
        },
        {
          company: "甲公司",
          adapter: "moka",
          reportedTotal: 100,
          fetched: 39,
          coveragePct: 39,
          lastRunAt: "2026-07-07T02:00:00Z",
        },
        {
          company: "丙公司",
          adapter: "workday",
          reportedTotal: 100,
          fetched: 120,
          coveragePct: 100,
          lastRunAt: "2026-07-07T03:00:00Z",
        },
      ],
    },
  );
});

test("getCoverageSnapshot calls the Supabase RPC and normalizes its response", async () => {
  assert.equal(typeof H.getCoverageSnapshot, "function");
  const calls = [];
  const result = await H.getCoverageSnapshot({
    rpc: async (name) => {
      calls.push(name);
      return {
        data: {
          measurable: 1,
          blind: 0,
          avg_coverage_pct: 55,
          under_count: 1,
          under_sources: [
            {
              company: "甲公司",
              adapter: "moka",
              reported_total: 100,
              fetched: 55,
              coverage_pct: 55,
              last_run_at: "2026-07-07T02:00:00Z",
            },
          ],
        },
        error: null,
      };
    },
  });

  assert.deepEqual(calls, ["crawl_coverage_snapshot"]);
  assert.equal(result.avgCoveragePct, 55);
  assert.deepEqual(result.underSources.map((source) => [source.company, source.coveragePct]), [["甲公司", 55]]);
});

test("getCoverageSnapshot returns an empty state instead of throwing on RPC failure", async () => {
  const originalError = console.error;
  console.error = () => {};
  try {
    const result = await H.getCoverageSnapshot({
      rpc: async () => ({ data: null, error: { message: "missing function" } }),
    });
    assert.deepEqual(result, {
      measurable: 0,
      blind: 0,
      avgCoveragePct: null,
      underCount: 0,
      underSources: [],
    });
  } finally {
    console.error = originalError;
  }
});

test("normalizeMustApplyFetchCoverage classifies must-apply fetch coverage without inventing missing totals", () => {
  assert.equal(typeof H.normalizeMustApplyFetchCoverage, "function");
  assert.deepEqual(
    H.normalizeMustApplyFetchCoverage({
      measurable: "3",
      blind: 1,
      fully_fetched: 2,
      avg_pct: 72,
      companies: [
        {
          name: "%腾讯%",
          pattern: "%腾讯%",
          reported_total: 100,
          fetched: 90,
          coverage_pct: 90,
          measurable: true,
        },
        {
          name: "%字节%",
          pattern: "%字节%",
          reported_total: 40,
          fetched: 60,
          coverage_pct: 150,
          measurable: true,
        },
        {
          name: "%阿里%",
          pattern: "%阿里%",
          reported_total: 0,
          fetched: 3,
          coverage_pct: null,
          measurable: true,
        },
        {
          name: "%美团%",
          pattern: "%美团%",
          reported_total: null,
          fetched: 7,
          coverage_pct: null,
          measurable: false,
        },
      ],
    }),
    {
      total: 4,
      measurable: 3,
      blind: 1,
      fullyFetched: 2,
      avgPct: 72,
      companies: [
        {
          name: "腾讯",
          pattern: "%腾讯%",
          reportedTotal: 100,
          fetched: 90,
          coveragePct: 90,
          measurable: true,
          lastRunAt: null,
        },
        {
          name: "字节跳动",
          pattern: "%字节%",
          reportedTotal: 40,
          fetched: 60,
          coveragePct: 100,
          measurable: true,
          lastRunAt: null,
        },
        {
          name: "阿里巴巴",
          pattern: "%阿里%",
          reportedTotal: 0,
          fetched: 3,
          coveragePct: null,
          measurable: true,
          lastRunAt: null,
        },
        {
          name: "美团",
          pattern: "%美团%",
          reportedTotal: null,
          fetched: 7,
          coveragePct: null,
          measurable: false,
          lastRunAt: null,
        },
      ],
    },
  );
});

test("getMustApplyFetchCoverage passes deduplicated cross-industry patterns to the RPC and fails open", async () => {
  assert.equal(typeof H.getMustApplyFetchCoverage, "function");
  const calls = [];
  const result = await H.getMustApplyFetchCoverage({
    rpc: async (name, args) => {
      calls.push({ name, args });
      return {
        data: {
          measurable: 2,
          blind: 28,
          fully_fetched: 1,
          avg_pct: 62,
          companies: [
            {
              name: "%字节%",
              pattern: "%字节%",
              reported_total: 100,
              fetched: 34,
              coverage_pct: 34,
              measurable: true,
            },
            {
              name: "%腾讯%",
              pattern: "%腾讯%",
              reported_total: 80,
              fetched: 72,
              coverage_pct: 90,
              measurable: true,
            },
          ],
        },
        error: null,
      };
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, "must_apply_coverage");
  assert.ok(calls[0].args.patterns.length > 30);
  assert.equal(new Set(calls[0].args.patterns).size, calls[0].args.patterns.length);
  assert.deepEqual(calls[0].args.patterns.slice(0, 2), ["%字节%", "%腾讯%"]);
  assert.equal(result.total, 2);
  assert.equal(result.measurable, 2);
  assert.equal(result.fullyFetched, 1);
  assert.deepEqual(result.companies.map((company) => [company.name, company.coveragePct]), [
    ["字节跳动", 34],
    ["腾讯", 90],
  ]);

  const originalError = console.error;
  console.error = () => {};
  try {
    const failed = await H.getMustApplyFetchCoverage({
      rpc: async () => ({ data: null, error: { message: "missing function" } }),
    });
    assert.deepEqual(failed, {
      total: calls[0].args.patterns.length,
      measurable: 0,
      blind: calls[0].args.patterns.length,
      fullyFetched: 0,
      avgPct: null,
      companies: [],
    });
  } finally {
    console.error = originalError;
  }
});

test("getMustApplyFetchCoverage uses overseas patterns only when scope is overseas", async () => {
  const calls = [];
  await H.getMustApplyFetchCoverage({
    rpc: async (name, args) => {
      calls.push({ name, args });
      return { data: null, error: null };
    },
  }, "overseas");
  assert.equal(calls[0].name, "must_apply_coverage");
  assert.ok(calls[0].args.patterns.includes("%Google%"));
  assert.ok(!calls[0].args.patterns.includes("%字节%"));
});

test("groupFetchCoverageByIndustry includes cross-industry companies in every requested industry", () => {
  assert.equal(typeof H.groupFetchCoverageByIndustry, "function");
  const grouped = H.groupFetchCoverageByIndustry(
    {
      total: 2,
      measurable: 1,
      blind: 1,
      fullyFetched: 1,
      avgPct: 90,
      companies: [
        { name: "蔚来", pattern: "%蔚来%", reportedTotal: 10, fetched: 9, coveragePct: 90, measurable: true, lastRunAt: null },
        { name: "腾讯", pattern: "%腾讯%", reportedTotal: null, fetched: 0, coveragePct: null, measurable: false, lastRunAt: null },
      ],
    },
    ["互联网/科技", "汽车/出行"],
  );
  assert.equal(grouped["互联网/科技"].total, 30);
  assert.equal(grouped["汽车/出行"].total, 30);
  assert.deepEqual(grouped["互联网/科技"].companies.map((company) => company.name), ["蔚来", "腾讯"]);
  assert.deepEqual(grouped["汽车/出行"].companies.map((company) => company.name), ["蔚来"]);
  assert.equal(grouped["汽车/出行"].fullyFetched, 1);
});

test("groupFetchCoverageByIndustry groups overseas patterns with overseas totals", () => {
  const grouped = H.groupFetchCoverageByIndustry(
    {
      total: 1,
      measurable: 1,
      blind: 0,
      fullyFetched: 1,
      avgPct: 90,
      companies: [
        { name: "Google", pattern: "%Google%", reportedTotal: 10, fetched: 9, coveragePct: 90, measurable: true, lastRunAt: null },
      ],
    },
    ["互联网/科技"],
    "overseas",
  );
  assert.equal(grouped["互联网/科技"].total, 30);
  assert.deepEqual(grouped["互联网/科技"].companies.map((company) => company.name), ["Google"]);
});

test("buildDailyReports merges technical runs into six human-facing operation cards", () => {
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
      {
        module: "auto_discover",
        runs: 1,
        success: 1,
        partial: 0,
        failed: 0,
        checked: 30,
        expired: 0,
        deleted: 0,
        enriched: 0,
        companies_enriched: 1,
        retired: 0,
        last_run_at: "2026-06-22T09:00:00Z",
      },
      {
        module: "auto_discover_browser",
        runs: 1,
        success: 1,
        partial: 0,
        failed: 0,
        checked: 60,
        expired: 0,
        deleted: 0,
        enriched: 0,
        companies_enriched: 2,
        retired: 0,
        last_run_at: "2026-06-22T09:30:00Z",
      },
    ],
  });

  assert.deepEqual(reports.map((report) => report.title), [
    "岗位抓取",
    "详情补全",
    "死岗治理",
    "职业洞察",
    "自动扩源",
    "刷新 / 发现",
  ]);
  assert.deepEqual(
    reports.find((report) => report.key === "auto_discover").metrics.map((metric) => [metric.label, metric.value]),
    [["探查公司", 90], ["新增源", 3]],
  );
  assert.equal(reports.find((report) => report.key === "auto_discover").status, "success");
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

test("crawl coverage snapshot uses latest enabled Supabase crawl runs and hides execution from users", () => {
  const migrationPath = path.join(
    __dirname,
    "..",
    "supabase",
    "migrations",
    "177_coverage_snapshot.sql",
  );
  const migration = fs.existsSync(migrationPath) ? fs.readFileSync(migrationPath, "utf8") : "";
  assert.match(migration, /create or replace function public\.crawl_coverage_snapshot\(\)/i);
  assert.match(migration, /security definer/i);
  assert.match(migration, /distinct on \(cr\.source_id\)/i);
  assert.match(migration, /where s\.enabled = true/i);
  assert.match(migration, /reported_total/i);
  assert.match(migration, /jobs_found/i);
  assert.match(migration, /least\(100/i);
  assert.match(migration, /coverage_pct asc/i);
  assert.match(migration, /limit 40/i);
  assert.match(migration, /revoke execute on function public\.crawl_coverage_snapshot\(\) from public, anon, authenticated/i);
  assert.match(migration, /grant execute on function public\.crawl_coverage_snapshot\(\) to service_role/i);
});

test("must-apply coverage snapshot accepts patterns, merges latest enabled source runs, and is service-role only", () => {
  const migrationPath = path.join(
    __dirname,
    "..",
    "supabase",
    "migrations",
    "178_must_apply_coverage.sql",
  );
  const migration = fs.existsSync(migrationPath) ? fs.readFileSync(migrationPath, "utf8") : "";
  assert.match(migration, /create or replace function public\.must_apply_coverage\(patterns text\[\]\)/i);
  assert.match(migration, /security definer/i);
  assert.match(migration, /unnest\(patterns\) with ordinality/i);
  assert.match(migration, /s\.company ilike r\.pattern/i);
  assert.match(migration, /where s\.enabled = true/i);
  assert.match(migration, /distinct on \(matched\.idx, matched\.source_id\)/i);
  assert.match(migration, /sum\(reported_total\)/i);
  assert.match(migration, /sum\(fetched\)/i);
  assert.match(migration, /least\(100/i);
  assert.match(migration, /coverage_pct asc/i);
  assert.match(migration, /fully_fetched/i);
  assert.match(migration, /revoke execute on function public\.must_apply_coverage\(text\[\]\) from public, anon, authenticated/i);
  assert.match(migration, /grant execute on function public\.must_apply_coverage\(text\[\]\) to service_role/i);
  assert.doesNotMatch(migration, /字节|腾讯|阿里|美团|拼多多/);
});

test("admin health page authenticates before parallel cross-database reads and renders plain-language sections", () => {
  const pagePath = path.join(__dirname, "..", "app", "admin", "health", "page.tsx");
  const source = fs.existsSync(pagePath) ? fs.readFileSync(pagePath, "utf8") : "";
  assert.match(source, /await isAdmin\(\)/);
  assert.match(source, /redirect\("\/"\)/);
  assert.ok(source.indexOf("await isAdmin()") < source.indexOf("Promise.allSettled"));
  assert.match(source, /getJobsHealthSnapshot/);
  assert.match(source, /\.rpc\("admin_health_snapshot",\s*\{\s*p_window:\s*"7 days"\s*\}\)/s);
  assert.match(source, /Promise\.allSettled/);
  assert.match(source, /今日健康/);
  assert.match(source, /管理员看板/);
  assert.match(source, /两周冲刺 · 用户闭环/);
  assert.match(source, /数据口径说明/);
  assert.match(source, /id="user-loop"/);
  assert.match(source, /id="must-apply-supply"/);
  assert.match(source, /id="jobs-quality"/);
  assert.match(source, /id="system-ops"/);
  assert.match(source, /用户闭环/);
  assert.match(source, /必投供给/);
  assert.match(source, /岗位质量/);
  assert.match(source, /系统运行/);
  assert.match(source, /展示岗位自动探活（非用户点击统计）/);
  assert.match(source, /抓全率（覆盖不足的原因诊断）/);
  assert.match(source, /官网总数/);
  assert.match(source, /我们抓到/);
  assert.match(source, /盲区/);
  assert.match(source, /buildDailyReports/);
  assert.match(source, /零结果搜索率/);
  assert.match(source, /洞察抽屉打开率/);
  assert.match(source, /积累中/);
  assert.doesNotMatch(source, /expired 占全库|removed 占全库|active 从未探活|>Source<|>Adapter<|>Partial</);
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
