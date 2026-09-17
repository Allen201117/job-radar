-- 268 — 停用「华润医药环保」名下的 3 条 hotjob 影子源（2026-09-18）
--
-- 现象：auto-discover 猜 slug `ce.hotjob.cn` 命中一个真实 wecruit 租户，探活「有岗」即判 verified，
-- 但该租户列表接口自报的公司是宜信（CreditEase）：岗位是「菲律宾业务部」「互联网保险部」「数智金融事业群」，
-- 与华润医药环保毫无关系。库里因此挂了 86 个在招岗到「华润医药环保」名下（用户按华润筛出来的是宜信的岗）。
-- 根因：`discover_domestic.hotjob_probe` 的 wecruit 分支没有公司名核验（已在同一天修复：探活结果必须
-- 通过 `_verify(自报公司, 目标公司)`；`emit_discovered._confirm_httpx` 同口径）。
-- 处置：只停用不删（保留行可回滚）；对应 86 个 jobs 行另行标 removed（可复活），不删。
-- 同一轮复核里其它「会被新核验拒掉」的 auto-discover 源（瓜子二手车→车好多、中国金茂→金茂系子公司、
-- 安信证券→国投证券、华夏幸福）逐条看过都是同一家公司的改名/母子公司，不动。
update sources
   set enabled = false,
       notes = coalesce(notes, '') || ' | 2026-09-18 停用：租户自报公司为宜信，与华润医药环保无关（影子源，见迁移 268）'
 where company = '华润医药环保'
   and adapter_name = 'hotjob'
   and source_url like 'https://ce.hotjob.cn/SU63f35dc6bef57c71d9fd08f8/%'
   and enabled;
