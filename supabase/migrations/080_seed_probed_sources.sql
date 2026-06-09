-- 080 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '紫光同芯 Tsinghua IC', 'https://app.mokahr.com/social-recruitment/tsinghuaic/39655', 'official', 'moka', 'playwright', 'private', '半导体', '紫光同芯 Tsinghua IC（半导体，probe live 探活 21 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/tsinghuaic/39655');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '芯粤能 Ascenpower', 'https://app.mokahr.com/campus-recruitment/ascenpower/142952', 'official', 'moka', 'playwright', 'private', '半导体', '芯粤能 Ascenpower（半导体，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/ascenpower/142952');
