-- 133 — JD summary 富化追踪：drain worker 用 enrich_fail_count 做死信、enrich_checked_at 做调度去重。
-- 幂等（add column if not exists）。push 后由 migrate.yml 自动应用。
alter table jobs add column if not exists enrich_fail_count int not null default 0;
alter table jobs add column if not exists enrich_checked_at timestamptz;

-- 队列扫描部分索引：active + 空 summary + 未超死信，按最近优先（drain 取队列走这条）。
create index if not exists idx_jobs_enrich_queue
  on jobs (first_seen_at desc)
  where status = 'active' and summary is null and enrich_fail_count < 3;
