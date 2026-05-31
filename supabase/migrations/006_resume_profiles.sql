-- ============================================================
-- Resume upload, deterministic parsing, and candidate profile
-- ============================================================

create table resume_uploads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  file_name text,
  file_type text,
  file_size integer default 0,
  raw_text text,
  parsed_profile jsonb default '{}'::jsonb,
  parse_status text default 'parsed' check (
    parse_status in ('parsed', 'failed')
  ),
  parse_error text,
  created_at timestamptz default now()
);

create index idx_resume_uploads_user_created
  on resume_uploads(user_id, created_at desc);

create table candidate_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  resume_id uuid references resume_uploads(id) on delete set null,
  headline text,
  target_roles text[] default '{}',
  target_locations text[] default '{}',
  skills text[] default '{}',
  industries text[] default '{}',
  seniority text,
  experience_stage text,
  education jsonb default '[]'::jsonb,
  experience jsonb default '[]'::jsonb,
  education_summary text,
  experience_summary text,
  raw_profile jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table resume_uploads enable row level security;

create policy "Users can read own resume uploads"
  on resume_uploads for select
  using (auth.uid() = user_id);

create policy "Users can insert own resume uploads"
  on resume_uploads for insert
  with check (auth.uid() = user_id);

alter table candidate_profiles enable row level security;

create policy "Users can read own candidate profile"
  on candidate_profiles for select
  using (auth.uid() = user_id);

create policy "Users can insert own candidate profile"
  on candidate_profiles for insert
  with check (auth.uid() = user_id);

create policy "Users can update own candidate profile"
  on candidate_profiles for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
