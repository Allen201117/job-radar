-- 067 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '零一万物 01AI', 'https://01ai.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', 'AI大模型', '零一万物 01AI（AI大模型，probe live 探活 在华 39 岗）'
where not exists (select 1 from sources where source_url = 'https://01ai.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '鹰角网络 Hypergryph', 'https://hypergryph.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '游戏', '鹰角网络 Hypergryph（游戏，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://hypergryph.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江淮汽车 JAC', 'https://jac.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'soe', '汽车', '江淮汽车 JAC（汽车，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://jac.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '江铃汽车 JMC', 'https://jmc.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'soe', '汽车', '江铃汽车 JMC（汽车，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://jmc.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '先导智能 LEAD', 'https://leadchina.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '锂电装备', '先导智能 LEAD（锂电装备，probe live 探活 在华 61 岗）'
where not exists (select 1 from sources where source_url = 'https://leadchina.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '博众精工 Bozhon', 'https://bozhon.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '智能装备', '博众精工 Bozhon（智能装备，probe live 探活 在华 67 岗）'
where not exists (select 1 from sources where source_url = 'https://bozhon.zhiye.com/social/jobs');
