-- 280 — 公告制招聘：每日复验所需的两列（verdict / expire_reason）
--
-- 为什么要（2026-09-18 逐条 live 复核 118 条在展示的公告后立）：
--   原设计只在**首次入库那一刻**看一眼标题，此后这行就一直 active 躺着，靠 deadline 或 45 天 TTL 下架。
--   实测这条链有三个洞，用户侧的表现就是「点进去是人家招聘结束的公示名单」：
--   ① 标题门放行了一批「过程通知」——「…关闭报名系统公告」「…专业测试公告」「…面试确认公告」
--      「…报名确认人数公告」「…岗位表」，它们标题里都带「招聘」，正向门直接放行；
--   ② 报名窗写在**正文**里，官方随时能另发一条公告把它关掉，入库时的判断当天就可能作废；
--   ③ 截止日抽取漏了「9月18日-9月24日」这类只有连字符、不写「至」也不写「截止」的区间写法
--      —— 实测 33 条 deadline 为空的公告里 **27 条正文其实写了**，于是它们全按「截止日未知」
--      一路展示到 45 天 TTL。
--   ⇒ 判断必须每天在**正文**上重做一遍（crawler/announcements/verify.py），这两列是它的落点。
--
-- ⚠️ expire_reason 只记原因、不改变 status 的语义：下架仍只走 status='expired'。
--   留着原因是为了「下架率突然飙升」时能一眼看出是判据变严了还是对方真关了（可观测性底线）。

alter table announcement_postings
  -- 展示档：ok=正常可报；index_page=官方汇总索引页（有真信息，但报名入口在别处，卡片要标注「需跳转」）。
  -- 刻意不把 index_page 直接下架：天津全省的公告就是这个形态，一刀切会让整省供给归零。
  add column if not exists verdict text not null default 'ok'
    check (verdict in ('ok', 'index_page')),
  -- 下架原因（status 变 expired 时写）：process_notice / registration_closed / deadline_passed / ttl / unreachable
  add column if not exists expire_reason text;

-- 复验按「最久没验过的优先」轮转取，需要这个前导列走索引（对齐岗位库 liveness-sweep 的做法）。
create index if not exists idx_announcement_recheck
  on announcement_postings (last_checked_at nulls first)
  where status = 'active';

comment on column announcement_postings.verdict is
  '展示档：ok / index_page（官方汇总索引页，报名入口在别处）。由 crawler/announcements/quality.assess 每日复验写入。';
comment on column announcement_postings.expire_reason is
  '下架原因：process_notice / registration_closed / deadline_passed / ttl / unreachable。只做可观测，不参与 RLS。';
