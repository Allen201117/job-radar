-- 275 — 停用特变电工的 wt 老门户源（tbea.hotjob.cn）：官网主入口是 wecruit，两条源是同一批岗（2026-09-18 查实，续 274）
--
-- 274 把 wecruit 租户 SU612f55… 的三条源改回特变电工之后，特变名下同时挂着两个门户：
--   wt 老版  https://tbea.hotjob.cn/wt/TBEA/web/index                     2,271 active
--   wecruit  https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/…      1,905 active（社招/校招/实习三条）
-- 标题+城市重叠 1,720 行，canonical 不同、唯一索引拦不住 → 用户看到约 1,700 张重复卡片。
-- 哪个是主门户：用创始人 Chrome 打开 https://www.tbea.com/join.html（人才发展），页面上「校园招聘」「社会招聘」
-- 两个按钮分别指向 wecruit …/pb/school.html 与 …/pb/social.html；官网没有任何入口指向 tbea.hotjob.cn。
-- 另：tbea.hotjob.cn 的 getSLD 返「企业信息不存在」，只说明它是 wecruit 之前的老系统，还在跑但已不是官方入口。
-- 处置（规则 H：一个门户只留一条源）：停用 wt 那条，保留行可回滚；wt 名下 2,271 个 active 岗走
--   remove-jobs-by-url-prefix.yml 标 removed（可逆：purge 不删，重新启用源即复活）。wecruit 三条源不动。
-- Idempotent：where 带 enabled，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-18 停用：特变电工官网人才发展页的校园/社会招聘按钮都指向 wecruit（SU612f55…），本条是 wt 老门户、与 wecruit 三条源是同一批岗（标题+城市重叠 1,720 / 2,271），规则 H 影子源；岗位由 wecruit 源提供。$md$
 where source_url = 'https://tbea.hotjob.cn/wt/TBEA/web/index'
   and company = '新疆特变电工集团'
   and enabled;
