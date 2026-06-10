-- 126 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中核集团', 'https://cnnc.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '核能', '中核集团（核能，probe live 探活 10 岗）'
where not exists (select 1 from sources where source_url = 'https://cnnc.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '明略科技', 'https://mininglamp.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'AI', '明略科技（AI，probe live 探活 22 岗）'
where not exists (select 1 from sources where source_url = 'https://mininglamp.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '北汽集团', 'https://baicgroup.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '汽车', '北汽集团（汽车，probe live 探活 117 岗）'
where not exists (select 1 from sources where source_url = 'https://baicgroup.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '摩尔线程', 'https://mthreads.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', 'AI芯片', '摩尔线程（AI芯片，probe live 探活 159 岗）'
where not exists (select 1 from sources where source_url = 'https://mthreads.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '摩尔线程', 'https://mthreads.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', 'AI芯片', '摩尔线程（AI芯片，probe live 探活 66 岗）'
where not exists (select 1 from sources where source_url = 'https://mthreads.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金域医学', 'https://kingmed.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '医检', '金域医学（医检，probe live 探活 29 岗）'
where not exists (select 1 from sources where source_url = 'https://kingmed.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金域医学', 'https://kingmed.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '医检', '金域医学（医检，probe live 探活 43 岗）'
where not exists (select 1 from sources where source_url = 'https://kingmed.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '诺禾致源', 'https://novogene.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '基因', '诺禾致源（基因，probe live 探活 43 岗）'
where not exists (select 1 from sources where source_url = 'https://novogene.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华大基因', 'https://genomics.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '基因', '华大基因（基因，probe live 探活 600 岗）'
where not exists (select 1 from sources where source_url = 'https://genomics.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华大基因', 'https://genomics.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '基因', '华大基因（基因，probe live 探活 92 岗）'
where not exists (select 1 from sources where source_url = 'https://genomics.zhiye.com/campus');
