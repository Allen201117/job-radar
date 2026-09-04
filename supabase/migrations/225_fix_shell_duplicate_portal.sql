-- 225 — 修 223 引入的壳牌影子源（同一个 Workday 站点挂了两条源）
--
-- 我在 223 里把壳牌当成「必投 A 类缺口（连一行源都没有）」新插了一条源。**这个判断是错的**：
-- 壳牌 2026-07-16 就有源了，只是 `sources.company` 记的是英文 `Shell`，
-- 而我的缺口普查按中文 token `壳牌` 去匹配 sources.company —— 匹配不上 ⇒ 误报成零源。
--
-- 后果是规则 H（同一门户挂多个 enabled 源）的典型形态，且**两条源都 status=success、
-- 没有任何失败信号**：
--     已有：…/wday/cxs/shell/**ShellCareers**/jobs   （company='Shell'，18 岗）
--     我加：…/wday/cxs/shell/**shellcareers**/jobs   （company='壳牌'，10 岗）
-- 同一个 Workday 租户 + 同一个站点，**只差大小写**。而大小写会一路带进 jd_url
-- （…/en-US/ShellCareers/job/… vs …/en-US/shellcareers/job/…），canonical_jd_url
-- 区分大小写 ⇒ 唯一索引拦不住 ⇒ 同一个岗位在库里存两行。
-- live 实测同一岗 `PCMO-ICAM-CD_R206653` 确实两行并存。
--
-- 处置（对齐规则 H 的口径「一个门户只留一条源」）：
--   ① 停用我新加的那条（后来的、且大小写与官方站点名不一致的那条）；
--   ② 把保留下来那条的 company 从 'Shell' 改成 '壳牌' —— 这才是壳牌当初被算成缺口的**真因**：
--      必投清单的 pattern 是 `%壳牌%`，公司名记英文就永远匹配不上，
--      「有岗但指标显示为 0」比「真没岗」更危险，因为它会驱动人去重复补源（正是本次）。
--
-- ⚠️ 留给后来人的教训：**缺口普查按公司名匹配 sources 时，必须同时考虑英文名/别名**，
--    否则会把「已有源但名字对不上」误报成「零源」，然后重复插源、制造影子。
--    同类隐患：sources 里仍有 Visa 的 `visa/Visa` 与 `visa/visa` 两条（非本次引入，已知会）。
--
-- Idempotent: 两条 update 都带 where 条件，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') ||
               ' ｜ 2026-09-04 停用：与 …/shell/ShellCareers/jobs 是同一个 Workday 站点（仅大小写不同），'
               '属规则 H 影子源；壳牌的岗位由保留的那条源提供。'
 where source_url = 'https://shell.wd3.myworkdayjobs.com/wday/cxs/shell/shellcareers/jobs'
   and enabled;

update sources
   set company = '壳牌',
       notes = coalesce(notes, '') ||
               ' ｜ 2026-09-04 公司名由 Shell 改为壳牌：必投清单 pattern 是 %壳牌%，'
               '记英文名会让「有岗」被指标算成「零源缺口」，从而诱发重复补源。'
 where source_url = 'https://shell.wd3.myworkdayjobs.com/wday/cxs/shell/ShellCareers/jobs'
   and company = 'Shell';
