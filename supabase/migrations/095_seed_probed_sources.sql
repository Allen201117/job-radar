-- 095 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车 DFMC', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/social.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车 DFMC（汽车，probe live 探活 在华 192 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车 DFMC 校招', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/school.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车 DFMC 校招（汽车，probe live 探活 在华 158 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东风汽车 DFMC 实习', 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/interns.html', 'official', 'hotjob', 'http', 'private', '汽车', '东风汽车 DFMC 实习（汽车，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://dfmc.hotjob.cn/SU60cc3c9cbef57c51986a8ca0/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '光启技术', 'https://wecruit.hotjob.cn/SU60b9cab4bef57c11896a86b4/pb/social.html', 'official', 'hotjob', 'http', 'private', '科技·军工', '光启技术（科技·军工，probe live 探活 在华 24 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU60b9cab4bef57c11896a86b4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '光启技术 校招', 'https://wecruit.hotjob.cn/SU60b9cab4bef57c11896a86b4/pb/school.html', 'official', 'hotjob', 'http', 'private', '科技·军工', '光启技术 校招（科技·军工，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU60b9cab4bef57c11896a86b4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中信银行信用卡中心', 'https://wecruit.hotjob.cn/SU621d83d4bef57c221e5c9d8c/pb/social.html', 'official', 'hotjob', 'http', 'private', '银行', '中信银行信用卡中心（银行，probe live 探活 在华 84 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU621d83d4bef57c221e5c9d8c/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '易方达基金', 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/social.html', 'official', 'hotjob', 'http', 'private', '基金·资管', '易方达基金（基金·资管，probe live 探活 在华 124 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '易方达基金 实习', 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/interns.html', 'official', 'hotjob', 'http', 'private', '基金·资管', '易方达基金 实习（基金·资管，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/interns.html');
