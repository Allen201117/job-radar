-- 107 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '立讯精密 LUXSHARE', 'https://luxshare.hotjob.cn/wt/LUXSHARE/web/index', 'official', 'wt', 'http', 'private', '电子制造', '立讯精密 LUXSHARE（电子制造，probe live 探活 在华 82 岗）'
where not exists (select 1 from sources where source_url = 'https://luxshare.hotjob.cn/wt/LUXSHARE/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安踏 ANTA', 'https://app.mokahr.com/campus-recruitment/antahr/142914', 'official', 'moka', 'playwright', 'private', '消费·运动', '安踏 ANTA（消费·运动，probe live 探活 63 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/antahr/142914');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '申洲国际 Shenzhou', 'https://shenzhou.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '消费·纺织', '申洲国际 Shenzhou（消费·纺织，probe live 探活 23 岗）'
where not exists (select 1 from sources where source_url = 'https://shenzhou.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '农夫山泉 养生堂', 'https://app.mokahr.com/campus-recruitment/yst/68367', 'official', 'moka', 'playwright', 'private', '消费·饮料', '农夫山泉 养生堂（消费·饮料，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/yst/68367');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '天合光能 Trina', 'https://app.mokahr.com/apply/trinasolar/39871', 'official', 'moka', 'playwright', 'private', '光伏', '天合光能 Trina（光伏，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/trinasolar/39871');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阳光电源 Sungrow', 'https://app.mokahr.com/campus-recruitment/sungrow/94416', 'official', 'moka', 'playwright', 'private', '光伏·储能', '阳光电源 Sungrow（光伏·储能，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/sungrow/94416');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '滴滴出行 DiDi', 'https://app.mokahr.com/apply/didiglobal/6222', 'official', 'moka', 'playwright', 'private', '互联网·出行', '滴滴出行 DiDi（互联网·出行，probe live 探活 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/didiglobal/6222');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东方财富', 'https://app.mokahr.com/campus-recruitment/eastmoney/57971', 'official', 'moka', 'playwright', 'private', '金融科技·券商', '东方财富（金融科技·券商，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/eastmoney/57971');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新城控股 Seazen', 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/social.html', 'official', 'hotjob', 'http', 'private', '房地产', '新城控股 Seazen（房地产，probe live 探活 200 岗）'
where not exists (select 1 from sources where source_url = 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新城控股 Seazen 校招', 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/school.html', 'official', 'hotjob', 'http', 'private', '房地产', '新城控股 Seazen 校招（房地产，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新城控股 Seazen 实习', 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/interns.html', 'official', 'hotjob', 'http', 'private', '房地产', '新城控股 Seazen 实习（房地产，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/interns.html');
