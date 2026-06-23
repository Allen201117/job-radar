-- 163 — 关注公司的覆盖请求（§5.3 / §10）
-- 用户在「关注与偏好」里填关注公司 → 保存即生成请求行并立即返回状态（covered/queued/...），不等待抓取。
-- 写入只由 /api/preferences（鉴权后 service role 代写）或管理员处理；客户端不可直接写。

create table if not exists company_watch_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  company text not null,
  normalized_company text not null,
  status text not null default 'queued'
    check (status in ('covered', 'queued', 'researching', 'unsupported')),
  matched_source_ids uuid[] not null default '{}',
  resolution_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, normalized_company)
);

create index if not exists idx_company_watch_requests_status_created
  on company_watch_requests (status, created_at desc);

alter table company_watch_requests enable row level security;

-- 用户只能读自己的请求
drop policy if exists "Users read own watch requests" on company_watch_requests;
create policy "Users read own watch requests"
  on company_watch_requests for select
  using (auth.uid() = user_id);

-- 管理员可读全部（运营队列用）
drop policy if exists "Admins read all watch requests" on company_watch_requests;
create policy "Admins read all watch requests"
  on company_watch_requests for select
  using (exists (select 1 from profiles where id = auth.uid() and role = 'admin'));

-- 不给 authenticated 任何 insert/update/delete 策略：写入一律走 service role（API/管理员），绕 RLS。
