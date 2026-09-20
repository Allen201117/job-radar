-- 停用 2 条「结构性空壳」来源（2026-09-20 创始人拍板，逐条 live 核实过）。
--
-- 背景：结构性审计 exp.fake_green_sources_chronic 今天命中 32 条「连续 7 天 status=success
--       且 jobs_found=0」的来源。32 条全部逐个核实后，判定 A（对方该板块确实没有在招岗位）21 条。
--       ⚠️ 这 21 条里**只停这 2 条**：其余 19 条是「这一批招完了、下一批还没开」的休眠通道
--       （钉钉 8/5 还出过 42 个岗、菜鸟 8/10 出过岗、天合光能 8/29、科沃斯 8/23），
--       停掉等于下一批开闸时我们看不见。停用判据是**结构性**（这个入口永远不会再出岗），
--       不是**季节性**（这一期没岗）。
--
-- 逐条证据：
--   · 华虹 campus-recruitment/74008：页面是**从没配置过的 Moka 默认模板**（满屏「模块标题/
--     链接标题/© 公司名称」占位字）+ 0 岗。该公司真实的 2027 届校招在我们**已收录的另一条
--     健康源** 74036 上，供给无缺口。
--   · 奥普特 hotjob /pb/social.html：页面 0 岗，且该租户导航栏**根本没有「社会招聘」这一栏**
--     —— 这家公司就没在这个平台开社招，不是「暂时没岗」。
--
-- 影响面（2026-09-20 按 jobs.source_id 精确点名核过，不是按 jd_url 前缀猜）：
--   source_id f5770e5e-…（华虹 74008）      → jobs 表 0 行（含任何 status）
--   source_id c9ef7cd7-…（奥普特 社招）      → jobs 表 0 行（含任何 status）
--   **两条合计影响在招岗位 0 个。**
--   ⚠️ 别按租户 URL 前缀去数：`opt.hotjob.cn/SU6a85…%` 下确实有 20 个 active，但它们
--   `postType=campus`、归属**另一条源** 0f65e7f3-…（/pb/school.html），那条正常供给、不动。
--
-- 只关开关、保留行，随时把 enabled 改回 true 即可回滚（本项目一贯做法：disable 不 delete）。
update sources set enabled = false
 where source_url in (
   'https://app.mokahr.com/campus-recruitment/huahong/74008',
   'https://opt.hotjob.cn/SU6a8562191ad6db7cf8087df0/pb/social.html'
 );
