-- 188: 校招岗数时序快照 —— 用来发现「某公司秋招正式批开闸了」
--
-- 背景（2026-08-04）：校招与社招的供给形态完全不同。社招是涓流（每天来几个），
-- 校招是**闸门**——一家公司开正式批就一次性放出全部岗位，从几十跳到几百上千。
-- live 佐证：腾讯 careers API 社招 Count=2215，而校招 Count 只有 17（2027 届还没开闸）；
-- 阿里淘天校招频道 34 条且标题仍写「26 届」。闸门一开这两个数字会瞬间翻几十倍。
--
-- 为什么需要新表而不是复用 crawl_runs：
--   crawl_runs.jobs_found 是该源**全部**岗位数（社招+校招混在一起），校招那几十个岗的突增
--   会被社招几千个岗的正常波动完全淹没，根本看不出来。开闸检测必须盯**校招岗单独的计数**。
--   ⚠️ 抓全自检不在这里做——crawl_runs 的 reported_total / coverage_complete +
--   crawl_coverage_snapshot()（迁移 176/177）已经在做，本表不重复造。
--
-- 为什么只在数字变化时插行：
--   高频车道每小时一轮 × 约 200 个源 = 每天 4800 行，一个招聘季 50 万行，绝大多数是重复数字。
--   本表语义是**变更日志**不是采样日志——开闸检测只关心「和上次比变了多少」，没变的行毫无信息量。
--   prev_campus_job_count 冗余存下来，是为了让「当时依据什么判的开闸」可回溯（判据变了也能复盘）。

create table campus_board_snapshots (
  id bigserial primary key,
  source_id uuid not null references sources(id) on delete cascade,
  company text not null,
  -- 该源当下在库的 active 校招岗数（抓完回读香港 jobs 库得到）
  campus_job_count integer not null,
  -- 上一条快照的计数；null = 该源首次留痕（首次一律不判开闸，见 crawler/campus_lane.detect_surge）
  prev_campus_job_count integer,
  -- 是否判定为「开闸」（判据见 crawler/campus_lane.detect_surge：倍数 3 或增量 50）
  surge boolean not null default false,
  captured_at timestamptz not null default now()
);

-- 取某源最近一条快照（开闸判据的基线）——这是本表最热的查询
create index idx_campus_snapshots_source_recent
  on campus_board_snapshots (source_id, captured_at desc);

-- 运营看板「今日开闸公司」
create index idx_campus_snapshots_surge
  on campus_board_snapshots (captured_at desc)
  where surge;

alter table campus_board_snapshots enable row level security;
revoke all on table campus_board_snapshots from public, anon, authenticated;
grant all on table campus_board_snapshots to service_role;
grant select on table campus_board_snapshots to authenticated;

create policy "Admins can read campus_board_snapshots"
  on campus_board_snapshots for select
  to authenticated
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );

comment on table campus_board_snapshots is
  '校招岗数变更日志（仅在计数变化时插行），用于检测秋招/春招正式批开闸并触发加急全量重抓。'
  '⚠️ 不承担撤岗判定：计数下降只记录、绝不据此标 expired（见迁移 188 注释）。';

-- ⚠️⚠️ 红线：本表**不是撤岗依据**。
-- campus_job_count 下降有两种成因，处置完全相反：① 岗位真撤了；② 列表接口这轮只返了子集
-- （超时、限流、分页断、平台改版）。从计数下降反推撤岗会误删在招岗——2026-07-29 华为
-- 460 个在招岗就是这么差点被清掉的（见记忆 job-radar-liveness-rotation-starvation）。
-- 撤岗一律走既有的逐岗探活（liveness-sweep / dead-link-audit）与 list-absence 双安全闸，
-- 本迁移不新增任何撤岗路径。
