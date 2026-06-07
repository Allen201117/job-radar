-- 058 — 国内私企扩源（飞书招聘，懂车帝；live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '懂车帝 Dcar', 'https://dcar.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '汽车·内容',
       '懂车帝（汽车·内容，字节系，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://dcar.jobs.feishu.cn/index/position');
