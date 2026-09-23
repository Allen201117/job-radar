-- Postman 已从 Greenhouse 迁到 Workday（2026-09-23 live 核实，同迁移 283/285 一类问题）。
--
-- 现象：源连续 5 天 29 轮抓取全部 failed（结构性审计规则 F 开出 GitHub issue #36）。
-- 证据：boards-api.greenhouse.io/v1/boards/postman/jobs 匿名 404 —— 不是限流/反爬，board 本身
--       已被弃用。官网 postman.com/company/careers/open-positions/ 页面自己请求的
--       /_mk-www-next/api-cache/careers-jobs.json 里写着
--       {"meta":{"source":"workday_cxs","careersUrl":"https://postman.wd108.myworkdayjobs.com/careers"}}，
--       即官网自证的真实 ATS + 租户/站点（不是猜的 slug）。
--       直接 POST https://postman.wd108.myworkdayjobs.com/wday/cxs/postman/careers/jobs
--       （本仓库 workday adapter 的标准端点格式）匿名 200，total=36，与官网页面「36 open positions」
--       一致。
-- 影响面（本仓库 WorkdayAdapter.fetch+parse 用本行 regions={CN,US,SG,Remote} 实跑核过，不是估算）：
--       该租户没有任何中国/新加坡地点，也没有国家级 location facet（只有 8 个城市级叶子，
--       描述格式是「Austin, TX, US」，不含 adapter 认的 "united states"/"usa" 关键词，
--       facet 路径 trusted=0）→ 走 searchText 文本召回补充，6 条文本命中里过 regions 白名单后
--       存活 4 条（San Francisco/Austin×2/Boston，均美国岗，jd_url 逐条可开），London/Bangalore
--       两条判非目标 region 被过滤。如实记下：这条修复只为海外范围用户补 4 个美国岗，
--       对国内供给没有增量。
-- ⚠️ 已知残留：该租户地点用「City, State, US」缩写、无「United States」全称 facet 叶子，
--       adapter 的 facet 匹配（_REGION_FACET_KEYWORDS 认全称/usa/u.s.）在这类租户上失效，只能靠
--       searchText 兜底，兜底覆盖不全（36 个岗里美国岗理论上有 26 个，text search 只捞到 4 个落地）。
--       这是 workday adapter 现有的通用行为，不是本次改动引入的新问题，本迁移不改 adapter 逻辑。
update sources
   set source_url = 'https://postman.wd108.myworkdayjobs.com/wday/cxs/postman/careers/jobs',
       adapter_name = 'workday'
 where source_url = 'https://boards-api.greenhouse.io/v1/boards/postman/jobs?content=true';
