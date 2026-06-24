-- 164 — 雷达强度（active/passive，v3 取代「模式」）
-- 强度只调日常推荐的量/频/门槛；不卡 readiness、不压关键提醒（产品 spec 03 §2.2 / 技术 spec 04 §1.1）。
-- radar_intensity_source 优先级：近期 user(手动) > auto(行为自调) > default(系统默认)。
-- 幂等；不放宽 user_preferences 现有 RLS（沿用「自己读写」策略，service_role 绕 RLS）。

alter table user_preferences
  add column if not exists radar_intensity text not null default 'active'
    check (radar_intensity in ('active', 'passive'));

alter table user_preferences
  add column if not exists radar_intensity_source text not null default 'default'
    check (radar_intensity_source in ('default', 'user', 'auto'));

alter table user_preferences
  add column if not exists radar_intensity_updated_at timestamptz;
