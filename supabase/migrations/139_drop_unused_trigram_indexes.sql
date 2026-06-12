-- ============================================================
-- 139 — 撤掉 138 建的 trigram 索引（实测对 2~3 字中文 ilike 几乎无选择性，且给爬虫 upsert 加无谓写开销）
-- ============================================================
-- 138 本想用 pg_trgm 让 `ilike '%词%'` 走索引，但中文岗位词多为 2 字(产品/北京/算法)，
-- pg_trgm 对其选择性极差(单页仍 ~6s)，方案改为「(status,first_seen_at) 复合索引按最新翻页 + JS 精筛」
-- (见 lib/job-search.ts)，不再用 ilike。故这 4 个 gin trgm 索引纯属负担(尤其 summary 长文本的写维护)，撤掉。
-- 保留：jobs_status_first_seen_idx(复合索引，扫描主力) 与 active_companies() RPC。
-- 幂等；push 后由 migrate.yml 自动应用。

drop index if exists jobs_title_trgm;
drop index if exists jobs_summary_trgm;
drop index if exists jobs_company_trgm;
drop index if exists jobs_location_trgm;
-- pg_trgm 扩展留着（无害，可能他处用得上），仅撤索引。
