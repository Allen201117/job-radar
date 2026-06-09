-- 113 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通用技术集团', 'https://genertec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '装备', '通用技术集团（装备，probe live 探活 在华 248 岗）'
where not exists (select 1 from sources where source_url = 'https://genertec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通用技术集团', 'https://genertec.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '装备', '通用技术集团（装备，probe live 探活 在华 248 岗）'
where not exists (select 1 from sources where source_url = 'https://genertec.zhiye.com/campus');
