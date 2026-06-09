-- 099 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国电信国际', 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/social.html', 'official', 'hotjob', 'http', 'private', '电信·央企', '中国电信国际（电信·央企，probe live 探活 在华 22 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/social.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国电信国际 校招', 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/school.html', 'official', 'hotjob', 'http', 'private', '电信·央企', '中国电信国际 校招（电信·央企，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/school.html');
