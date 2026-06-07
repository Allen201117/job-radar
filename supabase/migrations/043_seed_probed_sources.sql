-- 043 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '德意志银行 Deutsche Bank', 'https://db.wd3.myworkdayjobs.com/wday/cxs/db/DBWebsite/jobs', 'official', 'workday', 'http', 'foreign', '金融', '德意志银行 Deutsche Bank（金融，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://db.wd3.myworkdayjobs.com/wday/cxs/db/DBWebsite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Marvell', 'https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs', 'official', 'workday', 'http', 'foreign', '半导体', 'Marvell（半导体，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '惠普 HP', 'https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs', 'official', 'workday', 'http', 'foreign', '硬件·IT', '惠普 HP（硬件·IT，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '慧与 HPE', 'https://hpe.wd5.myworkdayjobs.com/wday/cxs/hpe/jobsathpe/jobs', 'official', 'workday', 'http', 'foreign', '硬件·IT', '慧与 HPE（硬件·IT，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://hpe.wd5.myworkdayjobs.com/wday/cxs/hpe/jobsathpe/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奥的斯 Otis', 'https://otis.wd5.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs', 'official', 'workday', 'http', 'foreign', '工业·电梯', '奥的斯 Otis（工业·电梯，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://otis.wd5.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '特灵 Trane', 'https://tranetechnologies.wd12.myworkdayjobs.com/wday/cxs/tranetechnologies/Trane_Technologies_Careers/jobs', 'official', 'workday', 'http', 'foreign', '工业·暖通', '特灵 Trane（工业·暖通，probe live 探活 在华 85 岗）'
where not exists (select 1 from sources where source_url = 'https://tranetechnologies.wd12.myworkdayjobs.com/wday/cxs/tranetechnologies/Trane_Technologies_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '开利 Carrier', 'https://carrier.wd5.myworkdayjobs.com/wday/cxs/carrier/jobs/jobs', 'official', 'workday', 'http', 'foreign', '工业·暖通', '开利 Carrier（工业·暖通，probe live 探活 在华 27 岗）'
where not exists (select 1 from sources where source_url = 'https://carrier.wd5.myworkdayjobs.com/wday/cxs/carrier/jobs/jobs');
