-- ============================================================
-- 136 — 轻量行为埋点 events 表（验证「职业洞察是否有人用」，零分析 SDK）
-- ============================================================
-- 自有最小埋点：登录用户可写自己的事件；仅 admin 可读。push 后由 migrate.yml 自动应用。

create table if not exists events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  event text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- 近 7 天按 event 分组统计走这条（created_at 范围扫描）
create index if not exists idx_events_created_at on events (created_at desc);

alter table events enable row level security;

-- 登录用户只能插入自己的事件（user_id = auth.uid()）
create policy "Users can insert own events"
  on events for insert
  with check (auth.uid() = user_id);

-- 仅 admin 可读（service_role 绕 RLS 写/读统计）
create policy "Admins can read events"
  on events for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
