-- 158 — 管理员数据健康面板的 Supabase 侧聚合快照。
-- jobs 已在香港 PostgreSQL，本函数只聚合仍留在 Supabase 的运营表。
-- 返回小型 jsonb；禁止把 crawl_runs/discovery_runs/insight_* 全表拉到应用层。
-- 查询复用既有索引：crawl_runs(source_id, started_at)、discovery_runs(created_at)
-- 以及 insight_items(status, last_verified_at) / insight_disputes(status, created_at)。

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
    select now() - p_window as since_at
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
  discovery_mode_agg as (
    select
      coalesce(dr.mode, 'web_search') as mode,
      count(*)::int as runs,
      count(*) filter (
        where dr.started_at is not null and dr.finished_at is not null
      )::int as completed_runs,
      round(
        (
          avg(extract(epoch from (dr.finished_at - dr.started_at))) filter (
            where dr.started_at is not null and dr.finished_at is not null
          )
        )::numeric,
        1
      ) as avg_duration_seconds
    from discovery_runs dr
    cross join bounds
    where dr.created_at >= bounds.since_at
    group by coalesce(dr.mode, 'web_search')
  ),
  discovery_failure_agg as (
    select
      coalesce(dr.mode, 'web_search') as mode,
      case
        when nullif(btrim(dr.failure_reason), '') is not null
          then btrim(dr.failure_reason)
        when nullif(btrim(dr.diagnostics ->> 'failure_reason'), '') is not null
          then btrim(dr.diagnostics ->> 'failure_reason')
        when dr.status = 'partial_success' then 'partial_success_unspecified'
        else 'unknown'
      end as reason,
      count(*)::int as count
    from discovery_runs dr
    cross join bounds
    where dr.created_at >= bounds.since_at
      and dr.status in ('failed', 'partial_success')
    group by
      coalesce(dr.mode, 'web_search'),
      case
        when nullif(btrim(dr.failure_reason), '') is not null
          then btrim(dr.failure_reason)
        when nullif(btrim(dr.diagnostics ->> 'failure_reason'), '') is not null
          then btrim(dr.diagnostics ->> 'failure_reason')
        when dr.status = 'partial_success' then 'partial_success_unspecified'
        else 'unknown'
      end
  ),
  insight_dimension_agg as (
    select dimension, count(*)::int as count
    from insight_items
    where status = 'active'
    group by dimension
  ),
  insight_totals as (
    select count(*)::int as active_total
    from insight_items
    where status = 'active'
  ),
  dispute_totals as (
    select
      count(*)::int as total,
      count(*) filter (where status = 'open')::int as open
    from insight_disputes
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
    'discovery_modes', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'mode', mode,
          'runs', runs,
          'completed_runs', completed_runs,
          'avg_duration_seconds', avg_duration_seconds
        )
        order by mode
      )
      from discovery_mode_agg
    ), '[]'::jsonb),
    'discovery_failures', coalesce((
      select jsonb_agg(
        jsonb_build_object('mode', mode, 'reason', reason, 'count', count)
        order by count desc, mode, reason
      )
      from discovery_failure_agg
    ), '[]'::jsonb),
    'insight', jsonb_build_object(
      'active_total', (select active_total from insight_totals),
      'dimensions', coalesce((
        select jsonb_agg(
          jsonb_build_object('dimension', dimension, 'count', count)
          order by count desc, dimension
        )
        from insight_dimension_agg
      ), '[]'::jsonb),
      'disputes_total', (select total from dispute_totals),
      'disputes_open', (select open from dispute_totals)
    )
  );
$function$;

revoke execute on function public.admin_health_snapshot(interval) from public, anon, authenticated;
grant execute on function public.admin_health_snapshot(interval) to service_role;
