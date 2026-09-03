-- 职业洞察 v3：主体（公司 × 业务线）+ 结构化断言
-- 设计见 docs/superpowers/specs/2026-09-03-insights-v3-scope-and-model.md
--
-- 为什么要这张表与这几列（创始人 2026-09-03 退回 v2 的原因）：
--   v2 把「公司」当匀质对象，用 LLM 把公开讨论写成一句公司级散文结论
--   （「腾讯音乐年终奖 10 个月」——哪个业务线？）。
--   同一家公司不同业务线的强度/薪酬/发展差异极大（字节 Seed vs 电商、腾讯混元 vs 游戏），
--   公司级平均值对求职者没有决策价值，还可能误导。
--   且散文没法索引 / 筛选 / 跨公司比较 / 按口径治理。
-- v3 = 主体下沉到「公司 × 业务线」+ 内容结构化成「带主体、带口径、带时点的断言」。

-- ── 1) 洞察主体：公司本身，或公司下的业务线 ─────────────────────────────
create table if not exists insight_subjects (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references company_profiles(id) on delete cascade,
  kind text not null check (kind in ('company', 'business_unit')),
  -- 展示名，如「飞书」「TikTok Shop」「OceanBase」「小米汽车」
  name text not null,
  aliases text[] not null default '{}',
  -- 主体是怎么来的：标题抽取 / 原始部门字段 / 官方披露 / 人工录入。
  -- derived_dept 比 derived_title 可信（京东 positionDeptName、网易 productName 已有先例）。
  origin text not null check (origin in ('derived_title', 'derived_dept', 'official', 'manual')),
  -- 当前在招岗数：既是展示排序依据，也是治理依据（归零 → retired）。
  job_count int not null default 0,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now(),
  -- rejected = 人工判定是噪声（如滴滴的「27届秋招」「产品实习生」被误抽成业务线）。
  -- ⚠️ 保留行不删：下次抽取据此跳过，这是治理入口，删了就会反复抽回来。
  status text not null default 'active' check (status in ('active', 'retired', 'rejected')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, name)
);

comment on table insight_subjects is
  '洞察主体：公司或其业务线。业务线由 crawler/bu_extract.py 从自有岗位库抽取（阈值+停用词+人工下架回路）。';

-- 抽屉按公司取主体、按在招岗数排序 → 这条索引直接服务该查询。
create index if not exists idx_insight_subjects_company
  on insight_subjects (company_id, status, job_count desc);
-- 抽取器复跑时按 origin 找出「上一轮抽出来的」做 last_seen/retire 对账。
create index if not exists idx_insight_subjects_origin
  on insight_subjects (origin, status);

-- ── 2) insight_items 结构化：主体 / 断言强度 / 指标 ────────────────────
alter table insight_items
  add column if not exists subject_id uuid references insight_subjects(id) on delete set null,
  add column if not exists assertion text,
  add column if not exists metric_key text,
  add column if not exists metric_value numeric,
  add column if not exists metric_unit text,
  add column if not exists scope jsonb not null default '{}'::jsonb;

comment on column insight_items.subject_id is 'NULL = 公司级；非空 = 该业务线级。';
comment on column insight_items.assertion is
  'fact=官方/第一方可核验事实；signal=自有岗位库算出的观测量（只给数字不下结论）；claim=公开讨论的说法（必须带范围+时间+≥2 来源域名才展示）。';
comment on column insight_items.metric_key is
  '枚举化指标名，见 spec §3.3。有值即可跨公司/业务线索引、筛选、比较，并按 key 做口径治理。';

-- 断言强度白名单。存量行 assertion 为 NULL（P0-5 回填），故不加 not null。
alter table insight_items drop constraint if exists insight_items_assertion_check;
alter table insight_items
  add constraint insight_items_assertion_check
  check (assertion is null or assertion in ('fact', 'signal', 'claim'));

-- metric_key 白名单：可增不可乱改（改了等于改口径）。新增指标必须同步 spec §3.3。
alter table insight_items drop constraint if exists insight_items_metric_key_check;
alter table insight_items
  add constraint insight_items_metric_key_check
  check (metric_key is null or metric_key in (
    -- 组织规模（fact：年报 / signal：第一方）
    'headcount_total', 'headcount_tech_ratio', 'edu_bachelor_plus_ratio', 'edu_master_plus_ratio',
    'bu_count', 'bu_job_count',
    -- 招聘动态（signal：全部来自自有岗位库）
    'hiring_volume_30d', 'hiring_trend_30d_pct', 'hiring_trend_90d_pct', 'open_age_days_median',
    'city_share', 'function_share', 'bucket_share',
    -- 门槛（fact：JD 明写字段）
    'exp_years_median', 'edu_requirement_mode',
    -- 薪酬
    'avg_comp_annual', 'salary_range_k', 'bonus_months',
    -- 强度与发展（claim）
    'overtime_level', 'promotion_pace', 'interview_rounds',
    -- 稳定性
    'hiring_freeze_signal', 'layoff_mention',
    -- 上市与业绩（fact）
    'listing_status', 'revenue_yoy'
  ));

-- 按主体取条目（抽屉的业务线卡片）。
create index if not exists idx_insight_items_subject
  on insight_items (subject_id, status) where subject_id is not null;
-- 按指标跨公司筛选/比较（验收标准 §5.4：一条 SQL 查「招聘量增长 >30% 且有薪资数据的业务线」）。
create index if not exists idx_insight_items_metric
  on insight_items (metric_key, status) where metric_key is not null;
-- 按断言强度筛（展示门按档位取，治理时按档位批量处置）。
create index if not exists idx_insight_items_assertion
  on insight_items (assertion, status) where assertion is not null;

-- ── 3) RLS：与 insight_items 同口径（所有人可读 active，service/admin 写）─────
alter table insight_subjects enable row level security;

drop policy if exists insight_subjects_read on insight_subjects;
create policy insight_subjects_read on insight_subjects
  for select using (status = 'active');

drop policy if exists insight_subjects_admin_write on insight_subjects;
create policy insight_subjects_admin_write on insight_subjects
  for all using (
    exists (select 1 from profiles p where p.id = auth.uid() and p.role = 'admin')
  );
