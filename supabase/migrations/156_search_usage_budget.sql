-- ============================================================
-- 156 — 多源搜索层：各 provider 每日额度计数（T3 经验层供给升级）
-- ============================================================
-- 设计见 docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md（Phase 1）。
-- 全部幂等。push 后由 migrate.yml 自动应用。
--
-- T3 检索从单一千帆扩为多源（博查/Tavily/Serper/千帆，crawler/search_router.py）。每个付费源
-- 用 search_usage 做**跨 CI run 持久**的当日计数，绝不冲破各自日顶（*_DAILY_CAP env）→ 成本可控。
-- 千帆继续用既有 qianfan_usage（137），向后兼容；新源走本表。

-- 各 provider 当日调用计数（按 provider + UTC 日期一行；worker 读+增，超 cap 即停）
create table if not exists search_usage (
  provider text not null,
  day date not null,
  used int not null default 0,
  updated_at timestamptz not null default now(),
  primary key (provider, day)
);
alter table search_usage enable row level security;
-- 仅 service role 读写（worker 用 service key 绕 RLS）；不开放任何匿名/登录策略。
