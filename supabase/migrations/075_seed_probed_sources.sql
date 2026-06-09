-- 075 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '知乎 Zhihu', 'https://app.mokahr.com/apply/zhihu/3819', 'official', 'moka', 'playwright', 'private', '互联网·社区', '知乎 Zhihu（互联网·社区，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/zhihu/3819');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '第四范式 4Paradigm', 'https://app.mokahr.com/apply/4paradigm/5072', 'official', 'moka', 'playwright', 'private', 'AI', '第四范式 4Paradigm（AI，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/4paradigm/5072');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '灵感游戏 Inspire Games', 'https://app.mokahr.com/social-recruitment/inspiregames/144680', 'official', 'moka', 'playwright', 'private', '游戏', '灵感游戏 Inspire Games（游戏，probe live 探活 在华 27 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/inspiregames/144680');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博乐科技 Bole Games', 'https://app.mokahr.com/social-recruitment/bolegames/37642', 'official', 'moka', 'playwright', 'private', '游戏', '博乐科技 Bole Games（游戏，probe live 探活 20 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/bolegames/37642');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '向日葵远程 Oray', 'https://app.mokahr.com/social-recruitment/oray/42974', 'official', 'moka', 'playwright', 'private', '软件', '向日葵远程 Oray（软件，probe live 探活 9 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/oray/42974');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三只松鼠 Three Squirrels', 'https://app.mokahr.com/campus_apply/3songshu/457', 'official', 'moka', 'playwright', 'private', '消费·食品', '三只松鼠 Three Squirrels（消费·食品，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/3songshu/457');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '雪球 Xueqiu', 'https://app.mokahr.com/campus_apply/xueqiu/3590', 'official', 'moka', 'playwright', 'private', '金融科技', '雪球 Xueqiu（金融科技，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/xueqiu/3590');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Shopee', 'https://app.mokahr.com/campus_apply/shopee/2962', 'official', 'moka', 'playwright', 'private', '互联网·电商', 'Shopee（互联网·电商，probe live 探活 3 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/shopee/2962');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '远景科技 Envision', 'https://app.mokahr.com/campus_apply/envisiongroup/43123', 'official', 'moka', 'playwright', 'private', '新能源', '远景科技 Envision（新能源，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/envisiongroup/43123');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '幻方量化 High-Flyer', 'https://app.mokahr.com/social-recruitment/high-flyer/140576', 'official', 'moka', 'playwright', 'private', '量化投资', '幻方量化 High-Flyer（量化投资，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/high-flyer/140576');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '光子跳动 Photon Dance', 'https://app.mokahr.com/social-recruitment/guangzi/142129', 'official', 'moka', 'playwright', 'private', '智能硬件', '光子跳动 Photon Dance（智能硬件，probe live 探活 24 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/guangzi/142129');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Meshy', 'https://app.mokahr.com/apply/taichi/148086', 'official', 'moka', 'playwright', 'private', 'AI·3D', 'Meshy（AI·3D，probe live 探活 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/taichi/148086');
