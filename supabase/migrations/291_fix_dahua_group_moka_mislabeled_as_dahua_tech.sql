-- 291 — 纠正张冠李戴：Moka 租户 `dahua` 是「大华（集团）有限公司」（上海，房地产），不是浙江大华技术（安防）（2026-09-23 查实）
--
-- 现象：sources 里两条 Moka 源记成 company='浙江大华技术'（social 55997 / campus 118041），香港库这个名下 41 个 active 岗
--   全是「土建造价专业经理 / 景观设计主管 / 室内施工图设计师 / 物业…」—— 按「大华」查安防公司，看到的是地产公司的岗。
--   同名下的洞察画像还挂着 4 条由这 41 个地产岗算出来的「浙江大华技术」招聘指标（下一轮 bu_signals 无岗即 retire）。
-- 对方页面自己怎么说（live，三个门户逐个读）：
--   social-recruitment/dahua/55997   <title>大华集团 - 社会招聘</title>
--   campus-recruitment/dahua/118041  <title>大华（集团）有限公司 - 校园招聘</title>，siteName=2026届秋招门户
--   campus_apply/dahua → 302 → /188032  <title>大华（集团）有限公司 - 校园招聘</title>，siteName=2027届秋招门户
--   三页 intro 同一段：「大华（集团）有限公司成立于1988年，总部位于上海……形成了以房地产开发为主，集房地产投资、开发、建设、
--   物业管理等业务为一体……」—— 与浙江大华技术无关。真正的浙江大华技术是 beisen 源 dahua.zhiye.com
--   （<title>浙江大华技术股份有限公司</title>，库里记作「大华股份 Dahua」，474 个 active 岗，本迁移不动它）。
-- 根因：auto-discover 目标清单「浙江大华技术」的 cn='大华'，moka_probe 的标题核验只要求标题含「大华」→
--   「大华集团 - 社会招聘」照样放行（同 248 精雕/京东、274 特变电工/领益智造：探活出岗 ≠ 归属正确）。
--   清单 cn 同批改成「大华技术」，防止改名后它被判「库里缺这家」又把这个租户以原名插回来。
-- 处置：
--   ① 两条源改名「大华集团」（租户自报名），行业改地产。岗位真实、jd_url 稳定，只是挂错了名，不停用。
--   ② campus 源换到租户当前门户：118041 是上一期（2026届）门户，职位列表恒空；租户级别名 campus_apply/dahua 指向
--      当期（2027届，188032）。MokaAdapter 真抓：新 URL 10 岗（reported_total=10、fetch_complete、质量门 10/10），
--      旧 URL 0 岗；jd_url 渲染落到 /188032#/job/… 岗位详情。同迁移 286 写法；别名不保证有岗，这里是 live 看到岗才改。
--   ③ 香港库存量纠名走 rename-job-company.yml（jd_url 前缀 https://app.mokahr.com/social-recruitment/dahua/，
--      浙江大华技术 → 大华集团）；campus 源名下库里没有岗。
-- Idempotent：where 带旧值，重复执行无副作用。

update sources
   set company = '大华集团',
       industry = '地产',
       industry_group = '地产/建筑',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-23 公司名由「浙江大华技术」纠正为「大华集团」：Moka 租户 dahua 页面自报「大华（集团）有限公司」，总部上海、以房地产开发为主；浙江大华技术（安防）是 beisen 源 dahua.zhiye.com（大华股份 Dahua）。$md$
 where id in ('b77779ca-ecc3-4eac-8248-599d3f4ca816', '3e877801-62ab-4a1a-ac4b-721de3fecbdc')
   and company = '浙江大华技术';

update sources
   set source_url = 'https://app.mokahr.com/campus_apply/dahua'
 where source_url = 'https://app.mokahr.com/campus-recruitment/dahua/118041';
