-- ============================================================
-- 135 — 职业洞察 v2「机器验证 + 三层供给」schema 扩展
-- ============================================================
-- 设计见 docs/superpowers/specs/2026-06-12-career-insights-overhaul-design.md §10。
-- 全部幂等（add column if not exists / drop+add CHECK）。push 后由 migrate.yml 自动应用。

-- 1) insight_items：provenance（来源层）+ 机器验证审计 + pending_review 边缘队列状态
alter table insight_items add column if not exists origin text not null default 'manual';
  -- 取值：'derived'（T1 派生）| 'wikidata' | 'official'（官方页）| 'public_web'（T3 公开聚合）| 'manual'（人工/admin）
alter table insight_items add column if not exists verification jsonb;
  -- 机器验证审计：{ judge_verdict, confidence, spans:[{url,quote}] }，留痕可追溯

-- status CHECK 加 'pending_review'（判官矛盾/低置信的边缘案例先落库；
-- RLS public read 仍只放行 status='active' AND deidentified=true，故 pending_review 不展示给用户）
alter table insight_items drop constraint if exists insight_items_status_check;
alter table insight_items
  add constraint insight_items_status_check
  check (status in ('active', 'disputed', 'retired', 'pending_review'));

-- dimension CHECK 加 'hiring'（T1 派生维度。当前 read-time 不落库，但留枚举以备物化/admin 兼容）
alter table insight_items drop constraint if exists insight_items_dimension_check;
alter table insight_items
  add constraint insight_items_dimension_check
  check (dimension in (
    'timing', 'hiring', 'listing', 'compensation_intensity', 'path', 'culture'
  ));

-- origin CHECK（白名单，防脏值）
alter table insight_items drop constraint if exists insight_items_origin_check;
alter table insight_items
  add constraint insight_items_origin_check
  check (origin in ('derived', 'wikidata', 'official', 'public_web', 'manual'));

-- 2) company_profiles：官方事实字段（T2 Wikidata/官方页回填）+ 富化调度列（仿 migration 133 jobs 的 enrich 调度）
alter table company_profiles add column if not exists founded_year int;
alter table company_profiles add column if not exists headcount_band text;  -- 规模档，如 "10001-50000"
alter table company_profiles add column if not exists funding_stage text;   -- 如 "已上市" / "未上市" / "D轮"
alter table company_profiles add column if not exists hq_location text;      -- 总部，如 "杭州" / "深圳"
alter table company_profiles add column if not exists insight_checked_at timestamptz;  -- 富化调度去重（null=待处理）
alter table company_profiles add column if not exists insight_fail_count int not null default 0;  -- 死信计数

-- 队列扫描部分索引：待富化（insight_checked_at 为空优先）+ 未超死信，worker 用 WHERE 取队列走这条
create index if not exists idx_company_profiles_insight_queue
  on company_profiles (insight_checked_at nulls first)
  where insight_fail_count < 3;
