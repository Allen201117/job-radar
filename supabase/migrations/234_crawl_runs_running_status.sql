-- 234 — crawl_runs.status 增加 'running'，让「跑崩了」不再伪装成「按设计跳过」
--
-- 病：db.create_crawl_run() 插入时的**占位状态就是 'skipped'**，跑完才被 update 覆盖成终态。
-- 于是进程半途死掉（CI 超时/取消、OOM、被 kill）的源，在台账里跟 robots 拦截 /
-- adapter should_skip 主动跳过的源**长得一模一样**，规则 F 又只认 status='failed'
-- → 一次 CI 超时吞掉 10 个源，台账上不留任何异常信号（2026-09-05 实测近 7 天 25 条中招，
--   其中 09-05 05:06 有 10 个源在约 30 秒内集体留下空记录）。
--
-- 姊妹表 discovery_runs 的 CHECK 早就有 'queued'/'running'，crawl_runs 是唯一的例外 —— 对齐它。
--
-- ⚠️ CHECK 约束是**全量重建不是增量**：下面必须把旧的四个值一个不落抄全，
--    漏一个会把存量行打成非法。旧定义（本次迁移前生产实测）：
--      CHECK (status = ANY (ARRAY['success','partial_success','failed','skipped']))
--
-- 存量不回填：历史上那些 status='skipped' + finished_at IS NULL 的孤儿保持原样，
-- 规则 I 用的是 `finished_at IS NULL` 这个**与 status 无关**的判据，新旧两种都认得出。

alter table crawl_runs drop constraint if exists crawl_runs_status_check;

alter table crawl_runs add constraint crawl_runs_status_check
  check (status = any (array['running'::text,
                            'success'::text,
                            'partial_success'::text,
                            'failed'::text,
                            'skipped'::text]));
