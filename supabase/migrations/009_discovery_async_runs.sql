-- ============================================================
-- Async browser-discovery runs (on-demand Playwright intercept via CI dispatch)
-- ============================================================
-- The legacy /api/discovery flow is synchronous (Baidu web search) and writes
-- discovery_runs with terminal statuses only. The new on-demand "browser
-- discovery" is async: the API inserts a run as 'queued', triggers a GitHub
-- Actions workflow_dispatch, and the crawler updates the row through
-- 'running' -> terminal. The frontend polls /api/discovery/status?runId=.
--
-- This migration is required for the async path: status 'queued'/'running'
-- violate the 005 check constraint, so inserts fail until it is applied.

-- 1. Allow the two non-terminal statuses.
alter table discovery_runs drop constraint if exists discovery_runs_status_check;
alter table discovery_runs
  add constraint discovery_runs_status_check
  check (status in ('queued', 'running', 'success', 'partial_success', 'failed', 'skipped'));

-- 2. Columns for the async lifecycle.
alter table discovery_runs
  add column if not exists user_id uuid,
  add column if not exists mode text default 'web_search',
  add column if not exists started_at timestamptz,
  add column if not exists finished_at timestamptz,
  add column if not exists dispatch_ref text;

create index if not exists idx_discovery_runs_user_created
  on discovery_runs(user_id, created_at desc);

-- 3. Let a user poll their own runs directly (service role still bypasses RLS).
drop policy if exists "Users read own discovery_runs" on discovery_runs;
create policy "Users read own discovery_runs"
  on discovery_runs for select
  using (user_id = auth.uid());
