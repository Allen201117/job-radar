-- ============================================================
-- 145 — career-path 在招计数下沉到 DB：active_job_counts_by_company() RPC
-- ============================================================
-- app/api/career-path 原本 `select company from jobs where status='active'`——把全部在招行的
-- company 列拉进 serverless 内存，再在 JS 里逐行 filter 计数。这跟搜索 v2 已服务端聚合的口径分裂，
-- jobs 涨上去会变慢/OOM。改为 DB 侧 group by company 聚合：payload 从「全部在招行(~10万)」
-- 收敛到「去重公司数(~500+)」。
--
-- 为什么 SQL 只做 group by、不做匹配：公司别名归一（lib/insight-match.ts companyMatches 的
-- 归一化 + 双向子串 + 资格门语义）很难在 SQL 里逐字复制、易踩口径分裂。故保留在 JS，对聚合后的
-- 小集合做 sum——结果与「逐行 filter 计数」完全一致（每行恰属一个 company，按 company 分组求和
-- == 逐行计数）。镜像 138 的 active_companies()。幂等；push 自动应用。

create or replace function public.active_job_counts_by_company()
returns table(company text, job_count int)
language sql
stable
security definer
set search_path = public
as $$
  select j.company, count(*)::int as job_count
  from jobs j
  where j.status = 'active' and j.company is not null and j.company <> ''
  group by j.company
$$;

-- jobs 本就「登录可读」(002_rls)；把只读聚合函数授给匿名/登录/服务角色（与 active_companies 同口径）。
grant execute on function public.active_job_counts_by_company() to anon, authenticated, service_role;
