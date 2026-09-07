-- 240 — 公告制入口改指「真正的公告页」，不再停在门户首页（2026-09-07 逐条真浏览器核验）
--
-- 现象（创始人反馈）：「公告制的入口那里你给的链接都是点击跳转到企业官网，但不是具体的
--   公告页面，这里不准。」实测 13 条 announcement 里 6 条落在门户根 / 平台首页上：
--   中煤 zhaopin.chinacoal.com、华电 rencaishichang.chd.com.cn、大唐 zhaopin.china-cdt.com、
--   国网 .../static/home.html、邮储 /cn/gyyc/rczp/、中行 /aboutboc/bi4/。
--
-- 根因：上一批（迁移 231/239）核验的问题是「这家有没有逐岗页」，答案是「没有」——这没错；
--   但**据此就把 entry_url 填成门户根**，等于只回答了「该不该进这一页」，没回答
--   「用户点下去该看到什么」。这两件事被合成了一件，于是 6 条停在了首页。
--   典型的是大唐：239 的 notes 写着「连公告本身都没有独立 URL（javascript:showView）」——
--   这条是对的，但**公告列表页 zpgg_index.html 是有 URL 的**，当时没往下找一层。
--
-- 防法：announcement 类的 entry_url 判据从「能打开」升级为
--   **「打开后第一屏就得看见招聘公告条目」**。分两档，按能拿到的最深一层取：
--     ① 对方当前挂着**具体公告** → 直接指公告全文（邮储 / 中行 / 中国邮政）；
--     ② 只有列表 → 指**公告列表页**（中煤 / 华电 / 大唐 / 国网 / 其余保持）。
--   门户根只在「根页面本身就是公告列表」时才允许（只有华能一家，见
--   lib/apply-programs.ts 的 PORTAL_ROOT_IS_ANNOUNCEMENT_LIST 白名单 + 单测）。
--
-- ⚠️ ①这一档会随报名窗口过期而变旧。所以每条都：把截止日期写进 window_text（页面会单独
--    渲染成一行琥珀提示）、把常青的列表页写进 description、并在 notes 里写明复查时点。
--    宁可让用户看见「截止 10 月 9 日」也不给一个看不出时效的列表页——
--    这一页本来就是「对方按公告批量招聘」，公告本身才是用户要读的东西。

-- ── ② 档：指到公告列表页 ────────────────────────────────────────────────────

-- 中煤：/notice 是「招聘公告」列表（全部/校园/社会 三个 tab + 搜索）。
-- live：10 条公告，最新两条 2026-09-07（江苏分公司第 2 次社招、西南分公司第九批）。
update apply_programs
   set entry_url = 'https://zhaopin.chinacoal.com/notice',
       verified_at = now(),
       notes = $md$2026-09-07 真浏览器核验：门户根 / 只渲染首页摘要（只露 7 条），/notice 才是完整公告列表（10 条，带 全部/校园/社会 筛选）。
⚠️ 站内「查看更多」跳出来的是 /notice?s=<加密串>，那个带签名的 URL 打开是「暂无数据」——**不要抄站内那条**，裸 /notice 才正常出数。$md$
 where company = '中国中煤' and program_type = 'announcement';

-- 华电：hash 路由，社招公告在 class_item_pk=10001。
-- live：2 条在招（江苏华电赣榆 LNG 2026-09-07 发布 / 辽宁新能源分公司 8-28~9-10）。
-- 校招那一档（main_view2?class_item_pk=10000）当前只有一条「校园招聘测试公告（勿投）」，
-- 指过去等于把用户送到一个空页，所以这条先指社招，并在 description 写清怎么切。
update apply_programs
   set entry_url = 'https://rencaishichang.chd.com.cn/w3/#/w3/notice/main_view?class_item_pk=10001',
       program_name = '社会招聘公告（校招 / 实习在同站切换）',
       verified_at = now(),
       description = $md$华电招聘投的是「公告」不是岗位：一条公告对应一家分子公司的一批招聘，卡片上会把岗位名列出来（如「安全专工 / 化学工艺专工 +2」），但点不进单个岗位。这条链接直接落在**社会招聘公告**列表；顶部那排「青年骏才 / 校园招聘 / 实习招聘…」可以切到其它档，校招在招聘季才会有正式公告。$md$,
       notes = $md$2026-09-07 真浏览器核验：门户根 rencaishichang.chd.com.cn 渲染出来只有一排 tab + 登录按钮，**一条公告都没有**（curl 拿到的 body 只有 391 字节）。真正有内容的是 #/w3/notice/main_view?class_item_pk=10001（社招，2 条在招）。
校招是另一个组件 main_view2?class_item_pk=10000，当前仅「校园招聘测试公告（勿投）」一条，故未采用。
⚠️ hash 路由：在已打开的页面里改 # 是同文档导航、不重渲染（核验时当场读到空 body，reload 后才出数）。用户从新标签页打开是完整加载，不受影响。$md$
 where company = '中国华电' and program_type = 'announcement';

-- 大唐：zpgg_index.html 是「招聘公告」页（校园/社会/系统内/人才帮扶/共享用工 5 tab + 46 家分子公司筛选）。
-- live：2 条进行中（中新能化 2026 高校毕业生招聘公告、江西分公司 2026 届校园招聘公告）。
update apply_programs
   set entry_url = 'https://zhaopin.china-cdt.com/zpgg_index.html',
       verified_at = now(),
       notes = $md$2026-09-07 真浏览器核验：门户根只有导航，公告列表在 /zpgg_index.html（2 条「进行中」）。
📌 更正迁移 239 的 notes：那条写「连公告本身都没有独立 URL（javascript:showView）」——**公告全文确实没有独立 URL，但公告列表页有**，当时只查到前半句就停在了门户根。$md$
 where company = '中国大唐' and program_type = 'announcement';

-- 国网：recrAument.html = 招聘公告（各省公司，可按年度 / 批次筛）；home.html 只是平台首页。
-- live：国网北京/天津/河北/冀北… 2026 年高校毕业生招聘公告（第三批），2026-04-27。
update apply_programs
   set entry_url = 'https://zhaopin.sgcc.com.cn/sgcchr/static/recrAument.html',
       verified_at = now(),
       notes = $md$2026-09-07 真浏览器核验（站点上了 Akamai，裸 curl 返 412，必须真渲染）：
从首页链接里扫出全部静态页，公告有两个入口——recrAument.html=各省公司「招聘公告」（本条采用，可按年度/批次筛），comyAument.html=集团级「公司公告」（含 2026 年招聘高校毕业生总公告，2025-10-18）。
home.html 虽然也摘要显示公告，但它是平台首页，不是公告页。$md$
 where company = '国家电网' and program_type = 'announcement';

-- ── ① 档：当前挂着具体公告，直接指公告全文 ──────────────────────────────────

-- 邮储：2027 年度校园招聘公告，2026-09-07 发布，报名截止 2026-10-07 24 点。
update apply_programs
   set entry_url = 'https://www.psbc.com/cn/gyyc/rczp/xyzp/202609/t20260907_460394.html',
       program_name = '中国邮政储蓄银行2027年度校园招聘公告',
       window_text = '报名截止时间为北京时间2026年10月7日24点',
       verified_at = now(),
       description = $md$邮储银行官网只发招聘公告，看不到具体岗位页；这条就是当期的 2027 届校园招聘公告全文（招聘对象、岗位方向、报名与笔试安排都在里面），投递要按公告里的网申链接跳到独立系统注册填简历。截止后回 https://www.psbc.com/cn/gyyc/rczp/xyzp/ 看最新一条；社会招聘在同栏目的「社会招聘」子栏。$md$,
       notes = $md$2026-09-07 真浏览器核验：/cn/gyyc/rczp/ 会 302 到 /xyzp/（校园招聘公告列表），列表首条即本公告。
⏳ 复查：2026-10-07 报名截止后本页变成往期公告，届时改指 /cn/gyyc/rczp/xyzp/ 或下一条当期公告。$md$
 where company = '邮储银行' and program_type = 'announcement';

-- 中行：2027 年全球校园招聘公告，2026-09-03 发布，报名截止 2026-10-09 24 点。
update apply_programs
   set entry_url = 'https://www.bankofchina.com/aboutboc/bi4/202609/t20260903_25689311.html',
       program_name = '中国银行2027年全球校园招聘公告',
       window_text = '报名截止时间为北京时间2026年10月9日24点',
       verified_at = now(),
       description = $md$中国银行按「公告」发布招聘，官网没有逐个岗位的详情页。这条是当期的 2027 年全球校园招聘公告全文：可报总行 1-2 个岗位、其它一级机构 1 个岗位，均为平行志愿，报名走公告里给出的网址。截止后回 https://www.bankofchina.com/aboutboc/bi4/ 看最新一条（社招、实习生、海外人才公告也都挂在那一栏）。$md$,
       notes = $md$2026-09-07 真浏览器核验：/aboutboc/bi4/ 是「招聘公告」列表（首条即本公告，2026-09-03）；本条改指公告全文本身。
⏳ 复查：2026-10-09 报名截止后改指 /aboutboc/bi4/ 或下一条当期公告。$md$
 where company = '中国银行' and program_type = 'announcement';

-- ── 保持不变但补时间窗 / 补核验凭据 ────────────────────────────────────────

-- 中国邮政：URL 本来就是具体公告（2027 年度联合校园招聘公告），只补一次核验时间。
update apply_programs
   set verified_at = now(),
       notes = $md$2026-09-07 真浏览器核验：页面即公告全文（2026-09-07 发布，来源中国邮政网），招聘范围 2027 届、简历接收截止 2026-10-31，网申链接 chinapost2027.zhaopin.com。
⏳ 复查：2026-10-31 截止后改指 https://www.chinapost.com.cn/cn/report/ 信息公告栏的下一条。$md$
 where company = '中国邮政' and program_type = 'announcement';

-- 华能：门户根本身就是「招聘公告」列表（167 条，带分页），没有更深的可寻址页
-- （/CampusRecruit 等路由实测「暂无数据」）。这是白名单里唯一允许停在根的一条。
update apply_programs
   set verified_at = now(),
       notes = $md$2026-09-07 真浏览器核验：zhaopin.chng.com.cn/ 默认视图就是「招聘公告」列表（共 167 条，含各单位年度高校毕业生招聘公告）。
读它自己的前端路由表（assets/index.*.js）确认没有更深的公告页：/CampusRecruit、/SocietyRecruit、/InternRecruit 等实测都是「暂无数据」的岗位视图。
⇒ 本条是 lib/apply-programs.ts PORTAL_ROOT_IS_ANNOUNCEMENT_LIST 白名单里唯一一条。$md$
 where company = '中国华能' and program_type = 'announcement';

-- 其余 5 条（东方电气 / 中国林业集团 / 中国烟草 / 中国稀土集团 / 国家开发银行）本来就指在
-- 公告列表页上，本次逐条重新渲染确认仍有公告条目，只刷新核验时间。
update apply_programs
   set verified_at = now()
 where program_type = 'announcement'
   and company in ('东方电气', '中国林业集团', '中国烟草', '中国稀土集团', '国家开发银行');
