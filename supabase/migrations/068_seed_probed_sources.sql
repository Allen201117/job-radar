-- 068 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '万科 Vanke', 'https://app.mokahr.com/apply/vanke/36266', 'official', 'moka', 'playwright', 'private', '地产', '万科 Vanke（地产，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/vanke/36266');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '巨人网络 Giant', 'https://app.mokahr.com/apply/ztgame/37485', 'official', 'moka', 'playwright', 'private', '游戏', '巨人网络 Giant（游戏，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/ztgame/37485');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '广联达 Glodon', 'https://app.mokahr.com/apply/glodon/1751', 'official', 'moka', 'playwright', 'private', '建筑软件', '广联达 Glodon（建筑软件，probe live 探活 26 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/glodon/1751');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '同盾科技 Tongdun', 'https://app.mokahr.com/apply/tongdun/29005', 'official', 'moka', 'playwright', 'private', '金融科技', '同盾科技 Tongdun（金融科技，probe live 探活 在华 11 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/tongdun/29005');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '真格基金 ZhenFund', 'https://app.mokahr.com/apply/zhenfund/39989', 'official', 'moka', 'playwright', 'private', '创投', '真格基金 ZhenFund（创投，probe live 探活 2 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/zhenfund/39989');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '特斯拉中国 Tesla', 'https://app.mokahr.com/apply/tesla/46129', 'official', 'moka', 'playwright', 'foreign', '汽车·新能源', '特斯拉中国 Tesla（汽车·新能源，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/tesla/46129');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '极智嘉 Geek+', 'https://app.mokahr.com/apply/geekplus/5030', 'official', 'moka', 'playwright', 'private', '物流机器人', '极智嘉 Geek+（物流机器人，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/geekplus/5030');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MAIA ACTIVE', 'https://app.mokahr.com/apply/maia/21988', 'official', 'moka', 'playwright', 'private', '运动服饰', 'MAIA ACTIVE（运动服饰，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/maia/21988');
