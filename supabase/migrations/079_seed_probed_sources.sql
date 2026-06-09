-- 079 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MiniMax', 'https://vrfi1sk8a0.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI大模型', 'MiniMax（AI大模型，probe live 探活 在华 39 岗）'
where not exists (select 1 from sources where source_url = 'https://vrfi1sk8a0.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '智谱 Zhipu AI', 'https://zhipu-ai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI大模型', '智谱 Zhipu AI（AI大模型，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://zhipu-ai.jobs.feishu.cn/index/position');
