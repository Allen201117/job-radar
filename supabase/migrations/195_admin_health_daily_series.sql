-- 195 — 管理员看板日序列：保留既有 admin_health_snapshot 的今日快照，单独提供 Tracker 所需的日粒度状态。

create or replace function public.admin_health_daily_series(
  p_days integer default 30
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $function$
  with bounds as (
    select greatest(1, least(coalesce(p_days, 30), 92))::integer as days,
      (now() at time zone 'Asia/Shanghai')::date as today_date
  ),
  calendar as (
    select generate_series(
      (select today_date - (days - 1) from bounds),
      (select today_date from bounds),
      interval '1 day'
    )::date as run_date
  ),
  ops_by_day as (
    select
      o.run_date,
      count(*)::integer as runs,
      count(*) filter (where o.status = 'failed')::integer as failed,
      count(*) filter (where o.status = 'partial')::integer as partial
    from public.ops_runs o
    cross join bounds
    where o.run_date between bounds.today_date - (bounds.days - 1) and bounds.today_date
    group by o.run_date
  ),
  crawl_by_day as (
    select
      (coalesce(cr.finished_at, cr.started_at) at time zone 'Asia/Shanghai')::date as run_date,
      count(*)::integer as runs,
      count(*) filter (where cr.status = 'failed')::integer as failed,
      count(*) filter (where cr.status = 'partial_success')::integer as partial
    from public.crawl_runs cr
    cross join bounds
    where (coalesce(cr.finished_at, cr.started_at) at time zone 'Asia/Shanghai')::date
      between bounds.today_date - (bounds.days - 1) and bounds.today_date
    group by 1
  ),
  north_star_by_day as (
    select
      n.snapshot_date as run_date,
      n.must_apply_healthy_companies as healthy,
      n.must_apply_total_companies as total,
      n.written_at
    from public.north_star_snapshots n
    cross join bounds
    where n.snapshot_date between bounds.today_date - (bounds.days - 1) and bounds.today_date
  )
  select jsonb_build_object(
    'days', coalesce(jsonb_agg(jsonb_build_object(
      'day', to_char(calendar.run_date, 'YYYY-MM-DD'),
      'ops', case when ops_by_day.run_date is null then null else jsonb_build_object(
        'runs', ops_by_day.runs,
        'failed', ops_by_day.failed,
        'partial', ops_by_day.partial
      ) end,
      'crawl', case when crawl_by_day.run_date is null then null else jsonb_build_object(
        'runs', crawl_by_day.runs,
        'failed', crawl_by_day.failed,
        'partial', crawl_by_day.partial
      ) end,
      'north_star', case when north_star_by_day.run_date is null then null else jsonb_build_object(
        'healthy', north_star_by_day.healthy,
        'total', north_star_by_day.total,
        'written_at', north_star_by_day.written_at
      ) end
    ) order by calendar.run_date), '[]'::jsonb)
  )
  from calendar
  left join ops_by_day using (run_date)
  left join crawl_by_day using (run_date)
  left join north_star_by_day using (run_date);
$function$;

revoke execute on function public.admin_health_daily_series(integer) from public, anon, authenticated;
grant execute on function public.admin_health_daily_series(integer) to service_role;

comment on function public.admin_health_daily_series(integer) is
  '管理员运营看板日序列：ops_runs、crawl_runs 和北极星快照的每日状态，供 Tracker 使用。';
