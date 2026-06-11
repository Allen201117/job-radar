-- ============================================================
-- 137 — 职业洞察 T3 经验层：百度千帆每日额度计数 + T3 富化调度列
-- ============================================================
-- 设计见 docs/superpowers/specs/2026-06-12-career-insights-overhaul-design.md §6/§16。
-- 全部幂等。push 后由 migrate.yml 自动应用。
--
-- 千帆免费「百度搜索」每日 50 次额度（全局）。T3 worker 用 qianfan_usage 做**跨 CI run 持久**的
-- 当日计数，自封顶（QIANFAN_DAILY_CAP，默认 40，留余量给 /api/discovery 的交互用量），绝不冲破 50。

-- 千帆当日调用计数（按 UTC 日期一行；T3 worker 读+增，超 cap 即停）
create table if not exists qianfan_usage (
  day date primary key,
  used int not null default 0,
  updated_at timestamptz not null default now()
);
alter table qianfan_usage enable row level security;
-- 仅 service role 读写（worker 用 service key，绕 RLS）；不开放任何匿名/登录策略。

-- company_profiles：T3 富化调度列（仿 T2 的 insight_checked_at/insight_fail_count）
alter table company_profiles add column if not exists t3_checked_at timestamptz;     -- 空=待 T3 富化
alter table company_profiles add column if not exists t3_fail_count int not null default 0;  -- 死信

-- T3 队列扫描部分索引：待富化 + 未超死信（worker 取队列走这条）
create index if not exists idx_company_profiles_t3_queue
  on company_profiles (t3_checked_at nulls first)
  where t3_fail_count < 3;
