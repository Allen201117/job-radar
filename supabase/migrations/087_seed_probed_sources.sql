-- 087 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润三九 999', 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '医药健康', '华润三九 999（医药健康，probe live 探活 在华 37 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '开源证券 Kysec', 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '证券', '开源证券 Kysec（证券，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU654f2e0b3538bc6c4d600eab/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上海瑞金医院 Ruijin Hospital', 'https://wecruit.hotjob.cn/SU68a400ef1343c325ffa8379c/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '医疗', '上海瑞金医院 Ruijin Hospital（医疗，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU68a400ef1343c325ffa8379c/pb/social.html');
