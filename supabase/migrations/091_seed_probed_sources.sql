-- 091 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Novartis 诺华', 'https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Novartis 诺华（医药·制药，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'GSK 葛兰素史克', 'https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSKCareers/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'GSK 葛兰素史克（医药·制药，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSKCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Intel 英特尔', 'https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs', 'official', 'workday', 'http', 'foreign', '半导体', 'Intel 英特尔（半导体，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Micron 美光', 'https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs', 'official', 'workday', 'http', 'foreign', '半导体·存储', 'Micron 美光（半导体·存储，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'KLA 科磊', 'https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs', 'official', 'workday', 'http', 'foreign', '半导体设备', 'KLA 科磊（半导体设备，probe live 探活 在华 37 岗）'
where not exists (select 1 from sources where source_url = 'https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Morgan Stanley 摩根士丹利', 'https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs', 'official', 'workday', 'http', 'foreign', '金融·投行', 'Morgan Stanley 摩根士丹利（金融·投行，probe live 探活 在华 44 岗）'
where not exists (select 1 from sources where source_url = 'https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs');
