-- 130 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市正弦电气股份有限公司', 'https://sinee.hotjob.cn/SU658a367d1c240e6503ec1691/pb/social.html', 'official', 'hotjob', 'http', 'private', '工业驱动/伺服系统', '深圳市正弦电气股份有限公司（工业驱动/伺服系统，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://sinee.hotjob.cn/SU658a367d1c240e6503ec1691/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深圳市正弦电气股份有限公司', 'https://sinee.hotjob.cn/SU658a367d1c240e6503ec1691/pb/school.html', 'official', 'hotjob', 'http', 'private', '工业驱动/伺服系统', '深圳市正弦电气股份有限公司（工业驱动/伺服系统，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sinee.hotjob.cn/SU658a367d1c240e6503ec1691/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '特变电工新能源股份有限公司', 'https://tbea.hotjob.cn/wt/TBEA/web/index', 'official', 'wt', 'http', 'private', '光伏逆变器/变压器', '特变电工新能源股份有限公司（光伏逆变器/变压器，probe live 探活 在华 1531 岗）'
where not exists (select 1 from sources where source_url = 'https://tbea.hotjob.cn/wt/TBEA/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '固德威技术股份有限公司', 'https://goodwe.hotjob.cn/wt/goodwe/web/index', 'official', 'wt', 'http', 'private', '光伏逆变器', '固德威技术股份有限公司（光伏逆变器，probe live 探活 在华 304 岗）'
where not exists (select 1 from sources where source_url = 'https://goodwe.hotjob.cn/wt/goodwe/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '超级猩猩（深圳）健康管理有限公司', 'https://supermonkey.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '运动健身-精品健身工作室', '超级猩猩（深圳）健康管理有限公司（运动健身-精品健身工作室，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://supermonkey.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '麦瑞克科技（广东）有限公司', 'https://merach.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '运动健身-家用健身器械', '麦瑞克科技（广东）有限公司（运动健身-家用健身器械，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://merach.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '武汉华星光电技术有限公司', 'https://csot.hotjob.cn/wt/CSOT/web/index', 'official', 'wt', 'http', 'private', '武汉光谷·AMOLED/LCD面板', '武汉华星光电技术有限公司（武汉光谷·AMOLED/LCD面板，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://csot.hotjob.cn/wt/CSOT/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '厦门艾德生物医药科技股份有限公司', 'https://amoydiagnostics.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '伴随诊断/肿瘤基因检测', '厦门艾德生物医药科技股份有限公司（伴随诊断/肿瘤基因检测，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://amoydiagnostics.jobs.feishu.cn/index/position');
