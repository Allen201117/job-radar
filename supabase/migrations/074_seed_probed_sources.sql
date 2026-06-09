-- 074 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '流利说 LAIX', 'https://app.mokahr.com/campus_apply/liulishuo/2402', 'official', 'moka', 'playwright', 'private', '教育·AI', '流利说 LAIX（教育·AI，probe live 探活 1 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/liulishuo/2402');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中微公司 AMEC', 'https://app.mokahr.com/campus_apply/amec/4362', 'official', 'moka', 'playwright', 'private', '半导体设备', '中微公司 AMEC（半导体设备，probe live 探活 在华 29 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/amec/4362');
