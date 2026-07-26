-- 185 — 必投清单缺口漏斗台账（P1 httpx 道）。

create table must_apply_gap_attempts (
  id uuid primary key default gen_random_uuid(),
  scope text not null default 'domestic' check (scope in ('domestic','overseas')),
  company text not null,
  pattern text not null,
  industries text[] not null default '{}',
  state text not null default 'unknown' check (state in (
    'unknown','entry_found','platform_known','source_added','healthy','thin_only',
    'no_official_entry','wrong_platform','no_active_jobs','no_stable_jd',
    'anti_bot','login_wall','manual_review','governance_candidate')),
  official_entry_url text,
  detected_platform text,
  source_id uuid,
  fail_reason text,
  evidence jsonb not null default '{}'::jsonb,
  attempts integer not null default 0,
  rounds_no_entry integer not null default 0,
  last_attempt_at timestamptz,
  next_retry_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (scope, company)
);

create index idx_gap_attempts_queue
  on must_apply_gap_attempts (state, next_retry_at nulls last);

alter table must_apply_gap_attempts enable row level security;
revoke all on table must_apply_gap_attempts from public, anon, authenticated;
grant all on table must_apply_gap_attempts to service_role;
grant select on table must_apply_gap_attempts to authenticated;

create policy "Admins can read must_apply_gap_attempts"
  on must_apply_gap_attempts for select
  to authenticated
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
