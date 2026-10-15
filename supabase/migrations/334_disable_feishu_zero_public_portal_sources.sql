-- 334 — 停用 8 条公开门户上没有在招岗的飞书主门户源（2026-10-14 查实，创始人 2026-10-15 同意停用、保留记录）
--
-- 现象：这 8 条源 2026-09-24 起每轮都是「成功 0 岗」（各 97 轮），占每日体检「连续 7 天报成功零产出」11 个里的 8 个，
--   把真要人处理的那 3 个（建信基金北森 ×2、中广核 wt）淹在里面。
-- 核实（2026-10-14，全部只读：列表 / 详情接口 + 首页导航配置 + 浏览器实开 + 香港库）：
--   · 8 家首页都自报了门户（7 家 index、海底捞 072846），自报门户的列表都是 0 岗；公开页自己写「开启新的工作（0）」。
--   · 不带 website-path 头的列表里有岗（七匹狼 6 / 北电数智 24 / 地素 96 / 恺英 1 / 普源 7 / 海底捞 144 / 自如 1 / 知存 0），
--     逐岗带自报门户的头读 channel_online_status 全是 0 =「该职位已下线」，2026-09-23 起本来就不抓（见 CLAUDE.md
--     「飞书招聘的校招岗藏在 website-path 请求头后面」主门户那条）。
--   · 首页导航配置里链到的同租户门户：只有北电数智一个（「校招职位」→ /098881），列表接口回 site not exist、
--     浏览器打开是 Not Found。北电数智官网首页没有招聘入口。
--   · 知存科技连不带头的列表都是 0；域名在 CI 上能解析（09-24 起 97 轮里 96 轮成功），租户还在，只是没挂岗。
--   · 香港库里这 8 个域名下的岗位行：0（任何状态都没有），停用不会留下没人刷新的岗。
-- 不是抓取故障：同一批核实里查出的真故障（首页没读到自报门户时只问 index、记成成功 0 岗）已在 adapters/feishu.py 修掉，
--   修后这 8 条照样是成功 0 岗、标抓全。
-- 处置：停用（保留行，可回滚）。对方以后在公开门户上重新挂岗，要人重新启用：update sources set enabled = true where source_url = …
-- Idempotent：where 带 enabled，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-15 停用：公开门户上没有在招岗。首页自报的门户列表 0 岗、公开页写「开启新的工作（0）」；不带门户头的列表里的岗在公开门户上全是「已下线」；首页导航没有链到别的在用门户。09-24 起每轮成功 0 岗。对方在公开门户上重新挂岗后再启用（迁移 334）。$md$
 where adapter_name = 'feishu'
   and enabled
   and source_url in (
     'https://septwolves.jobs.feishu.cn/index/position',      -- 七匹狼实业股份有限公司
     'https://caz6yhvgk5z.jobs.feishu.cn/index/position',     -- 北电数智
     'https://dazzle-fashion.jobs.feishu.cn/index/position',  -- 地素时尚股份有限公司
     'https://kingnet.jobs.feishu.cn/index/position',         -- 恺英网络
     'https://rigolportal.jobs.feishu.cn/index/position',     -- 普源精电
     'https://haidilao.jobs.feishu.cn/index/position',        -- 海底捞
     'https://iucylxooqp.jobs.feishu.cn/index/position',      -- 知存科技
     'https://ziroom.jobs.feishu.cn/index/position'           -- 自如
   );
