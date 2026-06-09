-- 097 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广发证券 GF', 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/social.html', 'official', 'hotjob', 'http', 'private', '证券', '广发证券 GF（证券，probe live 探活 在华 158 岗）'
where not exists (select 1 from sources where source_url = 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广发证券 GF 校招', 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/school.html', 'official', 'hotjob', 'http', 'private', '证券', '广发证券 GF 校招（证券，probe live 探活 在华 39 岗）'
where not exists (select 1 from sources where source_url = 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广发证券 GF 实习', 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/interns.html', 'official', 'hotjob', 'http', 'private', '证券', '广发证券 GF 实习（证券，probe live 探活 在华 53 岗）'
where not exists (select 1 from sources where source_url = 'https://gf.hotjob.cn/SU625527c30dcad4021443cdda/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广西柳工 LiuGong', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html', 'official', 'hotjob', 'http', 'private', '工程机械', '广西柳工 LiuGong（工程机械，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广西柳工 LiuGong 校招', 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html', 'official', 'hotjob', 'http', 'private', '工程机械', '广西柳工 LiuGong 校招（工程机械，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://liugong.hotjob.cn/SU6132e87abef57c3b637dcb71/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '创维 Skyworth 校招', 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html', 'official', 'hotjob', 'http', 'private', '消费电子', '创维 Skyworth 校招（消费电子，probe live 探活 在华 58 岗）'
where not exists (select 1 from sources where source_url = 'https://skyworth.hotjob.cn/SU668b8b251c240e2e76ea71d8/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国物流集团', 'https://chinalogisticsgroup.hotjob.cn/SU6426c1e1bef57c1e26962897/pb/social.html', 'official', 'hotjob', 'http', 'private', '物流·央企', '中国物流集团（物流·央企，probe live 探活 在华 58 岗）'
where not exists (select 1 from sources where source_url = 'https://chinalogisticsgroup.hotjob.cn/SU6426c1e1bef57c1e26962897/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国物流集团 校招', 'https://chinalogisticsgroup.hotjob.cn/SU6426c1e1bef57c1e26962897/pb/school.html', 'official', 'hotjob', 'http', 'private', '物流·央企', '中国物流集团 校招（物流·央企，probe live 探活 在华 68 岗）'
where not exists (select 1 from sources where source_url = 'https://chinalogisticsgroup.hotjob.cn/SU6426c1e1bef57c1e26962897/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云尖信息', 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/social.html', 'official', 'hotjob', 'http', 'private', '信息技术', '云尖信息（信息技术，probe live 探活 在华 183 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云尖信息 校招', 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/school.html', 'official', 'hotjob', 'http', 'private', '信息技术', '云尖信息 校招（信息技术，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云尖信息 实习', 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/interns.html', 'official', 'hotjob', 'http', 'private', '信息技术', '云尖信息 实习（信息技术，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU6298e4f10dcad45229985fd0/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '赢家时尚', 'https://wecruit.hotjob.cn/SU64f060386202cc142abc52eb/pb/social.html', 'official', 'hotjob', 'http', 'private', '消费·服饰', '赢家时尚（消费·服饰，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64f060386202cc142abc52eb/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '和睦家医疗', 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/social.html', 'official', 'hotjob', 'http', 'private', '医疗健康', '和睦家医疗（医疗健康，probe live 探活 在华 183 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '和睦家医疗 校招', 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/school.html', 'official', 'hotjob', 'http', 'private', '医疗健康', '和睦家医疗 校招（医疗健康，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '和睦家医疗 实习', 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/interns.html', 'official', 'hotjob', 'http', 'private', '医疗健康', '和睦家医疗 实习（医疗健康，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源 ATL', 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html', 'official', 'hotjob', 'http', 'private', '新能源·电池', '宁德新能源 ATL（新能源·电池，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源 ATL 校招', 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html', 'official', 'hotjob', 'http', 'private', '新能源·电池', '宁德新能源 ATL 校招（新能源·电池，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德新能源 ATL 实习', 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html', 'official', 'hotjob', 'http', 'private', '新能源·电池', '宁德新能源 ATL 实习（新能源·电池，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中化 ChemChina', 'https://wecruit.hotjob.cn/SU611a641a0dcad4106f04950e/pb/social.html', 'official', 'hotjob', 'http', 'private', '化工·央企', '中国中化 ChemChina（化工·央企，probe live 探活 在华 95 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU611a641a0dcad4106f04950e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中化 ChemChina 校招', 'https://wecruit.hotjob.cn/SU611a641a0dcad4106f04950e/pb/school.html', 'official', 'hotjob', 'http', 'private', '化工·央企', '中国中化 ChemChina 校招（化工·央企，probe live 探活 在华 92 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU611a641a0dcad4106f04950e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州凌志软件', 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/social.html', 'official', 'hotjob', 'http', 'private', '软件', '苏州凌志软件（软件，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '苏州凌志软件 校招', 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/school.html', 'official', 'hotjob', 'http', 'private', '软件', '苏州凌志软件 校招（软件，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/school.html');
