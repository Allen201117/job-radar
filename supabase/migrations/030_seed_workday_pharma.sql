-- 030 — 外企100强扩源（Workday 医药/医疗器械批次）：我方 live 探活在华岗位 > 0 的跨国药企
-- 修复了 Workday facet 应用：按 param 分组逐组试探取命中最多的单组（避免跨 param AND 坍缩，
-- 自适应 locationCountry/locationHierarchy1/locations 等不同租户结构）。jd_url = {host}/{site}{externalPath}（live 验证）。
-- crawl_method=http（httpx POST，无浏览器）。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '阿斯利康 AstraZeneca', 'https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs', 'official', 'workday', 'http', '阿斯利康（医药，Workday，live 在华 293+ 岗）'
where not exists (select 1 from sources where source_url = 'https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '赛诺菲 Sanofi', 'https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs', 'official', 'workday', 'http', '赛诺菲（医药，Workday，live 在华 123+ 岗）'
where not exists (select 1 from sources where source_url = 'https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '武田制药 Takeda', 'https://takeda.wd3.myworkdayjobs.com/wday/cxs/takeda/External/jobs', 'official', 'workday', 'http', '武田制药（医药，Workday，live 在华 108 岗）'
where not exists (select 1 from sources where source_url = 'https://takeda.wd3.myworkdayjobs.com/wday/cxs/takeda/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '雅培 Abbott', 'https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers/jobs', 'official', 'workday', 'http', '雅培（医疗·营养，Workday，live 在华 114 岗）'
where not exists (select 1 from sources where source_url = 'https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '美敦力 Medtronic', 'https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs', 'official', 'workday', 'http', '美敦力（医疗器械，Workday，live 在华 79 岗）'
where not exists (select 1 from sources where source_url = 'https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '诺华 Novartis', 'https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs', 'official', 'workday', 'http', '诺华（医药，Workday，live 在华 6 岗·港；大陆岗经其他渠道）'
where not exists (select 1 from sources where source_url = 'https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs');
