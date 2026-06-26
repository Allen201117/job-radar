-- 161 — 个人机会雷达：上次访问状态 + 邮件摘要设置（§5.1）
-- user_radar_state：记录用户上次打开「今日机会」的时间，用于「自上次访问新增」计算（§7.2）。
-- notification_settings：每日邮件摘要的用户设置（默认关闭；Workstream F 才接发送，本迁移先建表）。
-- 均按 user_id 隔离；service_role 绕 RLS 供摘要任务读取。

create table if not exists user_radar_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  last_opened_at timestamptz,
  last_feed_generated_at timestamptz,
  last_feed_count integer not null default 0 check (last_feed_count >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists notification_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email_digest_enabled boolean not null default false,
  frequency text not null default 'daily'
    check (frequency in ('daily', 'weekdays')),
  send_hour smallint not null default 8
    check (send_hour between 0 and 23),
  timezone text not null default 'Asia/Shanghai',
  last_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 摘要任务按「已开启 + last_sent_at」筛到期用户的部分索引
create index if not exists idx_notification_settings_due
  on notification_settings (email_digest_enabled, last_sent_at)
  where email_digest_enabled = true;

-- RLS：用户只能读写自己的；不允许客户端 delete。service_role 绕 RLS。
alter table user_radar_state enable row level security;

drop policy if exists "Users can read own radar state" on user_radar_state;
create policy "Users can read own radar state"
  on user_radar_state for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own radar state" on user_radar_state;
create policy "Users can insert own radar state"
  on user_radar_state for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own radar state" on user_radar_state;
create policy "Users can update own radar state"
  on user_radar_state for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

alter table notification_settings enable row level security;

drop policy if exists "Users can read own notification settings" on notification_settings;
create policy "Users can read own notification settings"
  on notification_settings for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own notification settings" on notification_settings;
create policy "Users can insert own notification settings"
  on notification_settings for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own notification settings" on notification_settings;
create policy "Users can update own notification settings"
  on notification_settings for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
