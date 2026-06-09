-- 103 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小马智行 Pony.ai', 'https://ponyai.jobs.feishu.cn/ponyai/position', 'official', 'feishu', 'playwright', 'private', '自动驾驶', '小马智行 Pony.ai（自动驾驶，probe live 探活 在华 37 岗）'
where not exists (select 1 from sources where source_url = 'https://ponyai.jobs.feishu.cn/ponyai/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '正浩创新 EcoFlow', 'https://ecoflow.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '储能·消费电子', '正浩创新 EcoFlow（储能·消费电子，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://ecoflow.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '商汤科技 SenseTime', 'https://sensetime.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '人工智能', '商汤科技 SenseTime（人工智能，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sensetime.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '鹰角网络 Hypergryph', 'https://app.mokahr.com/apply/hypergryph/26325', 'official', 'moka', 'playwright', 'private', '游戏', '鹰角网络 Hypergryph（游戏，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/hypergryph/26325');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '李宁 LI-NING', 'https://app.mokahr.com/apply/lining/166080', 'official', 'moka', 'playwright', 'private', '消费·运动服饰', '李宁 LI-NING（消费·运动服饰，probe live 探活 在华 32 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/lining/166080');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小天才 eebbk', 'https://app.mokahr.com/campus_apply/eebbk/37594', 'official', 'moka', 'playwright', 'private', '消费电子·教育电子', '小天才 eebbk（消费电子·教育电子，probe live 探活 在华 23 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/eebbk/37594');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '锐捷网络 Ruijie', 'https://app.mokahr.com/apply/ruijie/26518', 'official', 'moka', 'playwright', 'private', '网络设备', '锐捷网络 Ruijie（网络设备，probe live 探活 在华 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/ruijie/26518');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通用技术集团', 'https://genertec.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '综合·央企', '通用技术集团（综合·央企，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://genertec.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国交建', 'https://ccccltd.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '建筑工程·央企', '中国交建（建筑工程·央企，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://ccccltd.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国人民保险', 'https://picc.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '金融·保险', '中国人民保险（金融·保险，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://picc.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海天集团', 'https://haitian.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '制造·注塑机', '海天集团（制造·注塑机，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://haitian.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国外运', 'https://sinotrans.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '物流·央企', '中国外运（物流·央企，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sinotrans.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '曙光信息产业', 'https://sugon.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '信创·服务器', '曙光信息产业（信创·服务器，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://sugon.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '金风科技', 'https://goldwind.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '新能源·风电', '金风科技（新能源·风电，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://goldwind.zhiye.com/social');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '联通数字科技', 'https://unicom.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '通信·央企子公司', '联通数字科技（通信·央企子公司，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://unicom.zhiye.com/social');
