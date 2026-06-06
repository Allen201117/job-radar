-- 033 — 外企100强扩源（Workday 批 3：医药/汽车/通信）：我方 live 探活在华岗 > 0
-- 复用 030 facet 修复。jd_url = {host}/{site}{externalPath}（live 验证）。crawl_method=http。
-- Idempotent: guarded by source_url。港岗（china=0）保留（大中华区口径）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '通用汽车 GM', 'https://generalmotors.wd5.myworkdayjobs.com/wday/cxs/generalmotors/Careers_GM/jobs', 'official', 'workday', 'http', '通用汽车（汽车，Workday，live 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://generalmotors.wd5.myworkdayjobs.com/wday/cxs/generalmotors/Careers_GM/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '思科 Cisco', 'https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs', 'official', 'workday', 'http', '思科（网络·通信，Workday，live 在华 9 岗）'
where not exists (select 1 from sources where source_url = 'https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '罗氏 Roche', 'https://roche.wd3.myworkdayjobs.com/wday/cxs/roche/roche-ext/jobs', 'official', 'workday', 'http', '罗氏（医药·诊断，Workday，live 在华 7 岗·港）'
where not exists (select 1 from sources where source_url = 'https://roche.wd3.myworkdayjobs.com/wday/cxs/roche/roche-ext/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '葛兰素史克 GSK', 'https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSKCareers/jobs', 'official', 'workday', 'http', '葛兰素史克（医药，Workday，live 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/GSKCareers/jobs');
