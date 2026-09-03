-- 208 — crawl_runs 补一个按时间的索引。
--
-- 背景（2026-09-03 实测，非推测）：管理员看板最重的那条 RPC `admin_health_snapshot`
-- 里的 `crawl_today` 段只按 `started_at` 过滤 crawl_runs（33 万行），
-- 而表上唯一可用的索引是 `idx_crawl_runs_source (source_id, started_at desc)`——
-- 时间是**第二列**，用不上定位，只能把整个索引从头扫到尾。
--
--   EXPLAIN 实测：Index Scan using idx_crawl_runs_source，Buffers: shared hit=6692，
--   缓存热时 24.9ms；缓存一冷（需要真读盘）实测 1.64s。
--   而今天的数据只有 4,236 行 / 332,445 行 = 1.3%。
--
-- 加一个按时间的独立索引，就能直接定位到「今天」这一小段，而不是翻完整个索引。
--
-- ⚠️ 不用 CONCURRENTLY：迁移器把每个文件包在事务里跑，CONCURRENTLY 不能在事务内执行。
--    33 万行建索引只需几秒，期间短暂阻塞写入，可接受。
create index if not exists idx_crawl_runs_started_at
  on public.crawl_runs (started_at desc);
