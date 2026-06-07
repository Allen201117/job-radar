-- 057 — 国内500强扩源（北森，长安汽车；live 验证）
-- crawl_method=playwright，segment='private'(民营车企)+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '长安汽车 Changan', 'https://changan.zhiye.com/jobs', 'official', 'beisen', 'playwright', 'private', '汽车',
       '长安汽车（汽车，北森 zhiye，详情 /jobs/detail?jobAdId=，live 80 岗）'
where not exists (select 1 from sources where source_url = 'https://changan.zhiye.com/jobs');
