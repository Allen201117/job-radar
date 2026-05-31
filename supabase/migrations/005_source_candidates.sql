-- ============================================================
-- Official job discovery candidate isolation
-- ============================================================

create table source_candidates (
  id uuid primary key default gen_random_uuid(),
  query text not null,
  company text,
  title text,
  url text not null,
  source_type text,
  detected_platform text check (
    detected_platform in (
      'official_careers',
      'greenhouse',
      'lever',
      'workday',
      'ashby',
      'smartrecruiters',
      'unknown'
    )
  ),
  confidence numeric,
  status text default 'pending' check (
    status in ('pending', 'approved', 'rejected', 'parsed', 'failed')
  ),
  reason text,
  created_at timestamptz default now(),
  unique(query, url)
);

create index idx_source_candidates_status
  on source_candidates(status, created_at desc);

create index idx_source_candidates_platform
  on source_candidates(detected_platform, created_at desc);

create table discovery_runs (
  id uuid primary key default gen_random_uuid(),
  query text not null,
  city text,
  company text,
  job_type text,
  status text check (status in ('success', 'partial_success', 'failed', 'skipped')),
  candidates_found integer default 0,
  candidates_parsed integer default 0,
  candidates_pending integer default 0,
  jobs_created integer default 0,
  jobs_updated integer default 0,
  blocked_count integer default 0,
  error_message text,
  created_at timestamptz default now()
);

create index idx_discovery_runs_created
  on discovery_runs(created_at desc);

alter table source_candidates enable row level security;

create policy "Admins can read source_candidates"
  on source_candidates for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

alter table discovery_runs enable row level security;

create policy "Admins can read discovery_runs"
  on discovery_runs for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
