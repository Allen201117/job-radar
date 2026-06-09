-- 088 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '招商证券 CMS 校招', 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '证券', '招商证券 CMS 校招（证券，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润电力 CR Power 校招', 'https://wecruit.hotjob.cn/SU6149ff530dcad47003d01511/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '能源电力', '华润电力 CR Power 校招（能源电力，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6149ff530dcad47003d01511/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药 YNBY 校招', 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '云南白药 YNBY 校招（医药健康，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迪卡侬中国 Decathlon 校招', 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '消费·运动零售', '迪卡侬中国 Decathlon 校招（消费·运动零售，probe live 探活 在华 34 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华夏银行 HXB 校招', 'https://wecruit.hotjob.cn/SU645b0d18bef57c0907e9fbc8/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '银行', '华夏银行 HXB 校招（银行，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU645b0d18bef57c0907e9fbc8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '先声药业 Simcere 校招', 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '先声药业 Simcere 校招（医药健康，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '领益智造 Lingyi 校招', 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '电子制造', '领益智造 Lingyi 校招（电子制造，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国投证券 SDIC 校招', 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '证券', '国投证券 SDIC 校招（证券，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线 Horizon Robotics 校招', 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/school.html', 'official', 'hotjob', 'playwright', 'private', 'AI芯片', '地平线 Horizon Robotics 校招（AI芯片，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润三九 999 校招', 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '华润三九 999 校招（医药健康，probe live 探活 在华 33 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '开源证券 Kysec 校招', 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '证券', '开源证券 Kysec 校招（证券，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/school.html');
