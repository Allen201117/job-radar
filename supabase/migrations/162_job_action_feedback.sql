-- 162 — job_actions 结构化负反馈 + 跨库外键边界修正 + 原子动作 RPC（§5.2 / §8.1）
-- jobs 已迁到独立香港 PostgreSQL，job_actions 仍在 Supabase。继续保留指向 Supabase 旧 jobs 表的 FK
-- 会让香港库中新岗位无法收藏/忽略/投递（FK 校验失败）→ 必须删 FK，岗位存在性改由 action API 用
-- jobsByIds() 在写入前校验。

-- 1) 结构化负反馈列
alter table job_actions
  add column if not exists reason_code text,
  add column if not exists reason_text text,
  add column if not exists job_snapshot jsonb not null default '{}'::jsonb,
  add column if not exists updated_at timestamptz not null default now();

-- 2) reason_code 白名单 + reason_text 长度（数据库不强制 reason 必填，兼容旧客户端；新 API 对 ignored 强制）
alter table job_actions drop constraint if exists job_actions_reason_code_check;
alter table job_actions add constraint job_actions_reason_code_check
  check (reason_code is null or reason_code in (
    'role_mismatch', 'location_mismatch', 'industry_mismatch', 'seniority_mismatch',
    'education_mismatch', 'compensation_mismatch', 'company_not_interested',
    'already_seen_elsewhere', 'not_job_seeking', 'other'
  ));

alter table job_actions drop constraint if exists job_actions_reason_text_len;
alter table job_actions add constraint job_actions_reason_text_len
  check (reason_text is null or char_length(reason_text) <= 200);

-- 3) 跨库外键边界：删除指向 Supabase jobs 的 FK（live 库可能已无，if exists 幂等），
--    清理历史空 job_id 后置为 not null。
alter table job_actions drop constraint if exists job_actions_job_id_fkey;
delete from job_actions where job_id is null;
alter table job_actions alter column job_id set not null;

-- 4) 原子主动作 RPC（§8.1）：一次事务里「删旧主动作 → 视情况插新」，viewed 不动。
--    用 auth.uid()，不接受 user_id；reason 仅在 ignored 时落库。只 grant authenticated。
create or replace function public.set_job_primary_action(
  p_job_id uuid,
  p_action text,
  p_reason_code text,
  p_reason_text text,
  p_job_snapshot jsonb
)
returns text
language plpgsql
security definer
set search_path = public
as $function$
declare
  v_user uuid := auth.uid();
begin
  if v_user is null then
    raise exception 'not authenticated';
  end if;

  -- 删除该用户该岗位的主动作（saved/ignored/applied），保留 viewed
  delete from job_actions
   where user_id = v_user
     and job_id = p_job_id
     and action in ('saved', 'ignored', 'applied');

  -- 空动作 = 仅取消
  if p_action is null then
    return null;
  end if;

  if p_action not in ('saved', 'ignored', 'applied') then
    raise exception 'invalid action: %', p_action;
  end if;

  insert into job_actions (user_id, job_id, action, reason_code, reason_text, job_snapshot, updated_at)
  values (
    v_user,
    p_job_id,
    p_action,
    case when p_action = 'ignored' then p_reason_code else null end,
    case when p_action = 'ignored' then p_reason_text else null end,
    coalesce(p_job_snapshot, '{}'::jsonb),
    now()
  )
  on conflict (user_id, job_id, action) do update
    set reason_code = excluded.reason_code,
        reason_text = excluded.reason_text,
        job_snapshot = excluded.job_snapshot,
        updated_at = now();

  return p_action;
end;
$function$;

revoke execute on function public.set_job_primary_action(uuid, text, text, text, jsonb) from public, anon;
grant execute on function public.set_job_primary_action(uuid, text, text, text, jsonb) to authenticated;
