-- 070 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '招商局集团 CMHK', 'https://cmhk.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'soe', '综合·央企', '招商局集团 CMHK（综合·央企，probe live 探活 在华 69 岗）'
where not exists (select 1 from sources where source_url = 'https://cmhk.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '积海半导体 GHSMC', 'https://ghsmc.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'private', '半导体', '积海半导体 GHSMC（半导体，probe live 探活 在华 18 岗）'
where not exists (select 1 from sources where source_url = 'https://ghsmc.zhiye.com/campus/jobs');
