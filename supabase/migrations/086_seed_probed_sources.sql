-- 086 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华夏银行 HXB', 'https://wecruit.hotjob.cn/SU645b0d18bef57c0907e9fbc8/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '银行', '华夏银行 HXB（银行，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU645b0d18bef57c0907e9fbc8/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '先声药业 Simcere', 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '先声药业 Simcere（医药健康，probe live 探活 在华 44 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '领益智造 Lingyi', 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '电子制造', '领益智造 Lingyi（电子制造，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国投证券 SDIC', 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '证券', '国投证券 SDIC（证券，probe live 探活 在华 48 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线 Horizon Robotics', 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/social.html', 'official', 'hotjob', 'playwright', 'private', 'AI芯片', '地平线 Horizon Robotics（AI芯片，probe live 探活 在华 48 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/social.html');
