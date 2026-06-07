-- 049 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '爱德华兹生命科学 Edwards Lifesciences', 'https://edwards.wd5.myworkdayjobs.com/wday/cxs/edwards/edwardscareers/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', '爱德华兹生命科学 Edwards Lifesciences（医疗器械，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://edwards.wd5.myworkdayjobs.com/wday/cxs/edwards/edwardscareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '爱尔康 Alcon', 'https://alcon.wd5.myworkdayjobs.com/wday/cxs/alcon/careers_alcon/jobs', 'official', 'workday', 'http', 'foreign', '眼科·医疗', '爱尔康 Alcon（眼科·医疗，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://alcon.wd5.myworkdayjobs.com/wday/cxs/alcon/careers_alcon/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '瑞思迈 ResMed', 'https://resmed.wd3.myworkdayjobs.com/wday/cxs/resmed/ResMed_External_Careers/jobs', 'official', 'workday', 'http', 'foreign', '医疗设备', '瑞思迈 ResMed（医疗设备，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://resmed.wd3.myworkdayjobs.com/wday/cxs/resmed/ResMed_External_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '达信 Marsh McLennan', 'https://mmc.wd1.myworkdayjobs.com/wday/cxs/mmc/MMC/jobs', 'official', 'workday', 'http', 'foreign', '金融·保险经纪', '达信 Marsh McLennan（金融·保险经纪，probe live 探活 在华 39 岗）'
where not exists (select 1 from sources where source_url = 'https://mmc.wd1.myworkdayjobs.com/wday/cxs/mmc/MMC/jobs');
