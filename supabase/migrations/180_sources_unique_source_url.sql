-- 扩源重复入库根治：source_url 唯一约束（DB 层兜底）。
--
-- 根因（2026-07-14 live 实测）：sources 越过 1000 行（实测 1042）后，crawler 的
-- existing_source_keys() 走 PostgREST 单次查询——默认最多只返回 1000 行——拿到的是**残缺**的
-- 去重集合，尾部（恰恰是最新入库的源）被截断掉 → 去重失效 → 同一 source_url 被反复插入。
-- 当天 auto-discover-browser 连跑两轮，把 15 个 URL 各插了 2 次（中金公司/哈啰/我爱我家…）。
-- 影响面会随源池增长而恶化：三条扩源道（httpx / browser / overseas）共用这个函数。
--
-- 代码侧已改为分页拉全量（crawler/auto_discover.py::existing_source_keys）；这里在 DB 层
-- 上唯一约束治本，任何写入路径都不可能再插重复源。
--
-- ⚠️ 先清存量重复再建唯一索引：生产有重复时 CREATE UNIQUE INDEX 会失败并永久阻塞后续迁移
-- （见 CLAUDE.md「加唯一约束类迁移」）。保留每个 source_url 最早创建的那一行。
--
-- ⚠️ 不能直接 delete：重复源已被 daily-crawl 抓过，crawl_runs.source_id / jobs.source_id 有
-- 外键指向它们（第一版迁移就是这么挂的：violates foreign key constraint crawl_runs_source_id_fkey）。
-- 正确做法是**先把引用重定向到保留行**（保住抓取历史，不丢数据），再删重复行。
-- 注：Supabase 的 jobs 已是空表（热表在自建香港 PG，无跨库外键），这里的 update 是防御性的；
-- company_watch_requests.matched_source_ids 是 uuid[] 无外键、不阻塞删除，残留 id 不影响
-- resolve_watch_requests 的 append 语义，故不动。
set local statement_timeout = '600s';

create temporary table _sources_dup_map as
with ranked as (
  select
    id,
    first_value(id) over (partition by source_url order by created_at asc, id asc) as keep_id,
    row_number() over (partition by source_url order by created_at asc, id asc) as rn
  from public.sources
)
select id as dup_id, keep_id from ranked where rn > 1;

update public.crawl_runs cr
set source_id = m.keep_id
from _sources_dup_map m
where cr.source_id = m.dup_id;

update public.jobs j
set source_id = m.keep_id
from _sources_dup_map m
where j.source_id = m.dup_id;

delete from public.sources s
using _sources_dup_map m
where s.id = m.dup_id;

drop table _sources_dup_map;

create unique index if not exists sources_source_url_key on public.sources (source_url);
