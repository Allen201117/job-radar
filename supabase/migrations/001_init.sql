-- ============================================================
-- Job Radar Private Beta v0.1 — 数据库初始化
-- ============================================================

-- 1. profiles — 扩展 Supabase Auth 用户
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  role text default 'user' check (role in ('admin', 'user')),
  created_at timestamptz default now()
);

-- 2. sources — 企业招聘源
create table sources (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  source_url text not null,
  source_type text,
  adapter_name text,
  crawl_method text default 'http' check (crawl_method in ('http', 'playwright', 'manual')),
  enabled boolean default true,
  last_checked_at timestamptz,
  notes text,
  created_at timestamptz default now()
);

-- 3. jobs — 共享岗位库
create table jobs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  company text not null,
  title text not null,
  location text,
  job_type text,
  summary text,
  jd_url text not null,
  apply_url text,
  salary_text text,
  posted_at timestamptz,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now(),
  status text default 'active' check (status in ('active', 'removed', 'expired', 'error')),
  content_hash text,
  created_at timestamptz default now(),
  unique(company, title, location, jd_url)
);

create index idx_jobs_status on jobs(status);
create index idx_jobs_company on jobs(company);
create index idx_jobs_first_seen on jobs(first_seen_at desc);

-- 4. user_preferences — 用户求职偏好
create table user_preferences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  target_locations text[] default '{}',
  target_roles text[] default '{}',
  target_keywords text[] default '{}',
  exclude_keywords text[] default '{}',
  target_companies text[] default '{}',
  daily_limit integer default 20,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(user_id)
);

-- 5. job_actions — 用户岗位操作
create table job_actions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  job_id uuid references jobs(id) on delete cascade,
  action text not null check (action in ('viewed', 'saved', 'ignored', 'applied')),
  note text,
  created_at timestamptz default now(),
  unique(user_id, job_id, action)
);

create index idx_job_actions_user on job_actions(user_id, action);

-- 6. crawl_runs — 抓取日志
create table crawl_runs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  started_at timestamptz default now(),
  finished_at timestamptz,
  status text check (status in ('success', 'partial_success', 'failed', 'skipped')),
  jobs_found integer default 0,
  jobs_created integer default 0,
  jobs_updated integer default 0,
  error_message text
);

create index idx_crawl_runs_source on crawl_runs(source_id, started_at desc);
