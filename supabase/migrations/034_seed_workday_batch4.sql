-- 034 — 外企100强扩源（Workday 批 4：化工/金融保险）：我方 live 探活在华岗 > 0
-- 复用 030 facet 修复 + 收紧的回退过滤。jd_url = {host}/{site}{externalPath}（live 验证）。
-- crawl_method=http。Idempotent: guarded by source_url。
-- 宏利 china=13(大陆)+港；杜邦该 site 无 China facet（facet=False），靠严格 is_china_location 回退只放行在华岗（live 验证 7 个均上海）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '宏利金融 Manulife', 'https://manulife.wd3.myworkdayjobs.com/wday/cxs/manulife/MFCJH_Jobs/jobs', 'official', 'workday', 'http', '宏利金融（金融·保险，Workday，live 在华 108 岗·含港）'
where not exists (select 1 from sources where source_url = 'https://manulife.wd3.myworkdayjobs.com/wday/cxs/manulife/MFCJH_Jobs/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '杜邦 DuPont', 'https://dupont.wd5.myworkdayjobs.com/wday/cxs/dupont/Jobs/jobs', 'official', 'workday', 'http', '杜邦（化工·材料，Workday，live 在华 7 岗·上海；该 site 无 China facet，靠严格在华过滤回退）'
where not exists (select 1 from sources where source_url = 'https://dupont.wd5.myworkdayjobs.com/wday/cxs/dupont/Jobs/jobs');
