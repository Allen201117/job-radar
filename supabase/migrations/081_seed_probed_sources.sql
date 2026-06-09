-- 081 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '唯品会 VIP.com', 'https://app-tc.mokahr.com/social-recruitment/vipshophr/10038', 'official', 'moka', 'playwright', 'private', '电商', '唯品会 VIP.com（电商，probe live 探活 在华 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app-tc.mokahr.com/social-recruitment/vipshophr/10038');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '月之暗面 Kimi', 'https://app.mokahr.com/apply/moonshot/148506', 'official', 'moka', 'playwright', 'private', 'AI大模型', '月之暗面 Kimi（AI大模型，probe live 探活 在华 18 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/moonshot/148506');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '斗鱼直播 Douyu', 'https://app.mokahr.com/apply/douyu/7622', 'official', 'moka', 'playwright', 'private', '直播', '斗鱼直播 Douyu（直播，probe live 探活 15 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/douyu/7622');
