-- DESTRUCTIVE PRODUCTION OPERATION.
-- Run only after explicit user approval.
-- This removes all current job rows and any rows in tables that reference jobs through FK CASCADE.
-- Expected casualty: job_actions tied to current jobs may be deleted.

begin;

truncate table jobs cascade;

commit;
