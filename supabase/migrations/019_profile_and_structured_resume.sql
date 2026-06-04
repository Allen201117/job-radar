-- ============================================================
-- 019 — 个人资料签名 + 简历结构化抽取字段
-- ============================================================

-- profiles：个性签名（昵称复用已有 display_name）。
-- 补 INSERT 策略，让用户能 upsert 自己的资料行（原表只有 select / update）。
alter table profiles
  add column if not exists bio text;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'profiles'
      and policyname = 'Users can insert own profile'
  ) then
    create policy "Users can insert own profile"
      on profiles for insert
      with check (auth.uid() = id);
  end if;
end $$;

-- candidate_profiles：LLM 结构化抽取新增字段。
-- 教育沿用已有 education jsonb；新增实习 / 项目 / 基本信息（基本信息脱敏存储）。
alter table candidate_profiles
  add column if not exists basic_info jsonb default '{}'::jsonb,
  add column if not exists internships jsonb default '[]'::jsonb,
  add column if not exists projects jsonb default '[]'::jsonb;
