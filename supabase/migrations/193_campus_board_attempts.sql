-- 193 — 校招板块探测台账（批量补校招源的记忆）
--
-- 背景：2026-08-04 手工逐家啃自建门户（阿里/快手/美团/网易），每家 30-45 分钟，
-- 而库里 94% 的源是通用 ATS 平台——方向错了。平台的校招板块 URL 是模板化的，
-- 可批量推导 + 批量探（实测 152 个候选 20 秒分诊完、命中 140）。
-- 本表是那条批量流水线的记忆：谁探过、卡在哪一步、什么时候值得再看。
--
-- 为什么必须有台账：不同失败原因的复查价值差几个数量级——
--   robots 禁止 / 与既有源重复 = 平台机制决定，基本永不改变（退避 10 年 ≈ 永久搁置）
--   板块存在但 0 岗 = 正式批还没开，两周后完全可能有货（退避 14 天）
-- 没有台账就只能天天全量重探，把 CI 预算烧在必然失败的候选上。

create table campus_board_attempts (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  adapter_name text not null,
  candidate_url text,
  state text not null default 'unknown' check (state in (
    'unknown',
    'robots_blocked',    -- robots.txt 禁止抓取（合规边界，不绕过）
    'unreachable',       -- 404 / 连不上 / 页面是空壳
    'empty_board',       -- 板块存在但当前 0 岗（开闸前的正常状态）
    'duplicate_board',   -- 与该租户既有源返回同一批岗，建了就是重复源
    'source_added',      -- 已插 disabled 源，等验收
    'no_healthy_jobs',   -- 真抓了但回读不到健康岗
    'healthy'            -- 验收通过，已 enable
  )),
  note text,
  recheck_after date,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (company, adapter_name)
);

create index idx_campus_board_attempts_queue
  on campus_board_attempts (state, recheck_after nulls first);

alter table campus_board_attempts enable row level security;
revoke all on table campus_board_attempts from public, anon, authenticated;
grant all on table campus_board_attempts to service_role;
grant select on table campus_board_attempts to authenticated;

create policy "Admins can read campus_board_attempts"
  on campus_board_attempts for select
  to authenticated
  using (exists (select 1 from profiles where id = auth.uid() and role = 'admin'));

comment on table campus_board_attempts is
  '校招板块批量探测台账：每家探到哪步/为何失败/何时复查。'
  '按 state 退避（robots/duplicate ≈ 永久搁置，empty_board 14 天）避免天天空烧。';
