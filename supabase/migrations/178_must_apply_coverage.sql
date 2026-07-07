-- 178 — 北极星：必投清单抓全率。
-- 清单只从调用方传入 patterns，避免数据库内硬编码运营口径。

create or replace function public.must_apply_coverage(patterns text[])
returns jsonb
language sql
stable
security definer
set search_path = public
as $function$
  with requested as (
    select
      idx::int,
      pattern
    from unnest(patterns) with ordinality as p(pattern, idx)
    where pattern is not null
      and pattern <> ''
  ),
  matched as (
    select
      r.idx,
      r.pattern,
      s.id as source_id
    from requested r
    join sources s on s.company ilike r.pattern
    where s.enabled = true
  ),
  latest_runs as (
    select distinct on (matched.idx, matched.source_id)
      matched.idx,
      matched.pattern,
      matched.source_id,
      cr.reported_total,
      coalesce(cr.jobs_found, 0)::int as fetched,
      coalesce(cr.finished_at, cr.started_at) as last_run_at
    from matched
    left join crawl_runs cr on cr.source_id = matched.source_id
    order by matched.idx, matched.source_id, cr.started_at desc nulls last, cr.id desc
  ),
  company_totals as (
    select
      r.idx,
      r.pattern,
      case
        when count(reported_total) filter (where reported_total is not null) > 0
          then coalesce(sum(reported_total) filter (where reported_total is not null), 0)::int
        else null
      end as reported_total,
      coalesce(sum(fetched), 0)::int as fetched,
      max(last_run_at) as last_run_at
    from requested r
    left join latest_runs using (idx, pattern)
    group by r.idx, r.pattern
  ),
  scored as (
    select
      idx,
      pattern,
      reported_total,
      fetched,
      last_run_at,
      reported_total is not null as measurable,
      case
        when reported_total > 0 then round(least(100, fetched::numeric * 100 / reported_total))::int
        else null
      end as coverage_pct
    from company_totals
  )
  select jsonb_build_object(
    'measurable', (select count(*)::int from scored where measurable),
    'blind', (select count(*)::int from scored where not measurable),
    'fully_fetched', (
      select count(*)::int
      from scored
      where coverage_pct >= 90
    ),
    'avg_pct', (
      select round(avg(coverage_pct))::int
      from scored
      where coverage_pct is not null
    ),
    'companies', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'name', pattern,
          'pattern', pattern,
          'reported_total', reported_total,
          'fetched', fetched,
          'coverage_pct', coverage_pct,
          'measurable', measurable,
          'last_run_at', last_run_at
        )
        order by coverage_pct asc nulls last, idx asc
      )
      from scored
    ), '[]'::jsonb)
  );
$function$;

revoke execute on function public.must_apply_coverage(text[]) from public, anon, authenticated;
grant execute on function public.must_apply_coverage(text[]) to service_role;
