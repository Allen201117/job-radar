-- 102 — 外企100强「硬骨头」自建巨头：Google（无头浏览器 DOM 抓取适配器）
-- Google careers 结果页无公开 JSON 接口、岗位卡服务端渲染进 DOM；用 playwright 加载 China 过滤页读岗位卡。
-- jd_url = www.google.com/about/careers/applications/jobs/results/{id-slug}。crawl_method=playwright。
-- 文件名 _seed_foreign_hardbones 后缀，避免与并行域内扩源 _seed_probed_sources 撞名丢内容。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Google 谷歌', 'https://www.google.com/about/careers/applications/jobs/results/?location=China', 'official', 'google', 'playwright', 'foreign', '互联网·云', 'Google 谷歌（互联网·云，无头浏览器 DOM 抓取 probe live 探活 在华 51 岗）'
where not exists (select 1 from sources where source_url = 'https://www.google.com/about/careers/applications/jobs/results/?location=China');
