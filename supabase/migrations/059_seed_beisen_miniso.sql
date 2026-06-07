-- 059 — 国内私企扩源（北森，名创优品；live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '名创优品 MINISO', 'https://miniso.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '零售',
       '名创优品（零售，北森 zhiye，详情路由发现，live 27 岗）'
where not exists (select 1 from sources where source_url = 'https://miniso.zhiye.com/social/jobs');
