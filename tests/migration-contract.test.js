// 迁移契约测试（§9.2）：静态校验 161/162/163 含关键 DDL，防止有人改坏迁移导致写路径在生产失效。
// 不连库；只读 .sql 文件断言。归一为「小写 + 折叠空白」后做子串断言，容忍格式微调。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const DIR = path.join(__dirname, "..", "supabase", "migrations");
const norm = (f) => fs.readFileSync(path.join(DIR, f), "utf8").toLowerCase().replace(/\s+/g, " ");

test("161 建立 radar state + 通知设置 + RLS", () => {
  const s = norm("161_radar_state_and_notification_settings.sql");
  assert.ok(s.includes("create table if not exists user_radar_state"));
  assert.ok(s.includes("last_opened_at"));
  assert.ok(s.includes("create table if not exists notification_settings"));
  assert.ok(s.includes("email_digest_enabled"));
  assert.ok(s.includes("enable row level security"));
});

test("162 删跨库 FK + 负反馈/快照列 + set_job_primary_action RPC", () => {
  const s = norm("162_job_action_feedback.sql");
  assert.ok(s.includes("drop constraint if exists job_actions_job_id_fkey"));
  assert.ok(s.includes("add column if not exists reason_code"));
  assert.ok(s.includes("add column if not exists job_snapshot"));
  assert.ok(s.includes("alter column job_id set not null"));
  assert.ok(s.includes("create or replace function public.set_job_primary_action"));
  assert.ok(s.includes("security definer"));
  // 只授权 authenticated 执行 RPC
  assert.ok(/grant execute on function public\.set_job_primary_action[^;]*to authenticated/.test(s));
});

test("163 建立 company_watch_requests + 唯一约束 + RLS", () => {
  const s = norm("163_company_watch_requests.sql");
  assert.ok(s.includes("create table if not exists company_watch_requests"));
  assert.ok(s.includes("normalized_company"));
  assert.ok(s.includes("unique (user_id, normalized_company)"));
  assert.ok(s.includes("enable row level security"));
  // 不给 authenticated 写策略（写走 service role）—— 只应有 select 策略
  assert.ok(s.includes("for select"));
  assert.ok(!/for (insert|update|delete)/.test(s));
});

test("164 加雷达强度三列（active/passive + source + updated_at）幂等；无 radar_mode", () => {
  const s = norm("164_radar_intensity.sql");
  assert.ok(s.includes("add column if not exists radar_intensity text"));
  assert.ok(s.includes("radar_intensity in ('active', 'passive')"));
  assert.ok(s.includes("add column if not exists radar_intensity_source text"));
  assert.ok(s.includes("radar_intensity_source in ('default', 'user', 'auto')"));
  assert.ok(s.includes("add column if not exists radar_intensity_updated_at timestamptz"));
  // 反向：不得引入 radar_mode（v3 不走三模式老路）
  assert.ok(!s.includes("radar_mode"));
});

test("165 建立洞察现查台账索引 + 月度招聘聚合表", () => {
  const s = norm("165_insight_enrich_now_and_hiring_monthly.sql");
  assert.ok(s.includes("create table if not exists company_hiring_monthly"));
  assert.ok(s.includes("primary key (company, ym)"));
  assert.ok(s.includes("posted_count integer not null default 0"));
  assert.ok(s.includes("check (ym ~ '^\\d{4}-\\d{2}$')"));
  assert.ok(s.includes("grant select on table company_hiring_monthly to authenticated"));
  assert.ok(s.includes("create index if not exists idx_discovery_runs_insight_enrich_recent"));
  assert.ok(s.includes("where mode = 'insight_enrich'"));
});
