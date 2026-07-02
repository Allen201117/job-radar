-- ============================================================
-- First-party career insight submissions
-- ============================================================
-- Users can submit short, consented, deidentified first-hand experiences.
-- Approved rows are read by server-side APIs with service_role and returned
-- only after anonymization plus a company-level minimum-count gate.

create table if not exists insight_submissions (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  company_id uuid references company_profiles(id) on delete set null,
  user_id uuid not null references auth.users(id) on delete cascade,
  dimension text not null check (
    dimension in ('culture', 'compensation_intensity', 'path', 'hiring')
  ),
  topic text not null check (
    topic in ('internship', 'onboarding', 'bonus', 'interview', 'promotion', 'culture')
  ),
  rating integer check (rating between 1 and 5),
  content text not null check (char_length(content) <= 200),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check (
    status in ('pending', 'approved', 'rejected', 'retired')
  ),
  moderation jsonb not null default '{}'::jsonb,
  employment_verified boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_insight_submissions_company_status
  on insight_submissions (company, status, created_at desc);

create index if not exists idx_insight_submissions_user
  on insight_submissions (user_id, created_at desc);

create index if not exists idx_insight_submissions_status_created
  on insight_submissions (status, created_at desc);

alter table insight_submissions enable row level security;

drop policy if exists "Users can read own insight submissions" on insight_submissions;
create policy "Users can read own insight submissions"
  on insight_submissions for select using (user_id = auth.uid());

drop policy if exists "Users can insert own insight submissions" on insight_submissions;
create policy "Users can insert own insight submissions"
  on insight_submissions for insert with check (user_id = auth.uid());

drop policy if exists "Users can delete own insight submissions" on insight_submissions;
create policy "Users can delete own insight submissions"
  on insight_submissions for delete using (user_id = auth.uid());

drop policy if exists "Admins can read all insight submissions" on insight_submissions;
create policy "Admins can read all insight submissions"
  on insight_submissions for select using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

revoke all on table insight_submissions from public, anon;
grant select, insert, delete on table insight_submissions to authenticated;
grant select, insert, update, delete on table insight_submissions to service_role;
