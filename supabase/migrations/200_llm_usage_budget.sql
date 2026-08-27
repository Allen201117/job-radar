-- ============================================================
-- 200 — LLM 调用每日额度计数（成本天花板）
-- ============================================================
-- 全部幂等。push 后由 migrate.yml 自动应用。
--
-- 背景：搜索侧早有 search_usage（迁移 156）做每日预算守门，**LLM 侧一个闸门都没有** → 花多少
-- 全看队列多长，没有天花板（线上实测 130~243 次/天，账户欠费三天才被发现）。本表给 LLM 装上
-- 同款「跨 CI run 持久」的当日计数：crawler/llm_budget.py 读+增，超 env LLM_DAILY_CAP 即跳过
-- 本次 LLM 调用（跳过、不报错，主任务照常跑完）。
--
-- 口径：天花板按「当日全部**非豁免** kind 的 used 之和」判，按 kind 分行只为归因（看钱花在哪条
-- 链上：insight_t3 / resume_parse / …）。豁免 kind（用户实时触发的链路）不计数也不写行。
create table if not exists llm_usage (
  kind text not null,
  day date not null,
  used int not null default 0,
  updated_at timestamptz not null default now(),
  primary key (kind, day)
);

-- 热路径是「按 day 取当日全部 kind 求和」，主键 (kind, day) 前导列不是 day → 单独给 day 建索引。
create index if not exists idx_llm_usage_day on llm_usage(day);

alter table llm_usage enable row level security;
-- 仅 service role 读写（worker 用 service key 绕 RLS）；不开放任何匿名/登录策略。
