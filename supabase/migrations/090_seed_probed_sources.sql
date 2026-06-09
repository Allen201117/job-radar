-- 090 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'AstraZeneca 阿斯利康', 'https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'AstraZeneca 阿斯利康（医药·制药，probe live 探活 在华 436 岗）'
where not exists (select 1 from sources where source_url = 'https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Sanofi 赛诺菲', 'https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs', 'official', 'workday', 'http', 'foreign', '医药·制药', 'Sanofi 赛诺菲（医药·制药，probe live 探活 在华 164 岗）'
where not exists (select 1 from sources where source_url = 'https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Applied Materials 应用材料', 'https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs', 'official', 'workday', 'http', 'foreign', '半导体设备', 'Applied Materials 应用材料（半导体设备，probe live 探活 在华 84 岗）'
where not exists (select 1 from sources where source_url = 'https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs');
