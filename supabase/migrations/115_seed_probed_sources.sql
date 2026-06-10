-- 115 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '理想汽车', 'https://li.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车', '理想汽车（汽车，probe live 探活 在华 467 岗）'
where not exists (select 1 from sources where source_url = 'https://li.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海澜之家', 'https://www.hotjob.cn/wt/HLA/web/index', 'official', 'wt', 'http', 'private', '服装', '海澜之家（服装，probe live 探活 在华 83 岗）'
where not exists (select 1 from sources where source_url = 'https://www.hotjob.cn/wt/HLA/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇瑞汽车', 'https://chery.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '知名私企', '奇瑞汽车（知名私企，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://chery.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇瑞汽车', 'https://chery.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '知名私企', '奇瑞汽车（知名私企，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://chery.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '兆易创新', 'https://app.mokahr.com/campus_apply/gigadevice/92215', 'official', 'moka', 'playwright', 'private', '半导体', '兆易创新（半导体，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/gigadevice/92215');
