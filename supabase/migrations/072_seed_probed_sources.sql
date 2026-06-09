-- 072 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国钢研科技集团 NCSTEEL', 'https://gangyan.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'soe', '材料·央企', '中国钢研科技集团 NCSTEEL（材料·央企，probe live 探活 在华 57 岗）'
where not exists (select 1 from sources where source_url = 'https://gangyan.zhiye.com/campus/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'BIGO', 'https://app.mokahr.com/apply/bigo/1019', 'official', 'moka', 'playwright', 'private', '直播·社交', 'BIGO（直播·社交，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/bigo/1019');
