-- 132 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '卡夫亨氏（中国）食品有限公司', 'https://kraftheinz.hotjob.cn/wt/kraftheinz/web/index', 'official', 'wt', 'http', 'private', '食品饮料', '卡夫亨氏（中国）食品有限公司（食品饮料，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://kraftheinz.hotjob.cn/wt/kraftheinz/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奥迪汽车（中国）业务有限公司', 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/social.html', 'official', 'hotjob', 'http', 'private', '汽车', '奥迪汽车（中国）业务有限公司（汽车，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奥迪汽车（中国）业务有限公司', 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/school.html', 'official', 'hotjob', 'http', 'private', '汽车', '奥迪汽车（中国）业务有限公司（汽车，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奥迪汽车（中国）业务有限公司', 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/interns.html', 'official', 'hotjob', 'http', 'private', '汽车', '奥迪汽车（中国）业务有限公司（汽车，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://audi.hotjob.cn/SU616d95e3bef57c1af3dc6bbb/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '旭辉控股集团有限公司', 'https://cifi.hotjob.cn/wt/cifi/web/index', 'official', 'wt', 'http', 'private', '地产/住宅开发', '旭辉控股集团有限公司（地产/住宅开发，probe live 探活 在华 263 岗）'
where not exists (select 1 from sources where source_url = 'https://cifi.hotjob.cn/wt/cifi/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '地素时尚股份有限公司', 'https://dazzle-fashion.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '高端女装', '地素时尚股份有限公司（高端女装，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://dazzle-fashion.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '七匹狼实业股份有限公司', 'https://septwolves.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '男装/休闲服装', '七匹狼实业股份有限公司（男装/休闲服装，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://septwolves.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润水泥控股有限公司', 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/social.html', 'official', 'hotjob', 'http', 'private', '水泥', '华润水泥控股有限公司（水泥，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润水泥控股有限公司', 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/school.html', 'official', 'hotjob', 'http', 'private', '水泥', '华润水泥控股有限公司（水泥，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华润水泥控股有限公司', 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/interns.html', 'official', 'hotjob', 'http', 'private', '水泥', '华润水泥控股有限公司（水泥，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://crcement.hotjob.cn/SU6116236b2f9d24229ef9364c/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '旭辉控股（集团）有限公司', 'https://cifigroup.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '物业管理/代建', '旭辉控股（集团）有限公司（物业管理/代建，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://cifigroup.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '郑州银行股份有限公司', 'https://zzbank.hotjob.cn/SU64f952b41eb8051fabaed066/pb/social.html', 'official', 'hotjob', 'http', 'private', '城商行', '郑州银行股份有限公司（城商行，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://zzbank.hotjob.cn/SU64f952b41eb8051fabaed066/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '特变电工衡阳变压器有限公司', 'https://tbea.hotjob.cn/wt/TBEA/web/index', 'official', 'wt', 'http', 'private', '变压器/输变电成套/新能源装备', '特变电工衡阳变压器有限公司（变压器/输变电成套/新能源装备，probe live 探活 在华 1532 岗）'
where not exists (select 1 from sources where source_url = 'https://tbea.hotjob.cn/wt/TBEA/web/index');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药集团口腔护理事业部（云南白药牙膏）', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html', 'official', 'hotjob', 'http', 'private', '口腔护理', '云南白药集团口腔护理事业部（云南白药牙膏）（口腔护理，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药集团口腔护理事业部（云南白药牙膏）', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html', 'official', 'hotjob', 'http', 'private', '口腔护理', '云南白药集团口腔护理事业部（云南白药牙膏）（口腔护理，probe live 探活 在华 19 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/school.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '云南白药集团口腔护理事业部（云南白药牙膏）', 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html', 'official', 'hotjob', 'http', 'private', '口腔护理', '云南白药集团口腔护理事业部（云南白药牙膏）（口腔护理，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://ynby.hotjob.cn/SU6136b970bef57c3b638162c4/pb/interns.html');
