-- Nubank 已从 Greenhouse 迁到 Ashby（2026-09-20 live 核实）。与迁移 283（Marqeta / Temporal）同一类问题。
--
-- 现象：这条源连续 7 天「status=success + jobs_found=0」，没有任何报错信号
--       （结构性审计 exp.fake_green_sources_chronic 命中）。
-- 证据：boards-api.greenhouse.io/v1/boards/nubank/jobs 匿名 200，body 是
--       {"jobs":[],"meta":{"total":0}} —— 接口没坏，是这个 board 本身已被弃用（空壳）。
--       对方官网 nu.com/pt/carreiras 自己链向的招聘入口现在是 jobs.ashbyhq.com/nubank，
--       即官网自证的真实 ATS + board slug（不是猜的 slug）。
--       api.ashbyhq.com/posting-api/job-board/nubank 匿名 200，返回 122 个在招岗。
-- 影响面（已用本仓库的 ashby adapter + 本行 regions 实跑 parse 核过，不是估算）：
--       122 条里过 regions={CN,US,SG,Remote} 白名单后存活 39 条
--       （Palo Alto 23 / Miami 13 / Virginia 3），中国岗 0 条。
--       所以这条修复只为海外范围用户补 39 个美国岗，对国内供给没有增量——如实记在这里，
--       免得以后有人把它读成「补回了一家必投公司」。
update sources
   set source_url = 'https://api.ashbyhq.com/posting-api/job-board/nubank?includeCompensation=true',
       adapter_name = 'ashby'
 where source_url = 'https://boards-api.greenhouse.io/v1/boards/nubank/jobs?content=true';
