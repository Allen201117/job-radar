-- 062 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '公牛集团 GONGNIU', 'https://gongniu.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '五金电工·消费', '公牛集团 GONGNIU（五金电工·消费，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://gongniu.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '360集团', 'https://360campus.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'private', '互联网·安全', '360集团（互联网·安全，probe live 探活 在华 48 岗）'
where not exists (select 1 from sources where source_url = 'https://360campus.zhiye.com/campus/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中核集团 CNNC', 'https://cnnc.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'soe', '核工业·能源', '中核集团 CNNC（核工业·能源，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://cnnc.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '深业集团 SHENYE', 'https://shenyejituan.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'soe', '综合·地产·国资', '深业集团 SHENYE（综合·地产·国资，probe live 探活 5 岗）'
where not exists (select 1 from sources where source_url = 'https://shenyejituan.zhiye.com/campus/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国东方资产 COAMC', 'https://coamc.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'soe', '金融·资产管理', '中国东方资产 COAMC（金融·资产管理，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://coamc.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '上实集团 SIIC', 'https://siic.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'soe', '综合·实业·国资', '上实集团 SIIC（综合·实业·国资，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://siic.zhiye.com/campus/jobs');
