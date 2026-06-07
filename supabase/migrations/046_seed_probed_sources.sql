-- 046 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '英特尔 Intel', 'https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs', 'official', 'workday', 'http', 'foreign', '半导体', '英特尔 Intel（半导体，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '赛默飞 Thermo Fisher', 'https://thermofisher.wd5.myworkdayjobs.com/wday/cxs/thermofisher/ThermoFisherCareers/jobs', 'official', 'workday', 'http', 'foreign', '生命科学', '赛默飞 Thermo Fisher（生命科学，probe live 探活 在华 266 岗）'
where not exists (select 1 from sources where source_url = 'https://thermofisher.wd5.myworkdayjobs.com/wday/cxs/thermofisher/ThermoFisherCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '强生 Johnson & Johnson', 'https://jj.wd5.myworkdayjobs.com/wday/cxs/jj/JJ/jobs', 'official', 'workday', 'http', 'foreign', '医药·医疗', '强生 Johnson & Johnson（医药·医疗，probe live 探活 在华 212 岗）'
where not exists (select 1 from sources where source_url = 'https://jj.wd5.myworkdayjobs.com/wday/cxs/jj/JJ/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Visa', 'https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/jobs', 'official', 'workday', 'http', 'foreign', '金融·支付', 'Visa（金融·支付，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '陶氏化学 Dow', 'https://dow.wd1.myworkdayjobs.com/wday/cxs/dow/ExternalCareers/jobs', 'official', 'workday', 'http', 'foreign', '化工', '陶氏化学 Dow（化工，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://dow.wd1.myworkdayjobs.com/wday/cxs/dow/ExternalCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '因美纳 Illumina', 'https://illumina.wd1.myworkdayjobs.com/wday/cxs/illumina/illumina-careers/jobs', 'official', 'workday', 'http', 'foreign', '生命科学', '因美纳 Illumina（生命科学，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://illumina.wd1.myworkdayjobs.com/wday/cxs/illumina/illumina-careers/jobs');
