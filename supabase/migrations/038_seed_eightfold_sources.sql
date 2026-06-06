-- 038 — 外企模块扩源（Eightfold ATS）：新增 eightfold 通用适配器后我方 live 探活在华岗 > 0
-- eightfold.ai 公开接口 + location 服务端收窄到在华；jd_url 用 canonicalPositionUrl（公司自有 careers 域名真实 per-job 链接，live 验证）。
-- crawl_method=http。带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '汇丰 HSBC', 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com', 'official', 'eightfold', 'http', 'foreign', '金融',
       '汇丰（金融，Eightfold，live 在华 160+ 岗）'
where not exists (select 1 from sources where source_url = 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '意法半导体 ST', 'https://stmicroelectronics.eightfold.ai/api/apply/v2/jobs?domain=stmicroelectronics.com', 'official', 'eightfold', 'http', 'foreign', '半导体',
       '意法半导体（半导体，Eightfold，live 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://stmicroelectronics.eightfold.ai/api/apply/v2/jobs?domain=stmicroelectronics.com');
