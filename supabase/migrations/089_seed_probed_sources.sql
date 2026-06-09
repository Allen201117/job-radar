-- 089 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '招商证券 CMS 实习', 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '证券', '招商证券 CMS 实习（证券，probe live 探活 在华 49 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU629dbc0c0dcad452299bc0f7/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药 YNBY 实习', 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '云南白药 YNBY 实习（医药健康，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迪卡侬中国 Decathlon 实习', 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '消费·运动零售', '迪卡侬中国 Decathlon 实习（消费·运动零售，probe live 探活 在华 35 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64631fe6bef57c0907f133c4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '先声药业 Simcere 实习', 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '先声药业 Simcere 实习（医药健康，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU61458d83bef57c54dcb4e43f/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '领益智造 Lingyi 实习', 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '电子制造', '领益智造 Lingyi 实习（电子制造，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国投证券 SDIC 实习', 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '证券', '国投证券 SDIC 实习（证券，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU625d4a0b2f9d24287db127c8/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地平线 Horizon Robotics 实习', 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', 'AI芯片', '地平线 Horizon Robotics 实习（AI芯片，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6409ef49bef57c635fd390a6/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润三九 999 实习', 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '华润三九 999 实习（医药健康，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '开源证券 Kysec 实习', 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '证券', '开源证券 Kysec 实习（证券，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/interns.html');
