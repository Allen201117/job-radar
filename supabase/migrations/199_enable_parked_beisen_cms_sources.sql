-- 199 — 打开被缺口漏斗「挂起」了的北森老版 CMS 源（零新代码，纯白捡 803 个岗）
--
-- 🚩 背景（这是一个系统性缺陷的第一次修复，教训见文末）：
-- 缺口漏斗对「探活通过但过不了验收门」的源，做法是插一行 enabled=false + notes='gap_funnel:pending …'
-- 挂起。但**没有任何机制在 adapter 能力升级后回头重试这些源** → 它们无限期躺着。
-- 中芯国际的社招/校招两条源 2026-07-27 就被漏斗从官网首页扒到并入库了（探活 verified），
-- 备注写着「待 route harvest 后走验收门」，然后卡了整整一个月 —— 卡点是老 BeisenAdapter
-- 抽不出老版 CMS 门户（theme2）的详情路由，而不是这些源有问题。
-- 上一个 commit 补上该分支后，这批挂起的源当场就能抓了。
--
-- 2026-08-27 我用补完的 adapter 把 8 条挂起源逐条 live 复跑，结果：
--   中芯国际 /social   293 岗   ✅ 全过质量门、正文覆盖 100%
--   中芯国际 /campus   248 岗   ✅（含大量「2027届校招」）
--   黑芝麻智能 /social 127 岗   ✅
--   启德教育 /social    15 岗   ✅
--   科伦药业 /social     6 岗   ✅
--   招商蛇口 /campus     4 岗   ✅
--   建发房产 /social 与 /campus  ❌ 两条**登记的路径本身就是空页**（该租户板块路径叫 /subzw/）
-- 合计打开 693 岗 + 建发改对路径后 110 岗 = 803 岗。
--
-- 建发房产另有一处 adapter 修复（同 commit）：它的列表行把详情链接写在 **data-url** 上
-- （`<li><a href="javascript:void(0)" data-url="/zwxq?jobId=561284174">`），href 是 javascript:void(0)。
-- 只认 href 会一条都抓不到 —— 这也是它挂起一个月的第二个原因。已改成两个属性都认并加回归测试。
--
-- ⚠️ 为什么用 update 而不是 insert：这些行**已经存在**（漏斗插的），
-- 而 seed 常用的 `on conflict (source_url) do nothing` **不会把已存在的 disabled 行改成 enabled**
-- ——迁移 198 就踩了这个坑（以为登记好了，查库才发现社招/校招仍是 false）。

-- ① 打开 6 条 live 验证通过的挂起源，并把备注改成可追溯的结论
update sources
   set enabled = true,
       notes = 'gap_funnel:accepted 老版 CMS 分支补齐后 2026-08-27 live 验收通过（原挂起于 route harvest 门）'
 where source_url in (
   'https://smics.zhiye.com/social',
   'https://smics.zhiye.com/campus',
   'https://bsthr.zhiye.com/social',
   'https://eic.zhiye.com/social',
   'https://kelun.zhiye.com/social',
   'https://cmsk1979.zhiye.com/campus'
 );

-- ② 中芯国际元数据对齐（漏斗当年写的是 制造/工业 且 segment 为空，与迁移 198 新插的 /overseas 行不一致）
update sources
   set industry = '半导体', segment = 'private'
 where source_url like 'https://smics.zhiye.com/%';

-- ③ 建发房产：登记的 /social 路径是空页，真实板块路径是 /subzw/（live 110 岗）→ 改对并打开。
--    该行从未抓成功过（无 jobs 引用），改 source_url 安全。
update sources
   set source_url = 'https://chinacdc.zhiye.com/subzw/',
       enabled = true,
       industry = '地产',
       segment = 'private',
       notes = 'gap_funnel:accepted 板块路径是 /subzw/ 不是 /social；详情链接在 data-url 上（2026-08-27 live 110 岗）'
 where source_url = 'https://chinacdc.zhiye.com/social';

-- ④ 建发房产的 /campus 保持停用：该租户是否有独立校招板块未经 live 确认，不猜。
update sources
   set notes = 'gap_funnel:parked 该租户校招板块路径未经 live 确认（社招走 /subzw/）；确认前不开，避免抓空源'
 where source_url = 'https://chinacdc.zhiye.com/campus';
