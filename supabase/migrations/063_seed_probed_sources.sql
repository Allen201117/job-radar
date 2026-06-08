-- 063 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '联影医疗 UIH', 'https://united-imaging.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '医疗器械·影像设备', '联影医疗 UIH（医疗器械·影像设备，probe live 探活 在华 65 岗）'
where not exists (select 1 from sources where source_url = 'https://united-imaging.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蒙牛乳业 MENGNIU', 'https://mengniu.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '乳业·消费', '蒙牛乳业 MENGNIU（乳业·消费，probe live 探活 在华 50 岗）'
where not exists (select 1 from sources where source_url = 'https://mengniu.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大华股份 Dahua', 'https://dahua.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '安防·AIoT', '大华股份 Dahua（安防·AIoT，probe live 探活 在华 43 岗）'
where not exists (select 1 from sources where source_url = 'https://dahua.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '复星医药 Fosun Pharma', 'https://fosunpharma.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '医药·生物', '复星医药 Fosun Pharma（医药·生物，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://fosunpharma.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇瑞汽车 CHERY', 'https://chery.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '汽车·制造', '奇瑞汽车 CHERY（汽车·制造，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://chery.zhiye.com/social/jobs');
