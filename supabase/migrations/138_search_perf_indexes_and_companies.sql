-- ============================================================
-- 138 — 服务端岗位搜索：trigram 索引(让 ilike 走索引) + active_companies() RPC
-- ============================================================
-- 岗位库页从「全库塞浏览器前端筛选」改为「服务端有界筛选 + 分页」（库已涨到 10万+，前端全量加载不可行）。
-- 服务端按 城市/公司/关键词 做 ilike 收窄候选；无索引时每页都全表顺扫(实测 北京+产品 18.7s)。
-- pg_trgm + gin 索引让 `ilike '%词%'` 走索引 → 搜索从十几秒降到 ~1-2s。
-- 全部幂等(IF NOT EXISTS)；runner 用 `psql -1` 单事务执行，故用普通 CREATE INDEX(非 CONCURRENTLY)。
-- push 后由 migrate.yml 自动应用。

create extension if not exists pg_trgm;

-- 关键词命中 title/summary（搜索主路径）；城市命中 location；公司命中 company —— 都用 ilike，建 trigram。
create index if not exists jobs_title_trgm on jobs using gin (title gin_trgm_ops);
create index if not exists jobs_summary_trgm on jobs using gin (summary gin_trgm_ops);
create index if not exists jobs_company_trgm on jobs using gin (company gin_trgm_ops);
create index if not exists jobs_location_trgm on jobs using gin (location gin_trgm_ops);

-- 「活跃 + 按最新排序」是 SSR/列表/截断分页的通用形态，建复合索引免重复全表排序。
create index if not exists jobs_status_first_seen_idx on jobs (status, first_seen_at desc);

-- ---- active_companies():一次取全部「有活跃岗位的公司」去重列表（供 /api/jobs/companies） ----
-- 服务端筛选后，公司下拉项不能再从「浏览器已加载的一小撮岗位」派生（那会只剩几家——正是本次要修的问题）。
-- 单次 group by 顺扫(无深 offset，不会 statement timeout)，返回全 ~500+ 家。
create or replace function public.active_companies()
returns table(company text)
language sql
stable
security definer
set search_path = public
as $$
  select j.company
  from jobs j
  where j.status = 'active' and j.company is not null and j.company <> ''
  group by j.company
  order by j.company
$$;

-- jobs 本就「所有人读」(002_rls)；把只读聚合函数授给匿名/登录/服务角色。
grant execute on function public.active_companies() to anon, authenticated, service_role;
