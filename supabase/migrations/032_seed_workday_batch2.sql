-- 032 — 外企100强扩源（Workday 批 2：半导体/消费/工业/金融/软件）：我方 live 探活在华岗 > 0
-- 复用 030 的 facet 修复（按 param 分组取命中最多单组）。jd_url = {host}/{site}{externalPath}（live 验证）。
-- crawl_method=http。Idempotent: guarded by source_url。
-- 港岗（china=0）保留：HK 属本雷达大中华区口径，且为真实 per-job 链接。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '应用材料 Applied Materials', 'https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs', 'official', 'workday', 'http', '应用材料（半导体设备，Workday，live 在华 74 岗）'
where not exists (select 1 from sources where source_url = 'https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '美光 Micron', 'https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs', 'official', 'workday', 'http', '美光（半导体·存储，Workday，live 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://micron.wd1.myworkdayjobs.com/wday/cxs/micron/External/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '可口可乐 Coca-Cola', 'https://coke.wd1.myworkdayjobs.com/wday/cxs/coke/coca-cola-careers/jobs', 'official', 'workday', 'http', '可口可乐（消费·饮料，Workday，live 在华 33 岗）'
where not exists (select 1 from sources where source_url = 'https://coke.wd1.myworkdayjobs.com/wday/cxs/coke/coca-cola-careers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '3M', 'https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs', 'official', 'workday', 'http', '3M（工业·材料，Workday，live 在华 54 岗）'
where not exists (select 1 from sources where source_url = 'https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Autodesk 欧特克', 'https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs', 'official', 'workday', 'http', 'Autodesk 欧特克（软件·设计，Workday，live 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '摩根士丹利 Morgan Stanley', 'https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs', 'official', 'workday', 'http', '摩根士丹利（金融·投行，Workday，live 在华 49 岗·港）'
where not exists (select 1 from sources where source_url = 'https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs');
