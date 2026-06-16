-- 删除迁移 148 下架的坏链 Workday 岗（/details/ 格式），回收 Supabase 空间。
--
-- 为何能删干净：重抓已用修好的适配器把每个岗的**正确 /job/ 版本**作为新行入库（canonical 不同 =
-- 另一批行），这批 /details/ 行既打不开、又是纯重复死行，无保留价值。
-- 为何 148 不够：148 只是 UPDATE→status='expired'，行仍物理躺在表里（UPDATE 还多产生 dead tuple、
-- 短期更占空间）。真正回收空间 = 这里 DELETE 删行 + 之后 maintenance-vacuum 的 VACUUM FULL 缩表还盘。
--
-- FK：job_actions.job_id 是 ON DELETE CASCADE → 删 jobs 行会自动连带删这批坏行上的收藏/忽略
--   （坏链行，用户的操作本就对不上正确的 /job/ 行，删之无碍）。
-- 事务：不写显式 begin/commit —— db-migrate.sh 用 `psql -1`（--single-transaction）已把整个文件包进
--   一个事务（148 的「already a transaction in progress」告警即源于多写了 begin）。
set local statement_timeout = '1800s';

delete from jobs
 where status = 'expired'
   and jd_url like '%myworkdayjobs.com/%/details/%';
