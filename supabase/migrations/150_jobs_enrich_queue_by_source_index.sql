-- ============================================================
-- 150 — enrich-backlog drain 提速：jobs (source_id, first_seen_at desc)
--        WHERE active AND summary IS NULL AND enrich_fail_count<3 部分索引
-- ============================================================
-- 现象：enrich-backlog workflow 的 **hotjob** 分片频繁失败（其余 4 分片正常）。
--   crawler/enrich_backlog.py fetch_queue 报 57014「canceling statement due to statement timeout」。
--   表现为「时好时坏、专挑 hotjob」：多数轮秒级成功，偶发分钟级后被杀。
--
-- 根因 = 133 的 idx_jobs_enrich_queue 只按 (first_seen_at desc) 建、谓词不含 source_id；
--   而 fetch_queue 的查询是
--     WHERE source_id IN(该 adapter 的源) AND summary IS NULL AND status='active'
--           AND enrich_fail_count<3  ORDER BY first_seen_at DESC
--   2026-06-15 重建库后 null-summary 的在招岗一度近乎全表，这条**共享**部分索引很大；
--   hotjob backlog 最大最旧，按日期序扫这条大索引、再用 source_id 做残差过滤，
--   要趟过海量非 hotjob 行 → 超 Supabase 默认 ~2min statement_timeout。随富化推进 backlog
--   收缩，多数轮次又压线通过 → 间歇性失败。（与 147 同一「重建后 statement_timeout」病根。）
--
-- 修法：加 source_id 前导的部分索引。source_id IN 查询改走「每源各自的 first_seen_at desc
--   区间扫 + merge-append」，扫描量从「全局 backlog」收敛到「该 adapter 自己的 backlog」，
--   且天然满足 ORDER BY first_seen_at DESC（免排序）。彻底脱离 statement_timeout，5 分片同等受益。
--   保留 133 旧索引（不删）：无 source_id 过滤的全量场景仍可用，仅新增。
--
-- 非 CONCURRENTLY：db-migrate.sh 用 `psql -1` 单事务跑迁移，CREATE INDEX CONCURRENTLY 不能进事务；
--   普通 CREATE INDEX 取 SHARE 锁秒级阻塞写入（部分索引仅含 backlog 行）；按 CLAUDE.md 在事务内
--   抬 statement_timeout，防被 Supabase 默认 ~2min 杀掉。幂等；push 后由 migrate.yml 自动应用。

set local statement_timeout = '1800s';

create index if not exists jobs_enrich_queue_by_source_idx
  on jobs (source_id, first_seen_at desc)
  where status = 'active' and summary is null and enrich_fail_count < 3;

-- 重建+回填后统计陈旧，刷新一次让规划器为 source_id IN 查询选中新索引。
analyze jobs;
