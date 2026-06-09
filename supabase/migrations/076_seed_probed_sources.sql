-- 076 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '小鹏汽车 XPeng', 'https://xiaopeng.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '新能源车', '小鹏汽车 XPeng（新能源车，probe live 探活 在华 40 岗）'
where not exists (select 1 from sources where source_url = 'https://xiaopeng.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '蔚来 NIO', 'https://nio.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '新能源车', '蔚来 NIO（新能源车，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://nio.jobs.feishu.cn/index/position');
