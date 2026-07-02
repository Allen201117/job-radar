-- ============================================================
-- Career insights: on-demand enrich ledger index + hiring monthly aggregate
-- ============================================================
-- 1) /api/insights can record user-triggered single-company enrich dispatches
--    in discovery_runs(mode='insight_enrich'). This partial index keeps the
--    cooldown/global-cap lookup bounded.
-- 2) company_hiring_monthly is the lightweight structure for future true
--    annual hiring-cycle comparison. It is not a source of truth until enough
--    historical months have accumulated.

create index if not exists idx_discovery_runs_insight_enrich_recent
  on discovery_runs (created_at desc)
  where mode = 'insight_enrich';

create table if not exists company_hiring_monthly (
  company text not null,
  ym text not null check (ym ~ '^\d{4}-\d{2}$'),
  posted_count integer not null default 0 check (posted_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (company, ym)
);

alter table company_hiring_monthly enable row level security;

drop policy if exists "Admins can read company_hiring_monthly" on company_hiring_monthly;
create policy "Admins can read company_hiring_monthly"
  on company_hiring_monthly for select
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

revoke all on table company_hiring_monthly from public, anon, authenticated;
grant select on table company_hiring_monthly to authenticated;
grant select, insert, update, delete on table company_hiring_monthly to service_role;
