-- 052 — 国内私企扩源（飞书招聘泛化适配器 'feishu'，host 从 source_url 解析，live 验证）
-- crawl_method=playwright（拦截 /api/v1/search/job/posts），segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '理想汽车 Li Auto', 'https://li.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车',
       '理想汽车（汽车，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://li.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '得物 POIZON', 'https://poizon.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '电商',
       '得物 POIZON（电商，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://poizon.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深言科技 Deeplang', 'https://deeplang.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI',
       '深言科技（AI，飞书招聘泛化适配器，live 6 岗）'
where not exists (select 1 from sources where source_url = 'https://deeplang.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '道旅科技 Dida', 'https://didatravel.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '旅游',
       '道旅科技（旅游，飞书招聘泛化适配器，live 26 岗）'
where not exists (select 1 from sources where source_url = 'https://didatravel.jobs.feishu.cn/index/position');
