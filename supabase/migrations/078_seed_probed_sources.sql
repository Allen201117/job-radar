-- 078 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'SHEIN', 'https://app.mokahr.com/campus-recruitment/shein/2932', 'official', 'moka', 'playwright', 'private', '跨境电商', 'SHEIN（跨境电商，probe live 探活 在华 27 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/shein/2932');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '好未来 TAL', 'https://app.mokahr.com/campus-recruitment/tal/146099', 'official', 'moka', 'playwright', 'private', '教育', '好未来 TAL（教育，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐 Sohu', 'https://app.mokahr.com/campus_apply/sohu/5682', 'official', 'moka', 'playwright', 'private', '互联网', '搜狐 Sohu（互联网，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/sohu/5682');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '虎牙直播 Huya', 'https://app.mokahr.com/campus_apply/huya/4112', 'official', 'moka', 'playwright', 'private', '直播', '虎牙直播 Huya（直播，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/huya/4112');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '乐元素 Happy Elements', 'https://app.mokahr.com/campus_apply/leyuansu/2357', 'official', 'moka', 'playwright', 'private', '游戏', '乐元素 Happy Elements（游戏，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/leyuansu/2357');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐畅游 Changyou', 'https://app.mokahr.com/campus_apply/cyou-inc/42233', 'official', 'moka', 'playwright', 'private', '游戏', '搜狐畅游 Changyou（游戏，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/cyou-inc/42233');
