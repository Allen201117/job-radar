-- 093 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Cadence 铿腾', 'https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs', 'official', 'workday', 'http', 'foreign', 'EDA软件', 'Cadence 铿腾（EDA软件，probe live 探活 在华 84 岗）'
where not exists (select 1 from sources where source_url = 'https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Workday', 'https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/jobs', 'official', 'workday', 'http', 'foreign', '企业软件', 'Workday（企业软件，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Rockwell Automation 罗克韦尔', 'https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation/jobs', 'official', 'workday', 'http', 'foreign', '工业自动化', 'Rockwell Automation 罗克韦尔（工业自动化，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation/jobs');
