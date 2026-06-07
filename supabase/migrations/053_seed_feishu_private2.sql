-- 053 — 国内私企扩源批2（飞书招聘泛化适配器 'feishu'，host 从 source_url 解析，live 验证）
-- crawl_method=playwright（拦截 /api/v1/search/job/posts），segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '智谱AI Zhipu', 'https://zhipu-ai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI大模型',
       '智谱AI（AI大模型，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://zhipu-ai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MiniMax 稀宇科技', 'https://vrfi1sk8a0.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI大模型',
       'MiniMax（AI大模型，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://vrfi1sk8a0.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '元气森林', 'https://k11pnjpvz1.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费·饮料',
       '元气森林（消费·饮料，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://k11pnjpvz1.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MetaApp', 'https://meta.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏·元宇宙',
       'MetaApp（游戏·元宇宙，飞书招聘泛化适配器，live 10 岗）'
where not exists (select 1 from sources where source_url = 'https://meta.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'VAST', 'https://a9ihi0un9c.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI·3D生成',
       'VAST（AI·3D生成，飞书招聘泛化适配器，live 10 岗）'
where not exists (select 1 from sources where source_url = 'https://a9ihi0un9c.jobs.feishu.cn/index/position');
