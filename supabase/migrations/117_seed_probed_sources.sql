-- 117 — 扩源（OPPO 校招门户 adapter=oppo，probe live 探活，detail 深链 render-verify 过）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'OPPO', 'https://careers.oppo.com/university/oppo/campus/post?recruitType=Graduate', 'official', 'oppo', 'http', 'private', '消费电子', 'OPPO（消费电子，careers.oppo.com openapi 公开接口，校招/实习渠道，detail 深链 live render-verify 过）'
where not exists (select 1 from sources where source_url = 'https://careers.oppo.com/university/oppo/campus/post?recruitType=Graduate');
