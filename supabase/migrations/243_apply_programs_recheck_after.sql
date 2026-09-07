-- 243 — 投递入口加「该复查了」的日期，并把华能当前无在窗公告如实写进卡片
--
-- 背景：迁移 242 把中行 / 邮储 / 中国邮政 指到了**具体公告全文**（创始人要的「准」），
-- 代价是这三条会随报名窗口过期变旧，而 apply_programs **没有任何自动复查机制**
-- （gap_census.classify_company 把这类公司钉在 manual_review 且 next_retry_at=None）。
-- 242 只把复查时点写进了 notes —— notes 没人读就等于没写。
--
-- 所以补一个**机器读得到**的字段 recheck_after，配 ops_watchdog 规则 J：
--   到期（或超过 45 天没人重新核实）就开 GitHub Issue，把「链接变旧」从静默变成会叫的。
--
-- ⚠️ 刻意是 date 而不是「从 window_text 解析出来的日期」：window_text 是**原文照抄**
--   （迁移 226 的设计，各家写法不一，硬解析会造出假精度）。要机器判就单独存一个人填的日期，
--   别去解析自由文本 —— 解析错了会在「已经过期」和「还没到期」两个方向上都出错。

alter table apply_programs
  add column if not exists recheck_after date;

comment on column apply_programs.recheck_after is
  '该日期之后这条入口需要人工复查（多为公告报名截止日 +1 天）。为空 = 没有明确到期日，'
  '由 ops_watchdog 规则 J 的「45 天没重新核实」兜底。';

-- 三条指向具体公告的行：截止日 +1 天。
update apply_programs set recheck_after = date '2026-10-08', updated_at = now()
 where company = '邮储银行' and program_type = 'announcement';   -- 报名截止 2026-10-07
update apply_programs set recheck_after = date '2026-10-10', updated_at = now()
 where company = '中国银行' and program_type = 'announcement';   -- 报名截止 2026-10-09
update apply_programs set recheck_after = date '2026-11-01', updated_at = now()
 where company = '中国邮政' and program_type = 'announcement';   -- 简历接收截止 2026-10-31

-- 华能：入口本身没问题（根页面就是招聘公告列表），但**当前一条在窗公告都没有** ——
-- 列表里 5 条全是 2026 届、status=3（该站字典 3=过期），窗口 2025-09-12 ~ 2025-10-31。
--
-- 为什么不下架：它确实是公告制，卡片上那句「对方按公告批量招聘」是真话，
-- 下架再过几天 2027 届一发又要加回来，是无谓 churn（上一届 2026 届是 2025-09-12 开的，
-- 今天 2026-09-07，就在同一个时间点上）。
-- 为什么也不能装作没事：用户点进去看到一屏「已结束」，等于我们给了个当下投不了的入口。
-- 折中 = 把这件事如实写进 window_text（页面会把它单独渲染成一行琥珀提示），
-- 并设 recheck_after，到点没发 2027 届就由规则 J 叫人来重新评估。
update apply_programs
   set window_text = '当前在架的是 2026 届公告（网申 2025-09-12 ~ 2025-10-31，已结束）；2027 届通常 9 月发布',
       recheck_after = date '2026-10-31',
       updated_at = now(),
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07（迁移 243）：入口没问题，但**当前无在窗公告**（列表 5 条全是 2026 届、status=3 过期）。已把这句如实写进 window_text，并设 recheck_after=2026-10-31。
到期若仍无 2027 届公告 ⇒ 重新评估这行还该不该对用户展示（同迁移 240 边界二的判断）。$md$
 where company = '中国华能' and program_type = 'announcement';

-- 断言：指向**具体公告全文**的行必须有 recheck_after，否则没人知道它什么时候会变旧。
-- 判据用「URL 里带年月目录 + .html 文件名」这种一眼是详情页的形态，够粗但不会误伤列表页。
do $$
declare bad text;
begin
  select string_agg(company || ' <' || entry_url || '>', ', ')
    into bad
    from apply_programs
   where enabled
     and program_type = 'announcement'
     and entry_url ~ '/[0-9]{6}/[a-z0-9_]+\.html?$'
     and recheck_after is null;
  if bad is not null then
    raise exception '迁移 243 断言失败：指向具体公告的入口没有 recheck_after，到期无人知晓 → %', bad;
  end if;
end $$;
