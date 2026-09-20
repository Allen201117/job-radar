-- Moka 校招门户「换期换 id」导致的存量死链（2026-09-20 live 逐条核实）。
--
-- 现象：这 4 条源连续 7 天 status=success + jobs_found=0，零报错
--       （结构性审计 exp.fake_green_sources_chronic 命中）。
-- 根因：Moka 同一租户**每一期校招会新建一个门户 id**，公司换期后，我们 sources 里存的
--       那个具体数字 id 就变成上一期的死门户（页面还在、职位列表恒空），而 adapter 完全正常。
--       租户级无 id 别名 `campus_apply/{tenant}` 指向该租户**当前生效**的那一期。
-- 核实方式：对每条源用无头浏览器渲染新旧两个 URL 对拍（同一套 MokaAdapter 的 `#/jobs` 路由与
--       `a[href*='#/job/']` 选择器），读页面自己写的「N 结果」：
--         知乎        apply/zhihu/3819        0 岗  →  campus_apply/zhihu          46 结果（27 届校招在招）
--         菲尼克斯    …/phoenixcontact/150964 0 岗  →  campus_apply/phoenixcontact 19 结果（15 城）
--         芯粤能      …/ascenpower/142952     0 岗  →  campus_apply/ascenpower      9 结果（广州 FAB 等）
--         明源云      …/mingyuan/116135       0 岗  →  campus_apply/mingyuan        6 结果
--       合计找回 80 个在招校招岗（正值秋招季）。
--
-- ⚠️ 别把它当成通用规律去批量改：`campus_apply/{tenant}` **不保证**指向有岗的门户。
--    反例（同批核实）：华虹的 campus_apply/huahong 渲染出来与它那个**空**门户 74008 逐字相同，
--    而真正有岗的是另一个数字门户 74036。所以只改「已经 live 看到岗位」的这 4 条，
--    其余一条不动。以后再遇到同类，也必须逐条渲染确认有岗再改。
update sources set source_url = 'https://app.mokahr.com/campus_apply/zhihu'
 where source_url = 'https://app.mokahr.com/apply/zhihu/3819';

update sources set source_url = 'https://app.mokahr.com/campus_apply/phoenixcontact'
 where source_url = 'https://app.mokahr.com/campus-recruitment/phoenixcontact/150964';

update sources set source_url = 'https://app.mokahr.com/campus_apply/ascenpower'
 where source_url = 'https://app.mokahr.com/campus-recruitment/ascenpower/142952';

update sources set source_url = 'https://app.mokahr.com/campus_apply/mingyuan'
 where source_url = 'https://app.mokahr.com/campus-recruitment/mingyuan/116135';
