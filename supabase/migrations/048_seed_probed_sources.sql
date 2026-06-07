-- 048 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Kenvue 科赴', 'https://kenvue.wd5.myworkdayjobs.com/wday/cxs/kenvue/kenvue/jobs', 'official', 'workday', 'http', 'foreign', '消费健康', 'Kenvue 科赴（消费健康，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://kenvue.wd5.myworkdayjobs.com/wday/cxs/kenvue/kenvue/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'GE医疗 GE HealthCare', 'https://gehc.wd5.myworkdayjobs.com/wday/cxs/gehc/GEHC_ExternalSite/jobs', 'official', 'workday', 'http', 'foreign', '医疗设备', 'GE医疗 GE HealthCare（医疗设备，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://gehc.wd5.myworkdayjobs.com/wday/cxs/gehc/GEHC_ExternalSite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '飞利浦 Philips', 'https://philips.wd3.myworkdayjobs.com/wday/cxs/philips/jobs-and-careers/jobs', 'official', 'workday', 'http', 'foreign', '医疗·健康科技', '飞利浦 Philips（医疗·健康科技，probe live 探活 在华 136 岗）'
where not exists (select 1 from sources where source_url = 'https://philips.wd3.myworkdayjobs.com/wday/cxs/philips/jobs-and-careers/jobs');
