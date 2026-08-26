-- 194 — 北极星每日快照：从每日抓取旁路写入，为后续趋势积累真实基线。

create table if not exists public.north_star_snapshots (
  snapshot_date date primary key,
  must_apply_healthy_companies integer not null check (must_apply_healthy_companies >= 0),
  must_apply_total_companies integer not null check (must_apply_total_companies >= 0),
  worst_industry text not null,
  worst_industry_healthy_companies integer not null check (worst_industry_healthy_companies >= 0),
  worst_industry_total_companies integer not null check (worst_industry_total_companies >= 0),
  valid_active_jobs integer not null check (valid_active_jobs >= 0),
  active_jobs integer not null check (active_jobs >= 0),
  job_validity_rate numeric check (job_validity_rate is null or (job_validity_rate >= 0 and job_validity_rate <= 1)),
  list_version text not null,
  written_at timestamptz not null default now()
);

alter table public.north_star_snapshots enable row level security;
revoke all on table public.north_star_snapshots from public, anon, authenticated;
grant select, insert, update on table public.north_star_snapshots to service_role;
grant select on table public.north_star_snapshots to authenticated;

drop policy if exists "Admins can read north_star_snapshots" on public.north_star_snapshots;
create policy "Admins can read north_star_snapshots"
  on public.north_star_snapshots for select
  to authenticated
  using (exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'));

comment on table public.north_star_snapshots is
  '每日北极星快照：必投清单健康覆盖与岗位有效率；同日 upsert 覆盖，供趋势展示在样本足够后启用。';
