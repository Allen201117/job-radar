-- 307: 欧莱雅招聘官网从 Avature 迁到 Radancy/TalentBrew —— source 改用 radancy adapter + 新搜索页；
--      盒马招聘站整站 500 一个多月 —— 停用这条源。（创始人 2026-10-07 批准两项）
--
-- 欧莱雅
--   现象：2026-10-05 晚起每轮 failed「avature: 首页未解析到岗位卡」（此前每轮约 330 岗）。
--   根因（2026-10-07 live）：旧 SearchJobs / JobDetail 地址一律 301 到 https://careers.loreal.com/en（官网首页），
--     库里 499 个 active 岗的 jd_url 逐个核过 499/499 落到首页。新站是 TalentBrew SSR 搜索页。
--   新地址是站点自己渲染的中国国家级地区页（data-location="China"、data-location-path=1814991），
--     live 自报 326 岗、radancy adapter 翻完 22 页抓回 326、jd_url 无重复（e78a750c）。
--   存量旧链接由 remove-jobs-by-url-prefix 标 removed（可逆），不在本迁移里动。
--   可逆：改回 adapter_name='avature' + 旧 source_url。幂等：id + 旧 source_url 双重限定。
update public.sources
   set adapter_name = 'radancy',
       source_url = 'https://careers.loreal.com/en/search-jobs/China/3456/2/1814991/35/105/50/2'
 where id = 'e07c58b0-c06b-4a85-8e22-82923b674a32'
   and source_url = 'https://careers.loreal.com/zh_CN/jobs/SearchJobs?3_110_3=18009';

-- 盒马
--   现象：2026-09-03 起每轮 failed，一次都没成功（看门狗规则 F 持续告警）。
--   live 2026-10-04~10-07 每天复测：hire.freshippo.com 与 talent.freshippo.com 首页、列表页均 500；
--     盒马官网首页正常但找不到新招聘入口。库里没有任何盒马岗位，停用不影响用户可见内容。
--   可逆：改回 enabled=true。只动这一行（id + source_url 双重限定）。
update public.sources
   set enabled = false
 where id = 'f213b193-2b74-41a3-b58c-22725f62b5ac'
   and source_url = 'https://hire.freshippo.com/off-campus/position-list?lang=zh';
