#!/usr/bin/env node
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import pg from "pg";
import tlsOptions from "../lib/jobs-store/tls-options.js";

const { Client } = pg;
const { buildJobsDatabaseSsl } = tlsOptions;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function connectionConfig(url, { jobsDatabase = false } = {}) {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: parsed.port ? Number(parsed.port) : 5432,
    user: decodeURIComponent(parsed.username),
    password: decodeURIComponent(parsed.password),
    database: parsed.pathname.replace(/^\//, ""),
    ssl: jobsDatabase
      ? buildJobsDatabaseSsl(process.env, parsed.hostname)
      : { rejectUnauthorized: true },
    connectionTimeoutMillis: 10_000,
    statement_timeout: 30_000,
  };
}

function asNumber(value) {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

const checks = [];
function check(name, dashboardValue, rawValue, { silent = false } = {}) {
  const dashboard = asNumber(dashboardValue);
  const raw = asNumber(rawValue);
  const ok = dashboard === raw;
  checks.push({ name, ok, dashboard, raw });
  if (!silent || !ok) {
    console.log(`${ok ? "[PASS]" : "[FAIL]"} ${name}: 看板=${dashboard} 真实=${raw}`);
  }
}

function byModule(rows) {
  return new Map((rows || []).map((row) => [row.module, row]));
}

async function main() {
  const supabaseUrl = process.env.SUPABASE_DB_URL;
  const jobsUrl = process.env.JOBS_DATABASE_URL;
  if (!supabaseUrl || !jobsUrl) {
    throw new Error("需要 SUPABASE_DB_URL 与 JOBS_DATABASE_URL（请先加载本地环境变量）");
  }

  const supabase = new Client(connectionConfig(supabaseUrl));
  const jobs = new Client(connectionConfig(jobsUrl, { jobsDatabase: true }));
  await Promise.all([supabase.connect(), jobs.connect()]);

  try {
    await supabase.query("BEGIN");
    const migration = fs.readFileSync(
      path.join(root, "supabase", "migrations", "159_admin_ops_dashboard.sql"),
      "utf8",
    );
    await supabase.query(migration);

    const { rows: snapshotRows } = await supabase.query(
      "select public.admin_health_snapshot(interval '7 days') as snapshot",
    );
    const { rows: supabaseRawRows } = await supabase.query(`
          with b as (
            select date_trunc('day', now() at time zone 'Asia/Shanghai')
              at time zone 'Asia/Shanghai' as today_start
          )
          select
            (select count(*) from crawl_runs cr, b where cr.started_at >= b.today_start) as crawl_runs,
            (select coalesce(sum(jobs_found), 0) from crawl_runs cr, b where cr.started_at >= b.today_start) as crawl_found,
            (select coalesce(sum(jobs_created), 0) from crawl_runs cr, b where cr.started_at >= b.today_start) as crawl_created,
            (select coalesce(sum(jobs_updated), 0) from crawl_runs cr, b where cr.started_at >= b.today_start) as crawl_updated,
            (select count(*) from crawl_runs cr, b where cr.started_at >= b.today_start and cr.status = 'failed') as crawl_failed,
            (select count(distinct source_id) from crawl_runs cr, b where cr.started_at >= b.today_start and cr.status = 'failed') as crawl_failed_sources,
            (select count(*) from discovery_runs dr, b where dr.created_at >= b.today_start) as discovery_runs,
            (select coalesce(sum(jobs_created), 0) from discovery_runs dr, b where dr.created_at >= b.today_start) as discovery_created,
            (select coalesce(sum(jobs_updated), 0) from discovery_runs dr, b where dr.created_at >= b.today_start) as discovery_updated,
            (select count(*) from discovery_runs dr, b where dr.created_at >= b.today_start and dr.status = 'failed') as discovery_failed,
            (select count(*) from profiles) as total_users,
            (select count(*) from profiles p, b where p.created_at >= b.today_start) as today_users,
            (select count(distinct user_id) from user_preferences) as users_with_preferences,
            (select count(*) from job_actions where action = 'saved') as saved_total,
            (select count(*) from job_actions ja, b where ja.action = 'saved' and ja.created_at >= b.today_start) as saved_today,
            (select count(*) from job_actions where action = 'applied') as applied_total,
            (select count(*) from job_actions ja, b where ja.action = 'applied' and ja.created_at >= b.today_start) as applied_today,
            (select count(*) from insight_items where status = 'active') as insight_active,
            (select count(*) from insight_items ii, b where ii.created_at >= b.today_start) as insight_created,
            (select count(*) from insight_disputes where status = 'open') as disputes_open,
            (select count(*) from insight_disputes) as disputes_total,
            (select count(*) from events e, b where e.created_at >= b.today_start and e.event = 'resume_parse_started') as resume_started,
            (select count(*) from events e, b where e.created_at >= b.today_start and e.event = 'resume_parse_succeeded') as resume_succeeded,
            (select count(*) from events e, b where e.created_at >= b.today_start and e.event = 'resume_parse_succeeded'
              and e.payload #>> '{diagnostics,source}' = 'llm') as resume_llm,
            (select count(*) from events e, b where e.created_at >= b.today_start and e.event = 'resume_parse_succeeded'
              and e.payload #>> '{diagnostics,source}' = 'rule') as resume_rule
        `);
    const { rows: rawOpsRows } = await supabase.query(`
          select
            module,
            count(*)::int as runs,
            count(*) filter (where status = 'success')::int as success,
            count(*) filter (where status = 'partial')::int as partial,
            count(*) filter (where status = 'failed')::int as failed,
            coalesce(sum(case when jsonb_typeof(metrics -> 'checked') = 'number'
              then (metrics ->> 'checked')::int else 0 end), 0)::int as checked,
            coalesce(sum(case when jsonb_typeof(metrics -> 'expired') = 'number'
              then (metrics ->> 'expired')::int else 0 end), 0)::int as expired,
            coalesce(sum(case when jsonb_typeof(metrics -> 'deleted') = 'number'
              then (metrics ->> 'deleted')::int else 0 end), 0)::int as deleted,
            coalesce(sum(case when jsonb_typeof(metrics -> 'enriched') = 'number'
              then (metrics ->> 'enriched')::int else 0 end), 0)::int as enriched,
            coalesce(sum(case when jsonb_typeof(metrics -> 'companies_enriched') = 'number'
              then (metrics ->> 'companies_enriched')::int else 0 end), 0)::int as companies_enriched,
            coalesce(sum(case when jsonb_typeof(metrics -> 'retired') = 'number'
              then (metrics ->> 'retired')::int else 0 end), 0)::int as retired
          from ops_runs
          where run_date = (now() at time zone 'Asia/Shanghai')::date
          group by module
          order by module
        `);
    const { rows: rawSourceRows } = await supabase.query(`
          with b as (select now() - interval '7 days' as since_at)
          select
            s.id::text as source_id,
            count(cr.id)::int as runs,
            count(*) filter (where cr.status = 'success')::int as success,
            count(*) filter (where cr.status = 'partial_success')::int as partial_success,
            count(*) filter (where cr.status = 'failed')::int as failed,
            count(*) filter (where cr.status = 'skipped')::int as skipped
          from sources s
          cross join b
          left join crawl_runs cr on cr.source_id = s.id and cr.started_at >= b.since_at
          where s.enabled = true
          group by s.id
          order by s.id
        `);

    const snapshot = snapshotRows[0].snapshot;
    const raw = supabaseRawRows[0];
    const today = snapshot.today;

    check("岗位抓取.运行次数", today.crawl.runs, raw.crawl_runs);
    check("岗位抓取.抓到岗位", today.crawl.jobs_found, raw.crawl_found);
    check("岗位抓取.新增岗位", today.crawl.jobs_created, raw.crawl_created);
    check("岗位抓取.更新岗位", today.crawl.jobs_updated, raw.crawl_updated);
    check("岗位抓取.失败运行", today.crawl.failed_runs, raw.crawl_failed);
    check("岗位抓取.失败来源", today.crawl.failed_sources, raw.crawl_failed_sources);
    check("刷新发现.运行次数", today.discovery.runs, raw.discovery_runs);
    check("刷新发现.新增岗位", today.discovery.jobs_created, raw.discovery_created);
    check("刷新发现.更新岗位", today.discovery.jobs_updated, raw.discovery_updated);
    check("刷新发现.失败运行", today.discovery.failed_runs, raw.discovery_failed);

    const users = today.users;
    check("用户.总数", users.total_users, raw.total_users);
    check("用户.今日新注册", users.today_users, raw.today_users);
    check("用户.已设偏好", users.users_with_preferences, raw.users_with_preferences);
    check("收藏.总量", users.saved_total, raw.saved_total);
    check("收藏.今日", users.saved_today, raw.saved_today);
    check("投递.总量", users.applied_total, raw.applied_total);
    check("投递.今日", users.applied_today, raw.applied_today);
    check("洞察.可用总量", snapshot.insight.active_total, raw.insight_active);
    check("洞察.今日新增", snapshot.insight.today_created, raw.insight_created);
    check("申诉.待处理", snapshot.insight.disputes_open, raw.disputes_open);
    check("申诉.累计", snapshot.insight.disputes_total, raw.disputes_total);
    check("简历.今日解析", today.resume.started, raw.resume_started);
    check("简历.今日成功", today.resume.succeeded, raw.resume_succeeded);
    check("简历.智能解析", today.resume.llm, raw.resume_llm);
    check("简历.规则解析", today.resume.rule, raw.resume_rule);

    const snapshotOps = byModule(today.ops_runs);
    const rawOps = byModule(rawOpsRows);
    const modules = new Set([...snapshotOps.keys(), ...rawOps.keys()]);
    for (const module of modules) {
      const dashboardRow = snapshotOps.get(module) || {};
      const rawRow = rawOps.get(module) || {};
      for (const key of [
        "runs",
        "success",
        "partial",
        "failed",
        "checked",
        "expired",
        "deleted",
        "enriched",
        "companies_enriched",
        "retired",
      ]) {
        check(`台账.${module}.${key}`, dashboardRow[key], rawRow[key]);
      }
    }

    const snapshotSources = new Map((snapshot.crawl_sources || []).map((row) => [row.source_id, row]));
    const sourceCheckStart = checks.length;
    for (const row of rawSourceRows) {
      const dashboardRow = snapshotSources.get(row.source_id) || {};
      for (const key of ["runs", "success", "partial_success", "failed", "skipped"]) {
        check(`招聘源.${row.source_id}.${key}`, dashboardRow[key], row[key], { silent: true });
      }
    }
    const sourceChecks = checks.slice(sourceCheckStart);
    const sourceFailures = sourceChecks.filter((item) => !item.ok);
    console.log(
      `${sourceFailures.length ? "[FAIL]" : "[PASS]"} 招聘源近 7 天：`
        + `${sourceChecks.length - sourceFailures.length}/${sourceChecks.length} 个字段一致`,
    );

    const { rows: jobsDashboardRows } = await jobs.query(`
        with bounds as (
          select date_trunc('day', now() at time zone 'Asia/Shanghai')
            at time zone 'Asia/Shanghai' as today_start
        )
        select
          count_valid_active_jobs() as valid_active,
          count(*) filter (where first_seen_at >= bounds.today_start) as today_new,
          count(*) filter (where last_seen_at >= bounds.today_start and first_seen_at < bounds.today_start) as today_updated,
          count(*) filter (where status = 'active') as active_total,
          count(*) filter (where status = 'expired') as expired,
          count(*) filter (where status = 'removed') as removed,
          count(*) as total,
          count(*) filter (where status = 'active' and enrich_checked_at is null) as never_checked
        from jobs cross join bounds
      `);
    const { rows: jobsRawRows } = await jobs.query(`
        with b as (
          select date_trunc('day', now() at time zone 'Asia/Shanghai')
            at time zone 'Asia/Shanghai' as today_start
        )
        select
          (select count_valid_active_jobs()) as valid_active,
          (select count(*) from jobs, b where first_seen_at >= b.today_start) as today_new,
          (select count(*) from jobs, b where last_seen_at >= b.today_start and first_seen_at < b.today_start) as today_updated,
          (select count(*) from jobs where status = 'active') as active_total,
          (select count(*) from jobs where status = 'active'
            and (summary is null or char_length(btrim(summary)) < 60)) as thin_active,
          (select count(*) from jobs where status = 'expired') as expired,
          (select count(*) from jobs where status = 'removed') as removed,
          (select count(*) from jobs) as total,
          (select count(*) from jobs where status = 'active' and enrich_checked_at is null) as never_checked
      `);
    const jobsDashboard = jobsDashboardRows[0];
    const jobsRaw = jobsRawRows[0];
    for (const key of [
      "valid_active",
      "today_new",
      "today_updated",
      "active_total",
      "expired",
      "removed",
      "total",
      "never_checked",
    ]) {
      check(`岗位库.${key}`, jobsDashboard[key], jobsRaw[key]);
    }
    check(
      "岗位库.thin_active",
      asNumber(jobsDashboard.active_total) - asNumber(jobsDashboard.valid_active),
      jobsRaw.thin_active,
    );

    const failed = checks.filter((item) => !item.ok);
    console.log(`\n核对完成：${checks.length - failed.length}/${checks.length} 项一致。`);
    if (failed.length) {
      process.exitCode = 1;
    }
  } finally {
    try {
      await supabase.query("ROLLBACK");
    } finally {
      await Promise.allSettled([supabase.end(), jobs.end()]);
    }
  }
}

main().catch((error) => {
  console.error(`[verify-admin-health] ${error.message}`);
  process.exitCode = 1;
});
