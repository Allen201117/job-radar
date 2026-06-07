-- 050 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '麦格纳 Magna', 'https://magna.wd3.myworkdayjobs.com/wday/cxs/magna/Magna/jobs', 'official', 'workday', 'http', 'foreign', '汽车零部件', '麦格纳 Magna（汽车零部件，probe live 探活 在华 36 岗）'
where not exists (select 1 from sources where source_url = 'https://magna.wd3.myworkdayjobs.com/wday/cxs/magna/Magna/jobs');
