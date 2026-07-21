-- ============================================================
-- 校招洞察 P2：招聘周期观测表（结构化事实底座，可版本化、绑届别、留证据）
-- 唯一结构化真相源；insight_items timing 散文洞察不受影响、不反向同步。
-- 不变量：事实字段 immutable（改错=新增 + superseded_by），仅 verify_status/
--   valid_until/superseded_by/updated_at 可改，由 admin API 写路径强制。
-- ============================================================

create table recruitment_cycle_observations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references company_profiles(id) on delete cascade,
  grad_class text not null,                         -- 毕业届别，如 "2027届"（据往年必绑此）
  season text not null check (season in ('秋招','春招')),
  batch text not null check (batch in ('提前批','正式批','补录','实习转正')),
  event text not null check (event in ('开放','截止','黄金期','结束')),
  time_expr_type text not null check (time_expr_type in ('精确日期','日期范围','月','历史规律')),
  value_text text not null,                         -- 展示串："约7月" / "8-9月" / "全年滚动"
  month_start smallint check (month_start between 1 and 12),
  month_end smallint check (month_end between 1 and 12),
  date_start date,                                  -- 仅 time_expr_type='精确日期'（P3）
  date_end date,
  confidence text not null default 'medium' check (confidence in ('high','medium','low')),
  evidence_url text,
  evidence_excerpt text,                            -- 证据短摘要，禁整段原文
  evidence_fetched_at timestamptz,
  source_kind text,                                 -- official_site/official_notice/manual_curation/llm_draft/public_aggregate
  verify_status text not null default 'draft' check (verify_status in ('draft','verified','rejected')),
  valid_until date,
  superseded_by uuid references recruitment_cycle_observations(id),
  created_by text,                                  -- admin email / 'seed' / 'llm'
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_rco_company_verify_valid
  on recruitment_cycle_observations(company_id, verify_status, valid_until);
create index idx_rco_grad_class on recruitment_cycle_observations(grad_class);

alter table recruitment_cycle_observations enable row level security;

-- 读：仅 verified 且未过期（宁缺不编）
create policy "Authenticated users can read verified cycles"
  on recruitment_cycle_observations for select
  using (
    auth.role() = 'authenticated'
    and verify_status = 'verified'
    and (valid_until is null or valid_until >= current_date)
  );

-- 写：仅 admin（service_role 绕 RLS，另走）
create policy "Admins can write cycles"
  on recruitment_cycle_observations for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
