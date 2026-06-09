-- 112 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国五矿', 'https://minmetals.hotjob.cn/wt/minmetals/web/index', 'official', 'wt', 'http', 'private', '矿业', '中国五矿（矿业，probe live 探活 在华 259 岗）'
where not exists (select 1 from sources where source_url = 'https://minmetals.hotjob.cn/wt/minmetals/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '国机集团', 'https://sinomach.hotjob.cn/wt/sinomach/web/index', 'official', 'wt', 'http', 'private', '装备', '国机集团（装备，probe live 探活 在华 139 岗）'
where not exists (select 1 from sources where source_url = 'https://sinomach.hotjob.cn/wt/sinomach/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国一汽', 'https://faw.hotjob.cn/wt/FAW/web/index', 'official', 'wt', 'http', 'private', '汽车', '中国一汽（汽车，probe live 探活 在华 1043 岗）'
where not exists (select 1 from sources where source_url = 'https://faw.hotjob.cn/wt/FAW/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/social.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车（汽车，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/school.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车（汽车，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/interns.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车（汽车，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html', 'official', 'hotjob', 'http', 'private', '装备', '中国中车（装备，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/school.html', 'official', 'hotjob', 'http', 'private', '装备', '中国中车（装备，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国中车', 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/interns.html', 'official', 'hotjob', 'http', 'private', '装备', '中国中车（装备，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国一重', 'https://cfhi.hotjob.cn/SU6738316a1eb805735df19c2a/pb/social.html', 'official', 'hotjob', 'http', 'private', '装备', '中国一重（装备，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://cfhi.hotjob.cn/SU6738316a1eb805735df19c2a/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国一重', 'https://cfhi.hotjob.cn/SU6738316a1eb805735df19c2a/pb/school.html', 'official', 'hotjob', 'http', 'private', '装备', '中国一重（装备，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://cfhi.hotjob.cn/SU6738316a1eb805735df19c2a/pb/school.html');
