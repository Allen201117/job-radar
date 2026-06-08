-- 066 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '维达', 'https://vinda.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '日化', '维达（日化，probe live 探活 在华 26 岗）'
where not exists (select 1 from sources where source_url = 'https://vinda.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东鹏', 'https://dongpeng.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '建材', '东鹏（建材，probe live 探活 在华 63 岗）'
where not exists (select 1 from sources where source_url = 'https://dongpeng.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '东山精密', 'https://dsbj.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '精密制造', '东山精密（精密制造，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://dsbj.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蜂巢能源', 'https://svolt.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '电池', '蜂巢能源（电池，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://svolt.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新东方 New Oriental', 'https://xdf.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '教育', '新东方 New Oriental（教育，probe live 探活 在华 46 岗）'
where not exists (select 1 from sources where source_url = 'https://xdf.zhiye.com/social/jobs');
