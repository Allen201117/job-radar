-- 047 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '丹纳赫 Danaher', 'https://danaher.wd1.myworkdayjobs.com/wday/cxs/danaher/DanaherJobs/jobs', 'official', 'workday', 'http', 'foreign', '生命科学·诊断', '丹纳赫 Danaher（生命科学·诊断，probe live 探活 在华 102 岗）'
where not exists (select 1 from sources where source_url = 'https://danaher.wd1.myworkdayjobs.com/wday/cxs/danaher/DanaherJobs/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '百时美施贵宝 BMS', 'https://bristolmyerssquibb.wd5.myworkdayjobs.com/wday/cxs/bristolmyerssquibb/BMS/jobs', 'official', 'workday', 'http', 'foreign', '医药', '百时美施贵宝 BMS（医药，probe live 探活 在华 60 岗）'
where not exists (select 1 from sources where source_url = 'https://bristolmyerssquibb.wd5.myworkdayjobs.com/wday/cxs/bristolmyerssquibb/BMS/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '吉利德 Gilead', 'https://gilead.wd1.myworkdayjobs.com/wday/cxs/gilead/gileadcareers/jobs', 'official', 'workday', 'http', 'foreign', '生物医药', '吉利德 Gilead（生物医药，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://gilead.wd1.myworkdayjobs.com/wday/cxs/gilead/gileadcareers/jobs');
