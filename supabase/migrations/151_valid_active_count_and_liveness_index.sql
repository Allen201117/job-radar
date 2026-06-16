-- 岗位质量方针整治（与 150 互补；150 已修 summary-drain 队列索引，这里补「失活清扫队列」+「诚实计数」）。
--
-- 背景（db-report 实测 2026-06-16）：active 129,562，25%(32,202) 是无 JD 正文的薄卡，
--   87%(112,942) 从未探活 —— 因为 enrich/sweep 取工作队列的查询在 13 万 active 上撞 statement_timeout
--   静默失败，死岗/薄卡清不掉。150 修了 summary-drain 的 fetch_queue；这里修 liveness-sweep 的
--   fetch_liveness_queue，并把首页计数从虚高的裸 count(active) 换成「有效在招」。
--
-- 大表建索引须抬超时（默认 ~2min 会被杀致整迁移回滚）。CREATE INDEX 取短暂写锁（秒级，部分索引）。
set local statement_timeout = '1800s';

-- (1) 失活清扫队列索引：enrich_backlog.py fetch_liveness_queue =
--       WHERE source_id IN(该 adapter 的源) AND status='active' ORDER BY enrich_checked_at NULLS FIRST。
--     与 150 同思路用 source_id 前导 → 每源各自按 enrich_checked_at 区间扫 + merge，免全表排序，脱离超时。
--     （150 那条谓词含 summary IS NULL，sweep 不限空 summary、且按 enrich_checked_at 序，故需独立索引。）
create index if not exists jobs_active_liveness_by_source_idx
  on jobs (source_id, enrich_checked_at nulls first)
  where status = 'active';

-- (2)「有效在招」计数索引：谓词与 count_valid_active_jobs() 完全一致 → count(*) 走 index-only scan。
create index if not exists jobs_valid_active_idx
  on jobs (id)
  where status = 'active' and summary is not null and char_length(btrim(summary)) >= 60;

-- 「有效在招」诚实计数 = active + 有 JD 正文(≥60 字)。首页计数卡改用它，取代裸 count(active)——
-- 后者含 25% 薄卡（如 moka 2.6 万张几乎全无正文）+ 大量未探活的假 active，把数字虚高到「十万多」。
-- 失活那部分由 liveness-sweep / dead-link-audit 持续探活下架，死岗离开 active 即自动退出本计数。
create or replace function count_valid_active_jobs()
returns bigint
language sql
stable
as $$
  select count(*)::bigint
  from jobs
  where status = 'active'
    and summary is not null
    and char_length(btrim(summary)) >= 60;
$$;

grant execute on function count_valid_active_jobs() to anon, authenticated, service_role;

-- 重建+回填后统计陈旧，刷新一次让规划器为上面查询选中新索引。
analyze jobs;
