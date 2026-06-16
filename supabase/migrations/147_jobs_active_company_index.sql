-- ============================================================
-- 147 — career-path / 公司聚合提速：jobs (company) WHERE status='active' 部分覆盖索引
-- ============================================================
-- 现象：/path 职业路径页 500「canceling statement due to statement timeout」。
-- 根因 = 145 的 active_job_counts_by_company()（`group by company`）要扫全部在招行，但库已涨到
--   16.7 万行（在招占多数、单行很宽：含 summary + search_bigrams/search_doc 等 tsvector），
--   且没有覆盖 (company) WHERE status='active' 的索引——只能走全表/全-status 索引扫 + 堆可见性回查。
--   实测：RPC ~10s 超时；连 `count(*) where status='active'` 都 ~9s 超时（status 低选择度）。
--
-- 修法：建「部分覆盖索引」——仅含在招行、按 company 有序。这样
--   · active_job_counts_by_company()（group by company，145）
--   · active_companies()（distinct company，138；搜索「公司」面板用）
--   都能走 index-only scan：扫描量从「~25 万宽行堆」收敛到「~11 万条 company 索引项（数 MB）」，
--   亚秒返回，彻底脱离 statement_timeout。两函数 WHERE 同为 status='active'，故索引谓词取公因子。
--
-- 非 CONCURRENTLY：db-migrate.sh 用 `psql -1` 单事务跑迁移，CREATE INDEX CONCURRENTLY / VACUUM
--   都不能进事务。普通 CREATE INDEX 取 SHARE 锁短暂阻塞写入（部分索引 ~11 万行，秒级）；
--   按 CLAUDE.md 在事务内抬 statement_timeout，防被 Supabase 默认 ~2min 杀掉。
-- 幂等；push 自动应用。

set local statement_timeout = '1800s';

create index if not exists jobs_active_company_idx
  on jobs (company)
  where status = 'active';

-- 重建+回填后统计可能陈旧，刷新一次让规划器选中新索引并正确估算分组数。
analyze jobs;
