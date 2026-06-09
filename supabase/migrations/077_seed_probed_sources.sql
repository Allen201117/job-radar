-- 077 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '理想汽车 Li Auto', 'https://li.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '新能源车', '理想汽车 Li Auto（新能源车，probe live 探活 在华 37 岗）'
where not exists (select 1 from sources where source_url = 'https://li.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '途游游戏 Tuyoo', 'https://app.mokahr.com/campus-recruitment/tuyoogame/146219', 'official', 'moka', 'playwright', 'private', '游戏', '途游游戏 Tuyoo（游戏，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tuyoogame/146219');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '驭势科技 UISEE', 'https://app.mokahr.com/campus_apply/yushi/3773', 'official', 'moka', 'playwright', 'private', '自动驾驶', '驭势科技 UISEE（自动驾驶，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/yushi/3773');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '元气森林 Genki Forest', 'https://k11pnjpvz1.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '消费·饮料', '元气森林 Genki Forest（消费·饮料，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://k11pnjpvz1.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '奇安信 QiAnXin', 'https://app.mokahr.com/campus_apply/qianxin/29182', 'official', 'moka', 'playwright', 'private', '网络安全', '奇安信 QiAnXin（网络安全，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/qianxin/29182');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中电信人工智能 China Telecom AI', 'https://app.mokahr.com/campus-recruitment/chinatelecomai/144822', 'official', 'moka', 'playwright', 'private', 'AI', '中电信人工智能 China Telecom AI（AI，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/chinatelecomai/144822');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '悠星网络 Yostar', 'https://app.mokahr.com/social-recruitment/yostar/145292', 'official', 'moka', 'playwright', 'private', '游戏发行', '悠星网络 Yostar（游戏发行，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/yostar/145292');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '鹏景科技 Pengwin', 'https://app.mokahr.com/campus-recruitment/pengwin/145331', 'official', 'moka', 'playwright', 'private', '科技', '鹏景科技 Pengwin（科技，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/pengwin/145331');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '见山科技 Jianshan', 'https://app.mokahr.com/campus-recruitment/jianshankeji/100134', 'official', 'moka', 'playwright', 'private', '科技', '见山科技 Jianshan（科技，probe live 探活 16 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/jianshankeji/100134');
