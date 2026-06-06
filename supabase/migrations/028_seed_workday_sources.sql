-- 028 — 外企扩源（Workday）：我方 live 探活在华岗位 > 0 的跨国企业
-- Workday CXS API + location facet 服务端过滤到大中华区；jd_url = {host}/{site}{externalPath}（live 验证渲染对应岗位）。
-- 外企100强主力平台：覆盖半导体/医药/金融。crawl_method=http（httpx POST，无浏览器）。
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'NVIDIA', 'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs', 'official', 'workday', 'http', 'NVIDIA（半导体·AI，Workday，probe live 在华 154 岗）'
where not exists (select 1 from sources where source_url = 'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Pfizer 辉瑞', 'https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs', 'official', 'workday', 'http', 'Pfizer 辉瑞（医药，Workday，probe live 在华 154 岗）'
where not exists (select 1 from sources where source_url = 'https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Citi 花旗', 'https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs', 'official', 'workday', 'http', 'Citi 花旗（金融，Workday，probe live 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'MSD 默沙东', 'https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs', 'official', 'workday', 'http', 'MSD 默沙东（医药，Workday，probe live 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Mastercard 万事达', 'https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs', 'official', 'workday', 'http', 'Mastercard 万事达（金融·支付，Workday，probe live 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs');
