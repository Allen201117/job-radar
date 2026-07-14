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
-- （见 CLAUDE.md「加唯一约束类迁移」）。保留每个 URL 最早创建的那一行。
-- 被删的是当天刚入库、尚未被 daily-crawl 抓过的重复行（无 jobs / crawl_runs 关联，不产生孤儿）。
set local statement_timeout = '600s';

delete from public.sources s
where s.id in (
  select id
  from (
    select id, row_number() over (partition by source_url order by created_at asc, id asc) as rn
    from public.sources
  ) t
  where t.rn > 1
);

create unique index if not exists sources_source_url_key on public.sources (source_url);
