-- 职业洞察 v3 P0-3：业务线级信号派生的两块地基
--   ① 派生条目的幂等键（同一主体同一指标只能有一行，天天重算即覆盖）
--   ② 每日快照表（把「趋势」建立在真实时间序列上，而不是有幸存者偏差的推断上）

-- ── ① 派生信号的唯一键 ─────────────────────────────────────────────────
-- crawler/bu_signals.py 每天为每个主体重算全部指标。没有唯一键的话，一次重跑就多一份，
-- 页面会看到同一个指标的两个数字。这条索引是最后一道闸（正常路径靠代码 select-then-write）。
-- 只约束 origin='derived'：搜索型 claim 未来也可能挂 subject_id + metric_key，
-- 同一主体同一指标允许有多条不同来源的说法，不该被这条唯一性误伤。
create unique index if not exists uniq_insight_items_derived_metric
  on insight_items (subject_id, metric_key)
  where origin = 'derived' and subject_id is not null and metric_key is not null;

-- ── ② 主体每日快照：趋势的唯一诚实来源 ──────────────────────────────────
-- ⚠️ 为什么不能直接拿 jobs.first_seen_at 分窗口算环比（本轮实测判断，别再退回去）：
--   expired 岗每天被 purge-expired 永久删除（job_events 也随 on delete cascade 一起没了），
--   于是「30-60 天前挂出」的岗只剩活到今天的那部分，而「近 30 天」几乎完整。
--   两个窗口的口径不同，直接相除会系统性地把环比算高——把一个平稳的业务线说成在扩张。
--   唯一无偏的办法是我们自己每天记一笔，让时间序列真的存在。
--   ⇒ 本表从今天开始积累；hiring_trend_30d_pct 等到有可比快照后由同一脚本产出，
--     在那之前**整字段省略**（spec §1.5 硬规则：样本不足不显示，不给推断）。
create table if not exists insight_subject_daily (
  subject_id   uuid not null references insight_subjects(id) on delete cascade,
  day          date not null,
  -- 当日该主体的在招岗位数（口径与 insight_subjects.job_count 相同）
  active_count int  not null,
  -- 当日回看 30 天内首次出现且仍在招的岗位数（观测量，非无偏新增量）
  new_30d      int,
  created_at   timestamptz not null default now(),
  primary key (subject_id, day)
);

comment on table insight_subject_daily is
  '洞察主体的每日在招规模快照。趋势类指标只能由本表的跨日对比得出，不得由 jobs.first_seen_at 分窗口推断（expired 每日 purge，历史窗口不完整）。';

create index if not exists idx_insight_subject_daily_day
  on insight_subject_daily (day desc);

alter table insight_subject_daily enable row level security;
-- 与 insight_subjects 同口径：读走聚合后的 insight_items，本表只服务派生脚本与 admin。
drop policy if exists insight_subject_daily_admin on insight_subject_daily;
create policy insight_subject_daily_admin on insight_subject_daily
  for all using (
    exists (select 1 from profiles p where p.id = auth.uid() and p.role = 'admin')
  );
