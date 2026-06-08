-- 064 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '药明康德 WuXi AppTec', 'https://wuxiapptec.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '医药·CRO', '药明康德 WuXi AppTec（医药·CRO，probe live 探活 在华 70 岗）'
where not exists (select 1 from sources where source_url = 'https://wuxiapptec.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通威股份 Tongwei', 'https://tongwei.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '光伏·农牧', '通威股份 Tongwei（光伏·农牧，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://tongwei.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卓胜微 Maxscend', 'https://maxscend.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '半导体·射频', '卓胜微 Maxscend（半导体·射频，probe live 探活 在华 74 岗）'
where not exists (select 1 from sources where source_url = 'https://maxscend.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '传音控股 Transsion', 'https://transsion.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '消费电子·手机', '传音控股 Transsion（消费电子·手机，probe live 探活 在华 60 岗）'
where not exists (select 1 from sources where source_url = 'https://transsion.zhiye.com/social/jobs');
