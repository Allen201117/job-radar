-- 181 — 用户漏斗：admin_health_snapshot 的 user_totals 新增 saved_users / applied_users（收藏过/投递过的去重人数），供管理员看板用户漏斗使用。

create table if not exists public.ops_runs (
  id uuid primary key default gen_random_uuid(),
  module text not null,
  run_date date not null default ((now() at time zone 'Asia/Shanghai')::date),
  metrics jsonb not null default '{}'::jsonb,
  status text not null check (status in ('success', 'partial', 'failed')),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_ops_runs_module_run_date
  on public.ops_runs (module, run_date desc);

alter table public.ops_runs enable row level security;
revoke all on table public.ops_runs from public, anon, authenticated;
grant select, insert on table public.ops_runs to service_role;

create or replace function public.admin_health_snapshot(
  p_window interval default interval '7 days'
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $function$
  with bounds as (
    select
      now() - p_window as since_at,
      date_trunc('day', now() at time zone 'Asia/Shanghai')
        at time zone 'Asia/Shanghai' as today_start,
      (now() at time zone 'Asia/Shanghai')::date as today_date
  ),
  crawl_agg as (
    select
      s.id as source_id,
      s.company,
      coalesce(s.adapter_name, 'unknown') as adapter_name,
      count(cr.id)::int as runs,
      count(*) filter (where cr.status = 'success')::int as success,
      count(*) filter (where cr.status = 'partial_success')::int as partial_success,
      count(*) filter (where cr.status = 'failed')::int as failed,
      count(*) filter (where cr.status = 'skipped')::int as skipped
    from sources s
    cross join bounds
    left join crawl_runs cr
      on cr.source_id = s.id
      and cr.started_at >= bounds.since_at
    where s.enabled = true
    group by s.id, s.company, s.adapter_name
  ),
  crawl_today as (
    select
      count(*)::int as runs,
      coalesce(sum(cr.jobs_found), 0)::int as jobs_found,
      coalesce(sum(cr.jobs_created), 0)::int as jobs_created,
      coalesce(sum(cr.jobs_updated), 0)::int as jobs_updated,
      count(*) filter (where cr.status = 'failed')::int as failed_runs,
      count(distinct cr.source_id) filter (where cr.status = 'failed')::int as failed_sources,
      max(coalesce(cr.finished_at, cr.started_at)) as last_run_at
    from crawl_runs cr
    cross join bounds
    where cr.started_at >= bounds.today_start
  ),
  discovery_today as (
    select
      count(*)::int as runs,
      coalesce(sum(dr.jobs_created), 0)::int as jobs_created,
      coalesce(sum(dr.jobs_updated), 0)::int as jobs_updated,
      count(*) filter (where dr.status = 'failed')::int as failed_runs,
      max(coalesce(dr.finished_at, dr.started_at, dr.created_at)) as last_run_at
    from discovery_runs dr
    cross join bounds
    where dr.created_at >= bounds.today_start
  ),
  ops_today as (
    select
      o.module,
      count(*)::int as runs,
      count(*) filter (where o.status = 'success')::int as success,
      count(*) filter (where o.status = 'partial')::int as partial,
      count(*) filter (where o.status = 'failed')::int as failed,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'checked') = 'number'
        then (o.metrics ->> 'checked')::int else 0 end), 0)::int as checked,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'expired') = 'number'
        then (o.metrics ->> 'expired')::int else 0 end), 0)::int as expired,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'deleted') = 'number'
        then (o.metrics ->> 'deleted')::int else 0 end), 0)::int as deleted,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'enriched') = 'number'
        then (o.metrics ->> 'enriched')::int else 0 end), 0)::int as enriched,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'companies_enriched') = 'number'
        then (o.metrics ->> 'companies_enriched')::int else 0 end), 0)::int as companies_enriched,
      coalesce(sum(case when jsonb_typeof(o.metrics -> 'retired') = 'number'
        then (o.metrics ->> 'retired')::int else 0 end), 0)::int as retired,
      max(coalesce(o.finished_at, o.started_at, o.created_at)) as last_run_at
    from ops_runs o
    cross join bounds
    where o.run_date = bounds.today_date
    group by o.module
  ),
  insight_totals as (
    select count(*)::int as active_total
    from insight_items
    where status = 'active'
  ),
  insight_today as (
    select
      count(*) filter (where ii.created_at >= bounds.today_start)::int as today_created
    from insight_items ii
    cross join bounds
  ),
  dispute_totals as (
    select
      count(*)::int as total,
      count(*) filter (where status = 'open')::int as open
    from insight_disputes
  ),
  user_totals as (
    select
      (select count(*)::int from profiles) as total_users,
      (select count(*)::int from profiles p cross join bounds
        where p.created_at >= bounds.today_start) as today_users,
      (select count(distinct up.user_id)::int from user_preferences up) as users_with_preferences,
      (select count(distinct user_id)::int from job_actions where action = 'saved') as saved_users,
      (select count(distinct user_id)::int from job_actions where action = 'applied') as applied_users,
      (select count(*)::int from job_actions where action = 'saved') as saved_total,
      (select count(*)::int from job_actions ja cross join bounds
        where ja.action = 'saved' and ja.created_at >= bounds.today_start) as saved_today,
      (select count(*)::int from job_actions where action = 'applied') as applied_total,
      (select count(*)::int from job_actions ja cross join bounds
        where ja.action = 'applied' and ja.created_at >= bounds.today_start) as applied_today
  ),
  resume_today as (
    select
      count(*) filter (where e.event = 'resume_parse_started')::int as started,
      count(*) filter (where e.event = 'resume_parse_succeeded')::int as succeeded,
      count(*) filter (
        where e.event = 'resume_parse_succeeded'
          and e.payload #>> '{diagnostics,source}' = 'llm'
      )::int as llm,
      count(*) filter (
        where e.event = 'resume_parse_succeeded'
          and e.payload #>> '{diagnostics,source}' = 'rule'
      )::int as rule
    from events e
    cross join bounds
    where e.created_at >= bounds.today_start
  )
  select jsonb_build_object(
    'window_days', greatest(1, round(extract(epoch from p_window) / 86400)::int),
    'crawl_sources', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'source_id', source_id,
          'company', company,
          'adapter_name', adapter_name,
          'runs', runs,
          'success', success,
          'partial_success', partial_success,
          'failed', failed,
          'skipped', skipped
        )
        order by failed desc, partial_success desc, runs desc, company
      )
      from crawl_agg
    ), '[]'::jsonb),
    'insight', jsonb_build_object(
      'active_total', (select active_total from insight_totals),
      'disputes_total', (select total from dispute_totals),
      'disputes_open', (select open from dispute_totals),
      'today_created', (select today_created from insight_today)
    ),
    'today', jsonb_build_object(
      'crawl', (select to_jsonb(crawl_today) from crawl_today),
      'discovery', (select to_jsonb(discovery_today) from discovery_today),
      'ops_runs', coalesce((
        select jsonb_agg(to_jsonb(ops_today) order by module)
        from ops_today
      ), '[]'::jsonb),
      'users', (select to_jsonb(user_totals) from user_totals),
      'resume', (select to_jsonb(resume_today) from resume_today)
    )
  );
$function$;

revoke execute on function public.admin_health_snapshot(interval) from public, anon, authenticated;
grant execute on function public.admin_health_snapshot(interval) to service_role;
