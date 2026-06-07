-- 045 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安进 Amgen', 'https://amgen.wd1.myworkdayjobs.com/wday/cxs/amgen/Careers/jobs', 'official', 'workday', 'http', 'foreign', '生物医药', '安进 Amgen（生物医药，probe live 探活 在华 37 岗）'
where not exists (select 1 from sources where source_url = 'https://amgen.wd1.myworkdayjobs.com/wday/cxs/amgen/Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '渤健 Biogen', 'https://biibhr.wd3.myworkdayjobs.com/wday/cxs/biibhr/external/jobs', 'official', 'workday', 'http', 'foreign', '生物医药', '渤健 Biogen（生物医药，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://biibhr.wd3.myworkdayjobs.com/wday/cxs/biibhr/external/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '帝亚吉欧 Diageo', 'https://diageo.wd3.myworkdayjobs.com/wday/cxs/diageo/Diageo_Careers/jobs', 'official', 'workday', 'http', 'foreign', '消费·酒类', '帝亚吉欧 Diageo（消费·酒类，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://diageo.wd3.myworkdayjobs.com/wday/cxs/diageo/Diageo_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '保乐力加 Pernod Ricard', 'https://pernodricard.wd3.myworkdayjobs.com/wday/cxs/pernodricard/pernod-ricard/jobs', 'official', 'workday', 'http', 'foreign', '消费·酒类', '保乐力加 Pernod Ricard（消费·酒类，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://pernodricard.wd3.myworkdayjobs.com/wday/cxs/pernodricard/pernod-ricard/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '马士基 Maersk', 'https://maersk.wd3.myworkdayjobs.com/wday/cxs/maersk/Maersk_Careers/jobs', 'official', 'workday', 'http', 'foreign', '物流·航运', '马士基 Maersk（物流·航运，probe live 探活 在华 41 岗）'
where not exists (select 1 from sources where source_url = 'https://maersk.wd3.myworkdayjobs.com/wday/cxs/maersk/Maersk_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'UPS', 'https://hcmportal.wd5.myworkdayjobs.com/wday/cxs/hcmportal/Search/jobs', 'official', 'workday', 'http', 'foreign', '物流', 'UPS（物流，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://hcmportal.wd5.myworkdayjobs.com/wday/cxs/hcmportal/Search/jobs');
