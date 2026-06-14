# Jobs Database Rebuild Runbook

## Purpose

Use this runbook when Supabase Free is blocked by `jobs` table bloat and the user has approved rebuilding the job library from crawler sources.

## Preconditions

- Workday public URL fix is merged.
- Stored `jobs.summary` is capped to 300-500 characters.
- User explicitly accepts loss of current `jobs` rows.
- User explicitly accepts loss of `job_actions` rows that are cascaded from current jobs.
- Daily crawler is paused.
- No one is running production migrations at the same time.

## Read-Only Inspection

Run `scripts/check-db-size.sql` in Supabase SQL Editor before destructive cleanup and save the output into the handoff.

## Destructive Cleanup

Only after explicit user approval, run:

```sql
truncate table jobs cascade;
```

## Migration Recovery

After cleanup, rerun the failed `db-migrate` workflow so migration 144 and 145 apply to an empty or near-empty `jobs` table.

Expected result:

- `canonical_jd_url` column exists.
- `jobs_canonical_jd_url_idx` exists.
- `jobs_canonical_jd_url_active_uniq` exists.
- `active_job_counts_by_company()` exists.

## Rebuild

Run crawler in small batches first:

```bash
cd crawler
python3 run.py --source workday
python3 run.py --tier httpx --shard-index 0 --shard-count 7
```

Then resume scheduled crawler after verifying database size stays under budget.

## Post-Rebuild Checks

- Run `scripts/check-db-size.sql`.
- Confirm `jobs.summary` max length is not above the configured budget:

```sql
select max(length(summary)) as max_summary_len from jobs;
```

- Confirm Workday samples use `/en-US/{site}/details/{slug}`.
- Confirm `/jobs`, `/today`, `/api/jobs/search`, `/api/career-path`, and `/api/insights/availability` return successfully.
