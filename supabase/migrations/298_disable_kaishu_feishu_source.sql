-- 停用凯叔讲故事的飞书招聘源（2026-09-23 创始人拍板）。
--
-- 现象：这条源连续 7 天「status=success + jobs_found=0」，是停用迁移 293 之后假绿体检剩下的 2 条之一。
-- 证据（2026-09-23 live）：kaishu.jobs.feishu.cn 整个租户渲染为「开启新的工作（0）/ 暂无职位」；
--       租户首页自报的门户 path 就是 index（不是配错了门户前缀），最后一次出岗是 2026-08-13（1 个）。
--       未找到公司另有官方招聘站（只查到第三方招聘平台条目，第三方不作数）。
-- 影响面（香港 jobs 库）：本源名下 0 行；company 含「凯叔」的岗位 0 行。
-- 必投清单：凯叔讲故事在清单里，本源是它唯一的来源。停用后缺口普查会把它从「有源没岗」改记为
--       「没有可用来源」，缺口漏斗会按正常轨道重新找入口；若再次找到本地址，漏斗会先真抓，
--       抓到在招岗才重新启用、抓不到就恢复停用（crawler/gap_funnel.py 的 _prepare_source / _rollback）。
--
-- 只关开关、保留行，随时把 enabled 改回 true 即可回滚。
update sources set enabled = false
 where source_url = 'https://kaishu.jobs.feishu.cn/index/position';
