-- 056 — 国内私企扩源批5（北森，详情路由发现增强后打通；live 验证）
-- crawl_method=playwright（拦截 GetJobAdPageList + 探测详情路由），segment='private'+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '迈瑞医疗 Mindray', 'https://mindray.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '医疗器械',
       '迈瑞医疗（医疗器械，北森 zhiye，详情路由点击捕获，live 80 岗）'
where not exists (select 1 from sources where source_url = 'https://mindray.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '汇川技术 Inovance', 'https://inovance.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright', 'private', '工业自动化',
       '汇川技术（工业自动化，北森 zhiye，live 80 岗）'
where not exists (select 1 from sources where source_url = 'https://inovance.zhiye.com/campus/jobs');
