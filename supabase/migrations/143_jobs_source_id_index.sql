-- ============================================================
-- 143 — jobs.source_id 加索引：让「按源取/下架某源全部岗」不再全表扫超时
-- ============================================================
-- 死链 --sweep（按 source_id 拉某源全部 active 岗逐个审计）与 enrich/源管理里的 source 维度查询，
-- 之前 jobs.source_id 无索引 → eq(source_id) 全表扫撞 statement_timeout（智元 sweep 本地/CI 都卡在取数）。
-- btree 索引即可（等值过滤）。102K 行构建很快、锁很短。幂等；push 自动应用。
create index if not exists jobs_source_id_idx on jobs (source_id);
