-- 106 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '隆基绿能 LONGi', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html', 'official', 'hotjob', 'http', 'private', '光伏·新能源', '隆基绿能 LONGi（光伏·新能源，probe live 探活 在华 108 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '隆基绿能 LONGi 校招', 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html', 'official', 'hotjob', 'http', 'private', '光伏·新能源', '隆基绿能 LONGi 校招（光伏·新能源，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://longi.hotjob.cn/SU649d2f9c0dcad4644b43df7e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份 GoerTek', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html', 'official', 'hotjob', 'http', 'private', '消费电子', '歌尔股份 GoerTek（消费电子，probe live 探活 在华 74 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份 GoerTek 校招', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html', 'official', 'hotjob', 'http', 'private', '消费电子', '歌尔股份 GoerTek 校招（消费电子，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '歌尔股份 GoerTek 实习', 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html', 'official', 'hotjob', 'http', 'private', '消费电子', '歌尔股份 GoerTek 实习（消费电子，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/interns.html');
