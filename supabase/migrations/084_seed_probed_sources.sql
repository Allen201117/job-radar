-- 084 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL', 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html', 'official', 'hotjob', 'playwright', 'private', '消费电子·显示', 'TCL（消费电子·显示，probe live 探活 在华 38 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL 校招', 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/school.html', 'official', 'hotjob', 'playwright', 'private', '消费电子·显示', 'TCL 校招（消费电子·显示，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'TCL 实习', 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/interns.html', 'official', 'hotjob', 'playwright', 'private', '消费电子·显示', 'TCL 实习（消费电子·显示，probe live 探活 在华 21 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/interns.html');
