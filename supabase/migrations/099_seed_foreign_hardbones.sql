-- 099 — 外企100强「硬骨头」自建巨头：Phenom bespoke 适配器（crawler/adapters/phenom.py）
-- AMD 自建门户跑在 Phenom People 平台（非通用 ATS），公开 /api/jobs 按 location 服务端筛 + 分页。
-- jd_url = {host}/jobs/{slug}（Phenom 公开逐岗页；apply_url 指向 icims 登录页不可用）。
-- 文件名 _seed_foreign_hardbones 后缀，避免与并行域内扩源 _seed_probed_sources 撞名丢内容。
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'AMD 超威', 'https://careers.amd.com/api/jobs', 'official', 'phenom', 'http', 'foreign', '半导体', 'AMD 超威（半导体，Phenom bespoke 适配器 probe live 探活 在华 41 岗）'
where not exists (select 1 from sources where source_url = 'https://careers.amd.com/api/jobs');
