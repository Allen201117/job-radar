-- 105 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '伊利', 'https://yili.hotjob.cn/wt/yili/web/index', 'official', 'wt', 'http', 'private', '食品·乳业', '伊利（食品·乳业，probe live 探活 在华 402 岗）'
where not exists (select 1 from sources where source_url = 'https://yili.hotjob.cn/wt/yili/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中广核', 'https://cgn.hotjob.cn/wt/CGN/web/index', 'official', 'wt', 'http', 'private', '能源·核电·央企', '中广核（能源·核电·央企，probe live 探活 在华 333 岗）'
where not exists (select 1 from sources where source_url = 'https://cgn.hotjob.cn/wt/CGN/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国电信', 'https://www.hotjob.cn/wt/CT/web/index', 'official', 'wt', 'http', 'private', '电信·央企', '中国电信（电信·央企，probe live 探活 在华 113 岗）'
where not exists (select 1 from sources where source_url = 'https://www.hotjob.cn/wt/CT/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '现代汽车 HMGC', 'https://hmgc.hotjob.cn/wt/HMGC/web/index', 'official', 'wt', 'http', 'private', '汽车', '现代汽车 HMGC（汽车，probe live 探活 在华 47 岗）'
where not exists (select 1 from sources where source_url = 'https://hmgc.hotjob.cn/wt/HMGC/web/index');
