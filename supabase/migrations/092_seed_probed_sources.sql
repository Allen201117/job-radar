-- 092 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Roche 罗氏', 'https://roche.wd3.myworkdayjobs.com/wday/cxs/roche/roche-ext/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Roche 罗氏（医药·制药，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://roche.wd3.myworkdayjobs.com/wday/cxs/roche/roche-ext/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'NXP 恩智浦', 'https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs', 'official', 'workday', 'http', 'foreign', '半导体', 'NXP 恩智浦（半导体，probe live 探活 在华 46 岗）'
where not exists (select 1 from sources where source_url = 'https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Broadcom 博通', 'https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs', 'official', 'workday', 'http', 'foreign', '半导体', 'Broadcom 博通（半导体，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Cisco 思科', 'https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs', 'official', 'workday', 'http', 'foreign', '网络设备', 'Cisco 思科（网络设备，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Deutsche Bank 德意志银行', 'https://db.wd3.myworkdayjobs.com/wday/cxs/db/DBWebsite/jobs', 'official', 'workday', 'http', 'foreign', '金融·投行', 'Deutsche Bank 德意志银行（金融·投行，probe live 探活 在华 28 岗）'
where not exists (select 1 from sources where source_url = 'https://db.wd3.myworkdayjobs.com/wday/cxs/db/DBWebsite/jobs');
