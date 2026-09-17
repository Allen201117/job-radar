-- 257_insight_items_grade_attempts.sql
-- 档位判档的「已尝试」簿记（修 insight_grade_extract 连续 9 天 graded:0 / ungraded:194 的空转）。
--
-- 现象：ops_runs 里 insight_grade_extract 从 2026-09-09 起每天 scanned≈194 / graded=0 / llm_calls=11，
-- 却始终 status=success（绿灯零产出）。
-- 根因：取数条件只有 `metric_value is null`，而这 194 条的正文本来就判不出档
-- （多为实习薪资 / 福利 / 学历要求这类与「实习体验强弱」无关的说法，模型按 prompt 的
-- 「看不出强弱必须返回 null」正确地返回了 null）。判不出 → metric_value 仍为 null →
-- 次日被同一条件重新选中 → 永久重试，每天白烧 11 次 LLM 调用。
--
-- 修法：记下每条尝试过几次、最后一次是什么时候；取数排除已达上限的条目（见
-- crawler/insight_grade_extract.MAX_GRADE_ATTEMPTS）。刻意不删不下架这些条目——它们只是
-- 「判不出档」，正文本身仍可展示，下架等于误杀。
alter table insight_items add column if not exists grade_attempts integer not null default 0;
alter table insight_items add column if not exists grade_attempted_at timestamptz;

-- 存量的 194 条已经被日更任务送过至少 9 次（09-09~09-17 每天 scanned≈194、graded=0），
-- 不必再等 3 轮才搁置：凡「判档任务上线（09-03）后创建 ≥3 天、至今仍无 metric_value」的，
-- 一律按已达上限处理。刻意用 created_at 而不是一刀切全表：3 天内新写入的（实测 1 条）
-- 可能还没轮到过，直接搁置等于没给它机会。
update insight_items
set grade_attempts = 3
where metric_value is null
  and status = 'active'
  and origin = 'public_web'
  and metric_key in ('overtime_level', 'promotion_pace', 'intern_experience')
  and created_at < now() - interval '3 days';

-- 取数是 origin+status+metric_key+metric_value+grade_attempts 的组合过滤，给它一条部分索引。
create index if not exists insight_items_grade_pending_idx
  on insight_items (metric_key, grade_attempts)
  where metric_value is null and status = 'active' and origin = 'public_web';
