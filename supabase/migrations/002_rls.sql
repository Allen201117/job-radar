-- ============================================================
-- Row Level Security — 用户数据隔离
-- ============================================================

-- profiles: 用户只能读写自己的
alter table profiles enable row level security;

create policy "Users can read own profile"
  on profiles for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- jobs: 所有登录用户可读
alter table jobs enable row level security;

create policy "Authenticated users can read jobs"
  on jobs for select
  using (auth.role() = 'authenticated');

-- user_preferences: 用户只能管理自己的
alter table user_preferences enable row level security;

create policy "Users can read own preferences"
  on user_preferences for select
  using (auth.uid() = user_id);

create policy "Users can insert own preferences"
  on user_preferences for insert
  with check (auth.uid() = user_id);

create policy "Users can update own preferences"
  on user_preferences for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- job_actions: 用户只能管理自己的
alter table job_actions enable row level security;

create policy "Users can read own actions"
  on job_actions for select
  using (auth.uid() = user_id);

create policy "Users can insert own actions"
  on job_actions for insert
  with check (auth.uid() = user_id);

create policy "Users can update own actions"
  on job_actions for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own actions"
  on job_actions for delete
  using (auth.uid() = user_id);

-- sources: 所有登录用户可读；admin 和 service_role 可写
alter table sources enable row level security;

create policy "Authenticated users can read sources"
  on sources for select
  using (auth.role() = 'authenticated');

create policy "Admins can update sources"
  on sources for update
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

-- crawl_runs: 仅 admin 可读（service_role 绕 RLS 写入）
alter table crawl_runs enable row level security;

create policy "Admins can read crawl_runs"
  on crawl_runs for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

-- profiles: 补充 INSERT policy（新用户注册时 trigger 使用 SECURITY DEFINER 绕过，此处为完整性声明）
create policy "Service role can insert profiles"
  on profiles for insert
  with check (true);

-- ============================================================
-- 触发器：新用户注册时自动创建 profile
-- ============================================================
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, display_name, role)
  values (new.id, new.email, 'user');
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
