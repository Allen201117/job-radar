-- 101 — 外企100强「硬骨头」自建巨头：Microsoft（Phenom pcsx httpx 适配器）
-- MS 前端 jobs.careers.microsoft.com 被 Akamai 挡 httpx，但真实接口 apply.careers.microsoft.com/api/pcsx/search
-- 无 Akamai，httpx 直连可抓（浏览器调试发现）。按大中华区城市并集去重，jd_url=jobs.careers.microsoft.com/.../job/{displayJobId}。
-- 文件名 _seed_foreign_hardbones 后缀，避免与并行域内扩源 _seed_probed_sources 撞名丢内容。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Microsoft 微软', 'https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com', 'official', 'microsoft', 'http', 'foreign', '软件·云', 'Microsoft 微软（软件·云，pcsx httpx 适配器 probe live 探活 在华 24 岗）'
where not exists (select 1 from sources where source_url = 'https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com');
