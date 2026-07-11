-- 179 — align Supabase company availability counts with the valid-active jobs-store contract.
-- Idempotent because production environments may already expose the function from migration 145.

create or replace function public.active_job_counts_by_company()
returns table(company text, job_count int)
language sql
stable
security definer
set search_path = public
as $function$
  select j.company, count(*)::int as job_count
  from public.jobs j
  where j.status = 'active'
    and j.company is not null
    and btrim(j.company) <> ''
    and j.summary is not null
    and char_length(btrim(j.summary)) >= 60
  group by j.company
$function$;

grant execute on function public.active_job_counts_by_company() to anon, authenticated, service_role;
