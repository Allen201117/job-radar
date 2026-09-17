-- 258：校招渠道加第五态 `pending`（2026-09-17）
--
-- 现象：24 家国内必投公司被记成 campus_channel='idle'（「有 campus/mixed 源但近 3 天零校招岗」），
-- 其中 6 家（潍柴 / 华为 / 中通 / 奔驰 / 迈瑞医疗 / 中国金茂）**根本不是零校招岗**。
--
-- 根因：普查按 `jobs.recruitment_category = '校招'` 数，而这一列会被库里的触发器
-- jobs_guard_recruitment_class（jobs-db/schema.sql）**主动置 NULL**——列表一重抓、分类依据一变
-- 就把旧结论作废，等 backfill-recruitment-category 重新算出来。NULL 的语义是「还没算」，
-- 不是「不是校招」；普查把它当成了后者，于是「刚抓完还没回填」被读成「这个渠道零产出」。
-- 窗口并不短：那条 backfill 的 cron 写的是每 2 小时，GitHub 实际只跑出约 4 次/天
-- （09-16~17 实测相邻两次间隔最长 7 小时），而普查每天固定时刻跑一次，撞上是常态。
--
-- 证据（2026-09-17 香港库实测，离线用同一份 JS 裁决 scripts/classify-recruitment.js 重算）：
--   全库 active 492,643 行里 recruitment_category 为 NULL 的 3,380 行、全部是近 3 天新抓的；
--   潍柴 259 行全 NULL → 重算得 36 个校招；华为 101 行 NULL → 70 校招 + 31 实习；
--   中通 102 → 23；奔驰 11 → 10；金茂 10 → 8；迈瑞 263 → 1 校招 + 11 实习。
--   **反向**（列里写着校招、重算说不是）在这 24 家 2,200 行里 **0 条** —— 不是分类规则错了，
--   是普查把「还没算」读成了「没有」。
--
-- 修法（crawler/gap_census.py 同一 commit）：普查多数一个 `unclassified_recent`，
-- 「渠道在 + 零校招岗 + 还有没算完的行」→ `pending`（还不知道），而不是 `idle`（已确认零产出）。
-- ⚠️ pending **只降级 idle，不降级 missing**：missing 是按 sources 有没有 campus/mixed 源判的，
--    与这一列无关，NULL 推翻不了它；把 missing 也说成 pending 会让真缺口从看门狗规则 O 里消失。
--
-- CHECK 是全量重建的写法：旧四个取值一个不落抄全，只加 pending。
alter table public.must_apply_gap_attempts
  drop constraint if exists must_apply_gap_attempts_campus_channel_check;

alter table public.must_apply_gap_attempts
  add constraint must_apply_gap_attempts_campus_channel_check
  check (campus_channel in ('healthy', 'idle', 'pending', 'missing', 'unknown'));

comment on column public.must_apply_gap_attempts.campus_channel is
  '校招渠道：healthy=近3天有校招岗 / idle=有campus·mixed源且近3天的岗都已分类、确认零校招岗 / '
  'pending=有campus·mixed源但近3天还有未分类的岗（recruitment_category 为 NULL），判不了 / '
  'missing=无校招渠道源 / unknown=海外或未普查。与 state 正交。';
