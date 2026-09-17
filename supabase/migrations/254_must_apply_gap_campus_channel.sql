-- 254：必投缺口台账加「校招渠道」这一轴（2026-09-17）
--
-- 现象：国内必投 321 家里近 3 天有校招岗的只有 171 家（53%）：46 家只接了社招、20 家源坏了、89 家没源。
-- 而台账只有一个 state（healthy = 有健康岗），一家有 500 个社招岗就算 healthy，校招 0 也不报警 ——
-- 整个秋招季，系统对「对方校招开了、我们没接」这件事是瞎的；库里的 0 被读成「对方没开」正是它的产物。
-- 修法 = 渠道单独成轴（不改 state 语义）：
--   healthy = 近 3 天抓到过校招岗（产出反查优先：社招门户也可能出校招岗，见迁移 187 注释 3）
--   idle    = 有启用的 campus / mixed 源但近 3 天零校招岗（源坏了或对方还没开）
--   missing = 没有任何启用的校招渠道源（不管社招接没接）
--   unknown = 海外清单 / 尚未普查
alter table public.must_apply_gap_attempts
  add column if not exists campus_channel text not null default 'unknown'
    check (campus_channel in ('healthy','idle','missing','unknown')),
  add column if not exists campus_jobs_recent integer not null default 0,
  add column if not exists intern_jobs_recent integer not null default 0;

comment on column public.must_apply_gap_attempts.campus_channel is
  '校招渠道：healthy=近3天有校招岗 / idle=有campus·mixed源但零校招岗 / missing=无校招渠道源 / unknown=海外或未普查。与 state 正交。';
comment on column public.must_apply_gap_attempts.campus_jobs_recent is '近 3 天 last_seen 的校招岗数（本 scope）';
comment on column public.must_apply_gap_attempts.intern_jobs_recent is '近 3 天 last_seen 的实习岗数（本 scope）';

create index if not exists must_apply_gap_attempts_campus_channel_idx
  on public.must_apply_gap_attempts (scope, campus_channel);
