-- 242 — 公告制入口改指「真正的公告页」，不再停在门户首页（2026-09-07 逐条真浏览器核验）
--
-- 现象（创始人反馈）：「公告制的入口那里你给的链接都是点击跳转到企业官网，但不是具体的
--   公告页面，这里不准。」实测 13 条 enabled 的 announcement 里 6 条落在门户根 / 平台首页上：
--   中煤 zhaopin.chinacoal.com、华电 rencaishichang.chd.com.cn、大唐 zhaopin.china-cdt.com、
--   国网 .../static/home.html、邮储 /cn/gyyc/rczp/、中行 /aboutboc/bi4/。
--
-- 根因不是「核验没做」，是**核验回答错了问题**：迁移 231/239/240 问的是「这家有没有逐岗页」，
--   答案「没有」都是对的；但据此就把 entry_url 填成门户根，等于只回答了「该不该进这一页」，
--   没回答「用户点下去看到什么」。最典型的是大唐——239 的 notes 写着「连公告本身都没有独立
--   URL（javascript:showView）」，这句没错，但**公告列表页 zpgg_index.html 是有 URL 的**，
--   当时没往下找一层。
--
-- 判据升级为：announcement 的 entry_url 必须**打开后第一屏就看得见招聘公告条目**。
--   按能拿到的最深一层取，分两档：
--     ① 对方当前挂着具体公告 → 直接指公告全文（邮储 / 中行）；
--     ② 只有列表 → 指公告列表页（中煤 / 华电 / 大唐 / 国网）。
--   门户根只在「根页面本身就是公告列表」时才允许（只有华能一家，见
--   lib/apply-programs.ts 的 PORTAL_ROOT_IS_ANNOUNCEMENT_LIST 白名单 + 单测）。
--
-- ⚠️ notes 一律用 `coalesce(notes,'') || E'\n\n' || $md$…$md$` **追加**，不覆盖。
--   同一天迁移 239/240 刚给这些行写下「为什么这家没有逐岗页」的判定过程，那是**另一个问题**
--   的答案，不能被本次「为什么换了链接」顶掉。notes 是流水账，不是单值字段。
--
-- ⚠️ 与迁移 240 的一处**明确分歧**（中行）：240 的边界三写着「entry_url 指的是栏目页不是那条
--   2027 公告，所以 2026-10-09 截止后这行不会失效」——那是有意选的耐久性。本次按创始人的
--   明确指令改指公告本身（当前指令 > 既有实现）。代价（会随窗口过期变旧）用三件事兜：
--   截止日写进 window_text（页面单独渲染成一行琥珀提示）、常青列表页写进 description、
--   notes 里写死复查时点。
--
-- 🚫 本迁移**不动**东方电气 / 中国林业集团 / 中国烟草 / 中国稀土集团 / 中国邮政 /
--   国家开发银行 / 中国华能 这 7 行的 entry_url：本次逐条重新渲染，确认它们本来就落在
--   公告列表页或公告全文上（中国邮政指的就是 2027 年度联合校园招聘公告本身）。
--   只给华能追加一句白名单说明，其余零改动——没有需要改的就不要制造 diff。
--
-- 📌 写法约定（承 239/240）：description / notes 一律用美元引号 $md$...$md$。
--   一行写错整个迁移文件一起回滚（迁移 211 的教训）。
-- 📌 ⚠️ 迁移 240 是按 `where entry_url = '…'` 定位行的。本迁移改掉了 6 条 entry_url，
--   **以后再写这类迁移请按 company + program_type 定位**，否则会静默匹配 0 行。

-- ── ② 档：指到公告列表页 ────────────────────────────────────────────────────

-- 中煤：/notice 才是完整的「招聘公告」列表（全部 / 校园 / 社会 三个 tab + 搜索）。
update apply_programs
   set entry_url = 'https://zhaopin.chinacoal.com/notice',
       verified_at = now(),
       updated_at = now(),
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告页（原 https://zhaopin.chinacoal.com）：门户根只渲染首页摘要（只露 7 条公告），/notice 才是完整列表——live 10 条，最新两条 2026-09-07（江苏分公司第 2 次社招、西南分公司第九批）。
⚠️ 站内「查看更多」跳出来的是 /notice?s=<加密串>，那个带签名的 URL 打开是「暂无数据」——**别抄站内那条**，裸 /notice 才正常出数。$md$
 where company = '中国中煤' and program_type = 'announcement';

-- 华电：hash 路由，社招公告在 class_item_pk=10001。
update apply_programs
   set entry_url = 'https://rencaishichang.chd.com.cn/w3/#/w3/notice/main_view?class_item_pk=10001',
       program_name = '社会招聘公告（校招 / 实习在同站切换）',
       verified_at = now(),
       updated_at = now(),
       description = $md$华电招聘投的是「公告」不是岗位：一条公告对应一家分子公司的一批招聘，卡片上会把岗位名列出来（如「安全专工 / 化学工艺专工 +2」），但点不进单个岗位。这条链接直接落在**社会招聘公告**列表；顶部那排「青年骏才 / 校园招聘 / 实习招聘…」可以切到其它档，校招要到招聘季才会有正式公告。$md$,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告页（原 https://rencaishichang.chd.com.cn）：门户根渲染出来只有一排 tab + 登录按钮，**一条公告都没有**（curl 拿到的 body 只有 391 字节）。真正有内容的是 #/w3/notice/main_view?class_item_pk=10001（社招），live 2 条在招：江苏华电赣榆 LNG（2026-09-07 17:34 ~ 09-21）、辽宁新能源分公司（08-28 ~ 09-10）。
校招是另一个组件 main_view2?class_item_pk=10000，当前仅「校园招聘测试公告（勿投）」一条，指过去等于把用户送到空页，故未采用；招聘季再评估要不要另开一行。
⚠️ hash 路由：在已打开的页面里改 # 是同文档导航、不重渲染（核验时当场读到空 body，reload 后才出数，与 CLAUDE.md 那条碑同一个机制）。用户从新标签页打开是完整加载 —— 已用冷标签页单独验过，正常渲染出那 2 条公告。$md$
 where company = '中国华电' and program_type = 'announcement';

-- 大唐：zpgg_index.html 是「招聘公告」页（校园/社会/系统内/人才帮扶/共享用工 5 tab + 46 家分子公司筛选）。
update apply_programs
   set entry_url = 'https://zhaopin.china-cdt.com/zpgg_index.html',
       verified_at = now(),
       updated_at = now(),
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告页（原 https://zhaopin.china-cdt.com）：门户根只有导航，公告列表在 /zpgg_index.html，live 2 条「进行中」（中新能化科技公司 2026 年高校毕业生招聘公告、江西分公司 2026 届校园招聘公告）。
📌 更正迁移 239 的 notes：那条写「连公告本身都没有独立 URL（javascript:showView）」——公告**全文**确实没有独立 URL，但**公告列表页有**。当时只查到前半句就停在了门户根。$md$
 where company = '中国大唐' and program_type = 'announcement';

-- 国网：recrAument.html = 招聘公告（各省公司，可按年度 / 批次筛）；home.html 只是平台首页。
update apply_programs
   set entry_url = 'https://zhaopin.sgcc.com.cn/sgcchr/static/recrAument.html',
       verified_at = now(),
       updated_at = now(),
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告页（原 .../static/home.html）：站点上了 Akamai，裸 curl 返 412，必须真渲染。
从首页链接里扫出全部静态页，公告有两个入口——recrAument.html =各省公司「招聘公告」（本条采用，可按年度 / 批次筛，live 是「国网北京 / 天津 / 河北 / 冀北… 2026 年高校毕业生招聘公告（第三批）」2026-04-27），comyAument.html =集团级「公司公告」（含 2026 年招聘高校毕业生总公告，2025-10-18）。
home.html 虽然也摘要显示公告，但它是平台首页，不是公告页。
⚠️ live 最新一批是 2026-04-27（第三批），2027 届尚未发；若到 2026-11 仍无新公告，重新评估这行。$md$
 where company = '国家电网' and program_type = 'announcement';

-- ── ① 档：当前挂着具体公告，直接指公告全文 ──────────────────────────────────

-- 邮储：2027 年度校园招聘公告，2026-09-07 发布，报名截止 2026-10-07 24 点。
update apply_programs
   set entry_url = 'https://www.psbc.com/cn/gyyc/rczp/xyzp/202609/t20260907_460394.html',
       program_name = '中国邮政储蓄银行2027年度校园招聘公告',
       window_text = '报名截止时间为北京时间2026年10月7日24点',
       verified_at = now(),
       updated_at = now(),
       description = $md$邮储银行官网只发招聘公告，看不到具体岗位页；这条就是当期的 2027 届校园招聘公告全文（招聘范围、岗位方向、报名与笔试安排都在里面），投递要按公告里的网申链接跳到独立系统注册填简历。截止后回 https://www.psbc.com/cn/gyyc/rczp/xyzp/ 看最新一条；社会招聘在同栏目的「社会招聘」子栏。$md$,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告全文（原 /cn/gyyc/rczp/）：原 URL 会 302 到 /xyzp/（校园招聘公告列表），列表首条即本公告（2026-09-07 发布）。公告原文：每人可在总行（含信用卡中心）与一级分行岗位中申报任意 2 个，另可同时申报控股子公司；报名截止北京时间 2026 年 10 月 7 日 24 点。
⏳ 复查：2026-10-07 截止后本页变成往期公告 —— 届时改指 /cn/gyyc/rczp/xyzp/，或指向下一条当期公告。$md$
 where company = '邮储银行' and program_type = 'announcement';

-- 中行：2027 年全球校园招聘公告，2026-09-03 发布，报名截止 2026-10-09 24 点。
update apply_programs
   set entry_url = 'https://www.bankofchina.com/aboutboc/bi4/202609/t20260903_25689311.html',
       program_name = '中国银行2027年全球校园招聘公告',
       window_text = '报名截止时间为北京时间2026年10月9日24点',
       verified_at = now(),
       updated_at = now(),
       description = $md$中国银行按「公告」发布招聘，官网没有逐个岗位的详情页。这条是当期的 2027 年全球校园招聘公告全文：可报总行 1-2 个岗位、其它一级机构 1 个岗位，均为平行志愿，报名走公告里给出的网址。截止后回 https://www.bankofchina.com/aboutboc/bi4/ 看最新一条（社招、实习生、海外人才公告也都挂在那一栏）。$md$,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07 改指公告全文（原 /aboutboc/bi4/）：那一栏是「招聘公告」列表，首条即本公告（2026-09-03）。
⚠️ 与迁移 240 边界三的**明确分歧**：240 有意选栏目页，理由是「2026-10-09 截止后这行不会失效」。本次按创始人指令（「不是具体的公告页面，这里不准」）改指公告本身 —— 当前明确指令优先于既有实现。耐久性代价用三件事兜：截止日进 window_text（页面单独渲染成琥珀提示行）、常青栏目页写进 description、复查时点写在这里。
⏳ 复查：2026-10-09 截止后改指 /aboutboc/bi4/，或指向下一条当期公告。$md$
 where company = '中国银行' and program_type = 'announcement';

-- ── 门户根白名单：华能是唯一合法的一条 ────────────────────────────────────
update apply_programs
   set updated_at = now(),
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-07（迁移 242）：本行是「公告制入口不许停在门户根」这条规则的**唯一登记例外** —— 根视图默认就是「招聘公告」列表（自报 167 条），更深路由 /CampusRecruit、/SocietyRecruit、/InternRecruit 实测都是「暂无数据」的岗位视图，指过去反而更差。
例外登记在 lib/apply-programs.ts 的 PORTAL_ROOT_IS_ANNOUNCEMENT_LIST（含单测）；取数层对未登记的门户根入口会打 warn。改 entry_url 时记得同步那份白名单。$md$
 where company = '中国华能' and program_type = 'announcement';

-- ── 收尾断言（承迁移 240）：enabled 行必须有 notes，且公告制不得停在门户根 ──
-- 第二条断言只认「路径为空且无 query 无 hash」这种最粗的形态，与
-- lib/apply-programs.needsDeeperAnnouncementLink 同口径；白名单里的华能显式豁免。
do $$
declare
  missing text;
  shallow text;
begin
  select string_agg(company || ' <' || entry_url || '>', ', ')
    into missing
    from apply_programs
   where enabled and notes is null;
  if missing is not null then
    raise exception '迁移 242 断言失败：还有 enabled 的 apply_programs 行没有 notes → %', missing;
  end if;

  select string_agg(company || ' <' || entry_url || '>', ', ')
    into shallow
    from apply_programs
   where enabled
     and program_type = 'announcement'
     and entry_url !~ '^https?://[^/?#]+/[^?#]'
     and entry_url not in ('https://zhaopin.chng.com.cn/');
  if shallow is not null then
    raise exception '迁移 242 断言失败：公告制入口停在门户首页，点开看不到公告 → %', shallow;
  end if;
end $$;
