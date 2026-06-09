-- 098 — 外企100强「硬骨头」自建巨头：Amazon bespoke 适配器（crawler/adapters/amazon.py）
-- Amazon 完全自建招聘系统（非通用 ATS），公开 search.json 按 normalized_country_code=CHN 服务端筛 + 分页。
-- 文件名 _seed_foreign_hardbones 后缀，避免与并行域内扩源 _seed_probed_sources 撞名丢内容。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Amazon 亚马逊', 'https://www.amazon.jobs/en/search.json?normalized_country_code[]=CHN&result_limit=100', 'official', 'amazon', 'http', 'foreign', '互联网·云', 'Amazon 亚马逊（互联网·云，bespoke 适配器 probe live 探活 在华 341 岗）'
where not exists (select 1 from sources where source_url = 'https://www.amazon.jobs/en/search.json?normalized_country_code[]=CHN&result_limit=100');
