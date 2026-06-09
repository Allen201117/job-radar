-- 069 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '推想医疗 InferVision', 'https://app.mokahr.com/apply/infervision/2064', 'official', 'moka', 'playwright', 'private', '医疗AI', '推想医疗 InferVision（医疗AI，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/infervision/2064');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '掌趣科技 Playcrab', 'https://app.mokahr.com/apply/playcrab/24831', 'official', 'moka', 'playwright', 'private', '游戏', '掌趣科技 Playcrab（游戏，probe live 探活 4 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/playcrab/24831');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '安谋科技 Arm China', 'https://app.mokahr.com/apply/armchina/885', 'official', 'moka', 'playwright', 'private', '半导体', '安谋科技 Arm China（半导体，probe live 探活 在华 16 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/armchina/885');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '腾讯微保 WeSure', 'https://app-tc.mokahr.com/apply/wesure/6018', 'official', 'moka', 'playwright', 'private', '保险科技', '腾讯微保 WeSure（保险科技，probe live 探活 在华 4 岗）'
where not exists (select 1 from sources where source_url = 'https://app-tc.mokahr.com/apply/wesure/6018');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '盛趣游戏 Shengqu', 'https://app.mokahr.com/campus_apply/shengqu/4078', 'official', 'moka', 'playwright', 'private', '游戏', '盛趣游戏 Shengqu（游戏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/shengqu/4078');
