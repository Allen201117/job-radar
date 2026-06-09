-- 094 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Abbott 雅培', 'https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', 'Abbott 雅培（医疗器械，probe live 探活 在华 120 岗）'
where not exists (select 1 from sources where source_url = 'https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Medtronic 美敦力', 'https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', 'Medtronic 美敦力（医疗器械，probe live 探活 在华 89 岗）'
where not exists (select 1 from sources where source_url = 'https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Eli Lilly 礼来', 'https://lilly.wd5.myworkdayjobs.com/wday/cxs/lilly/LLY/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Eli Lilly 礼来（医药·制药，probe live 探活 在华 49 岗）'
where not exists (select 1 from sources where source_url = 'https://lilly.wd5.myworkdayjobs.com/wday/cxs/lilly/LLY/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Takeda 武田', 'https://takeda.wd3.myworkdayjobs.com/wday/cxs/takeda/External/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Takeda 武田（医药·制药，probe live 探活 在华 112 岗）'
where not exists (select 1 from sources where source_url = 'https://takeda.wd3.myworkdayjobs.com/wday/cxs/takeda/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Amgen 安进', 'https://amgen.wd1.myworkdayjobs.com/wday/cxs/amgen/Careers/jobs', 'official', 'workday', 'http', 'foreign', '生物医药', 'Amgen 安进（生物医药，probe live 探活 在华 39 岗）'
where not exists (select 1 from sources where source_url = 'https://amgen.wd1.myworkdayjobs.com/wday/cxs/amgen/Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Stryker 史赛克', 'https://stryker.wd1.myworkdayjobs.com/wday/cxs/stryker/StrykerCareers/jobs', 'official', 'workday', 'http', 'foreign', '医疗器械', 'Stryker 史赛克（医疗器械，probe live 探活 在华 32 岗）'
where not exists (select 1 from sources where source_url = 'https://stryker.wd1.myworkdayjobs.com/wday/cxs/stryker/StrykerCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'BlackRock 贝莱德', 'https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/BlackRock_Professional/jobs', 'official', 'workday', 'http', 'foreign', '金融·资管', 'BlackRock 贝莱德（金融·资管，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/BlackRock_Professional/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'HP 惠普', 'https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs', 'official', 'workday', 'http', 'foreign', '硬件·PC', 'HP 惠普（硬件·PC，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'HPE 慧与', 'https://hpe.wd5.myworkdayjobs.com/wday/cxs/hpe/Jobsathpe/jobs', 'official', 'workday', 'http', 'foreign', '企业IT', 'HPE 慧与（企业IT，probe live 探活 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://hpe.wd5.myworkdayjobs.com/wday/cxs/hpe/Jobsathpe/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '3M', 'https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs', 'official', 'workday', 'http', 'foreign', '工业·材料', '3M（工业·材料，probe live 探活 在华 57 岗）'
where not exists (select 1 from sources where source_url = 'https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Carrier 开利', 'https://carrier.wd5.myworkdayjobs.com/wday/cxs/carrier/jobs/jobs', 'official', 'workday', 'http', 'foreign', '工业·暖通', 'Carrier 开利（工业·暖通，probe live 探活 在华 33 岗）'
where not exists (select 1 from sources where source_url = 'https://carrier.wd5.myworkdayjobs.com/wday/cxs/carrier/jobs/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Autodesk 欧特克', 'https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs', 'official', 'workday', 'http', 'foreign', '软件·设计', 'Autodesk 欧特克（软件·设计，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Bristol Myers Squibb 施贵宝', 'https://bristolmyerssquibb.wd5.myworkdayjobs.com/wday/cxs/bristolmyerssquibb/BMS/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Bristol Myers Squibb 施贵宝（医药·制药，probe live 探活 在华 62 岗）'
where not exists (select 1 from sources where source_url = 'https://bristolmyerssquibb.wd5.myworkdayjobs.com/wday/cxs/bristolmyerssquibb/BMS/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'HSBC 汇丰', 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com', 'official', 'eightfold', 'http', 'foreign', '金融·银行', 'HSBC 汇丰（金融·银行，probe live 探活 在华 478 岗）'
where not exists (select 1 from sources where source_url = 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com');
