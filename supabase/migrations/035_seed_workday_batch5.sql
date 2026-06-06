-- 035 — 外企100强扩源（Workday 批 5：半导体设备/工程机械）：我方 live 探活在华岗 > 0
-- 复用 030 facet 修复。jd_url = {host}/{site}{externalPath}（live 验证）。crawl_method=http。
-- Idempotent: guarded by source_url。卡特彼勒 115 岗均在 China facet（含 City-CHN 缩写地名）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '卡特彼勒 Caterpillar', 'https://cat.wd5.myworkdayjobs.com/wday/cxs/cat/CaterpillarCareers/jobs', 'official', 'workday', 'http', '卡特彼勒（工程机械，Workday，live 在华 115 岗）'
where not exists (select 1 from sources where source_url = 'https://cat.wd5.myworkdayjobs.com/wday/cxs/cat/CaterpillarCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '科磊 KLA', 'https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs', 'official', 'workday', 'http', '科磊 KLA（半导体设备，Workday，live 在华 36 岗）'
where not exists (select 1 from sources where source_url = 'https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs');
