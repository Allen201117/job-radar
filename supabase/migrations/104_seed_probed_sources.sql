-- 104 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国交建 校招', 'https://ccccltd.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '建筑工程·央企', '中国交建 校招（建筑工程·央企，probe live 探活 在华 600 岗）'
where not exists (select 1 from sources where source_url = 'https://ccccltd.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天集团 校招', 'https://haitian.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '制造·注塑机', '海天集团 校招（制造·注塑机，probe live 探活 在华 62 岗）'
where not exists (select 1 from sources where source_url = 'https://haitian.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国外运 校招', 'https://sinotrans.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '物流·央企', '中国外运 校招（物流·央企，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://sinotrans.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '曙光信息产业 校招', 'https://sugon.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '信创·服务器', '曙光信息产业 校招（信创·服务器，probe live 探活 在华 20 岗）'
where not exists (select 1 from sources where source_url = 'https://sugon.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国人民保险 校招', 'https://picc.zhiye.com/campus', 'official', 'beisen', 'playwright', 'private', '金融·保险', '中国人民保险 校招（金融·保险，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://picc.zhiye.com/campus');
