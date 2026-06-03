-- ============================================================
-- 模块 B 职业洞察层（career insights）— 统一洞察引擎
-- 四维度共用一套 schema：timing / compensation_intensity / path / culture
-- 与官方岗位层（jobs）数据通道、信任级别、UI 严格分离（PRD §14）
-- ============================================================

-- 1. company_profiles — 公司画像（洞察聚合维度）
create table company_profiles (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  display_name text,
  -- 用于把 jobs.company 的写法变体（苹果 / Apple、字节 / 字节跳动 / ByteDance）对齐到同一画像
  aliases text[] default '{}',
  -- 去标识化的聚合摘要（禁止指向具体自然人）
  summary text,
  last_verified_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(company)
);

create index idx_company_profiles_company on company_profiles(company);

-- 2. insight_items — 洞察核心条目
create table insight_items (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references company_profiles(id) on delete cascade,
  dimension text not null check (
    dimension in ('timing', 'compensation_intensity', 'path', 'culture')
  ),
  grade text not null check (grade in ('fact', 'experience', 'rumor')),
  title text,
  -- 聚合归因式表述，禁止产品断言（见 lib/insight-verification.ts 的归因 lint）
  content text not null,
  -- experience 类的支撑样本量（grade=experience 时校验 >= 阈值）
  sample_size integer,
  -- 维度专属结构化数据：path 存 {from,to,direction}，timing 存窗口，comp 存薪资带等
  payload jsonb default '{}'::jsonb,
  -- 时效（强制至少有 time_window 或 valid_*，见校验门）
  time_window text,
  valid_from date,
  valid_until date,
  last_verified_at timestamptz not null default now(),
  -- 必须 true 才允许展示（去标识化门）
  deidentified boolean not null default false,
  status text not null default 'active' check (
    status in ('active', 'disputed', 'retired')
  ),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_insight_items_company_dim
  on insight_items(company_id, dimension, status);
create index idx_insight_items_status
  on insight_items(status, last_verified_at desc);

-- 3. insight_sources — 溯源（合规关键：仅链接 + 短摘要，禁止整段原文）
create table insight_sources (
  id uuid primary key default gen_random_uuid(),
  url text not null,
  publisher text,
  source_kind text check (
    source_kind in (
      'official_filing',
      'official_site',
      'campus_announcement',
      'public_aggregate',
      'community_deidentified'
    )
  ),
  -- 仅必要摘要片段，禁止整段 UGC 原文（PRD §7.2 著作权）
  excerpt text,
  collected_at timestamptz,
  -- 必须 true 才可被引用展示
  deidentified boolean not null default false,
  created_at timestamptz default now()
);

create index idx_insight_sources_url on insight_sources(url);

-- 4. insight_item_sources — 条目 ↔ 来源 多对多
create table insight_item_sources (
  item_id uuid not null references insight_items(id) on delete cascade,
  source_id uuid not null references insight_sources(id) on delete cascade,
  primary key (item_id, source_id)
);

-- 5. insight_disputes — 通知-删除机制（PRD §7.3，降低担责）
create table insight_disputes (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references insight_items(id) on delete cascade,
  reporter_user_id uuid references auth.users(id) on delete set null,
  reason text,
  contact text,
  status text not null default 'open' check (
    status in ('open', 'upheld', 'rejected')
  ),
  created_at timestamptz default now(),
  resolved_at timestamptz
);

create index idx_insight_disputes_item on insight_disputes(item_id, status);
create index idx_insight_disputes_status on insight_disputes(status, created_at desc);

-- ============================================================
-- RLS — 洞察读公开（仅可信+去标识），写限 admin/service_role
-- service_role 绕 RLS，用于 seed 与 admin API 写入
-- ============================================================

alter table company_profiles enable row level security;

create policy "Authenticated users can read company_profiles"
  on company_profiles for select
  using (auth.role() = 'authenticated');

create policy "Admins can write company_profiles"
  on company_profiles for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

alter table insight_items enable row level security;

-- 只暴露经校验、未下架、已去标识的条目
create policy "Authenticated users can read active insight_items"
  on insight_items for select
  using (
    auth.role() = 'authenticated'
    and status = 'active'
    and deidentified = true
  );

create policy "Admins can write insight_items"
  on insight_items for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

alter table insight_sources enable row level security;

create policy "Authenticated users can read deidentified insight_sources"
  on insight_sources for select
  using (auth.role() = 'authenticated' and deidentified = true);

create policy "Admins can write insight_sources"
  on insight_sources for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

alter table insight_item_sources enable row level security;

create policy "Authenticated users can read insight_item_sources"
  on insight_item_sources for select
  using (auth.role() = 'authenticated');

create policy "Admins can write insight_item_sources"
  on insight_item_sources for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

alter table insight_disputes enable row level security;

-- 任意登录用户可提申诉；reporter 必须是自己或匿名（null）
create policy "Users can file disputes"
  on insight_disputes for insert
  with check (
    auth.role() = 'authenticated'
    and (reporter_user_id = auth.uid() or reporter_user_id is null)
  );

create policy "Users can read own disputes"
  on insight_disputes for select
  using (auth.uid() = reporter_user_id);

create policy "Admins can read all disputes"
  on insight_disputes for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

create policy "Admins can update disputes"
  on insight_disputes for update
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
