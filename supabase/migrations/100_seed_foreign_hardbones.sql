-- 100 — 外企100强「硬骨头」自建巨头：Phenom 脉续 — PepsiCo
-- 文件名 _seed_foreign_hardbones 后缀，避免与并行域内扩源 _seed_probed_sources 撞名丢内容。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'PepsiCo 百事', 'https://www.pepsicojobs.com/api/jobs', 'official', 'phenom', 'http', 'foreign', '食品·饮料', 'PepsiCo 百事（食品·饮料，Phenom 适配器 probe live 探活 在华 66 岗）'
where not exists (select 1 from sources where source_url = 'https://www.pepsicojobs.com/api/jobs');
