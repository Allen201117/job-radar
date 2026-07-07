-- 177 — 管理员运营看板：全库抓全率快照。
-- jobs 已在香港 PostgreSQL；本函数只聚合 Supabase 的 sources/crawl_runs。

create or replace function public.crawl_coverage_snapshot()
returns jsonb
language sql
stable
security definer
set search_path = public
as $function$
  with latest_runs as (
    select distinct on (cr.source_id)
      cr.source_id,
      s.company,
      coalesce(s.adapter_name, 'unknown') as adapter,
      cr.reported_total,
      coalesce(cr.jobs_found, 0)::int as fetched,
      cr.coverage_complete,
      coalesce(cr.finished_at, cr.started_at) as last_run_at
    from crawl_runs cr
    join sources s on s.id = cr.source_id
    where s.enabled = true
    order by cr.source_id, cr.started_at desc nulls last, cr.id desc
  ),
  scored as (
    select
      company,
      adapter,
      reported_total,
      fetched,
      coverage_complete,
      last_run_at,
      case
        when reported_total > 0 then round(least(100, fetched::numeric * 100 / reported_total))::int
        else null
      end as coverage_pct
    from latest_runs
  )
  select jsonb_build_object(
    'measurable', (select count(*)::int from scored where reported_total is not null),
    'blind', (select count(*)::int from scored where reported_total is null),
    'avg_coverage_pct', (
      select round(avg(coverage_pct))::int
      from scored
      where reported_total > 0
    ),
    'under_count', (
      select count(*)::int
      from scored
      where reported_total > 0
        and coverage_pct < 80
    ),
    'under_sources', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'company', company,
          'adapter', adapter,
          'reported_total', reported_total,
          'fetched', fetched,
          'coverage_pct', coverage_pct,
          'last_run_at', last_run_at
        )
        order by coverage_pct asc, company
      )
      from (
        select
          company,
          adapter,
          reported_total,
          fetched,
          coverage_pct,
          last_run_at
        from scored
        where reported_total > 0
          and coverage_pct < 80
        order by coverage_pct asc, company
        limit 40
      ) under_limited
    ), '[]'::jsonb)
  );
$function$;

revoke execute on function public.crawl_coverage_snapshot() from public, anon, authenticated;
grant execute on function public.crawl_coverage_snapshot() to service_role;
