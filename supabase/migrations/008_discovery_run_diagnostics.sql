-- Optional diagnostics columns for controlled China official-source discovery.
-- The API route is backward-compatible with older schemas and falls back to
-- the 005_source_candidates discovery_runs shape until this migration is applied.

alter table discovery_runs
  add column if not exists provider_name text,
  add column if not exists provider_query text,
  add column if not exists raw_results_count integer default 0,
  add column if not exists official_candidates_count integer default 0,
  add column if not exists source_candidates_created integer default 0,
  add column if not exists source_candidates_reused integer default 0,
  add column if not exists rate_limited boolean default false,
  add column if not exists cache_hit boolean default false,
  add column if not exists failure_reason text,
  add column if not exists diagnostics jsonb;

create index if not exists idx_discovery_runs_provider_created
  on discovery_runs(provider_name, created_at desc);
