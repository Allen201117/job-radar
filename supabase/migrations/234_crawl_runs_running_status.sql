-- 234: crawl_runs 增加 running 占位状态 —— 把「按设计跳过」和「跑到一半没收尾」分开。
--
-- 现象（2026-09-05 实测）：近 7 天 status='skipped' 共 2,734 行，其中 15 行 finished_at 与
--   error_message 双 NULL；全表这样的孤儿 72 行，最早 2026-06-09。它们不是跳过 ——
--   crawler/db.py 的 create_crawl_run 在 insert 那一刻就写死 'skipped' 当占位符，之后才由
--   run.py 的 update_crawl_run 覆盖成真实结果。只要进程中途没了（CI 超时/取消、OOM、被 kill、
--   或收尾那次写库连抛两次），这行就永远停在 'skipped'，和 robots 拦截 / adapter.should_skip
--   主动跳过**在 status 上完全无法区分**。
--
-- 为什么动 status 而不是只让消费方自己看 finished_at：
--   ① 'skipped' 是**错的**，不是信息不全。留着它就等于要求每个新消费方都记得加
--      `and finished_at is not null` —— 漏一个就静默错算，正是本仓库反复吃亏的那类约束。
--   ② discovery_runs 的 CHECK 里本来就有 'running'（queued/running/success/partial_success/
--      failed/skipped）。同一族台账用同一套生命周期词汇，是对齐不是发明。
--   ③ 只看 finished_at is null **分不清「此刻正在飞」和「已经没收尾」**：2026-09-05 当场看到的
--      10 个「空记录」（华为/字节跳动/伊利…）1~3 分钟后全部 success 收尾了，它们只是查询那一瞬间
--      在跑。有了 running，判据才写得出来 —— running 且 started_at 早于宽限期 = 没收尾。
--      （近 30 天最长的一轮 27m16s，p99.9=6m38s，>30min 的 0 轮；watchdog 取 90min 宽限。）
--
-- ⚠️ CHECK 是**全量重建**而非增量：下面必须把 4 个旧值一个不落抄全，漏一个会把存量行打成非法。
alter table crawl_runs drop constraint if exists crawl_runs_status_check;

alter table crawl_runs add constraint crawl_runs_status_check
  check (status in ('success', 'partial_success', 'failed', 'skipped', 'running'));

comment on column crawl_runs.status is
  'running=已开跑未收尾（create_crawl_run 的占位符；超过宽限期仍是它 = 进程中途死了，见 ops_watchdog 规则 I）；'
  'success/partial_success/failed=跑完的结论；skipped=robots 或 adapter.should_skip 主动跳过（必带 error_message 说明原因）。';

-- 存量孤儿归位：谓词就是「占位符从没被覆盖过」这一个事实，与 CHECK 放开后新写入的 running 同义。
-- 这不是把数字改好看 —— 它让 skipped 的计数第一次是真的（2,734 → 2,719），
-- 并让 72 条此前不可见的「没收尾」进入告警视野。
-- 大表（35 万行）全表更新：Supabase 默认 statement_timeout≈2min，先抬掉，别让整个迁移回滚。
set local statement_timeout = '1800s';

update crawl_runs
set status = 'running'
where status = 'skipped'
  and finished_at is null;
