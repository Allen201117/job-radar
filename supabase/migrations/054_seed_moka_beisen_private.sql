-- 054 — 国内私企扩源批3（Moka + 北森，渲染/拦截抓取，live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '完美世界 Perfect World', 'https://app.mokahr.com/campus-recruitment/pwrd/140155', 'official', 'moka', 'playwright', 'private', '游戏',
       '完美世界（游戏，Moka 渲染 DOM，live 29 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus-recruitment/pwrd/140155');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '知乎 Zhihu', 'https://app.mokahr.com/apply/zhihu/3819', 'official', 'moka', 'playwright', 'private', '互联网·内容',
       '知乎（互联网·内容，Moka 渲染 DOM，live 验证）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/apply/zhihu/3819');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '远景能源 Envision', 'https://app.mokahr.com/campus_apply/envisiongroup/43123', 'official', 'moka', 'playwright', 'private', '新能源',
       '远景能源（新能源，Moka 渲染 DOM，live 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/envisiongroup/43123');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '搜狐畅游 Changyou', 'https://app.mokahr.com/campus_apply/cyou-inc/42233', 'official', 'moka', 'playwright', 'private', '游戏',
       '搜狐畅游（游戏，Moka 渲染 DOM，live 30 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/cyou-inc/42233');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '猿辅导 Yuanfudao', 'https://app.mokahr.com/campus_apply/fenbi/28', 'official', 'moka', 'playwright', 'private', '教育',
       '猿辅导（教育，Moka 渲染 DOM，live 验证）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/fenbi/28');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '作业帮 Zuoyebang', 'https://app.mokahr.com/social-recruitment/zuoyebang/41328', 'official', 'moka', 'playwright', 'private', '教育',
       '作业帮（教育，Moka 渲染 DOM，live 38 岗）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zuoyebang/41328');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '泡泡玛特 POP MART', 'https://popmart.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '潮玩',
       '泡泡玛特（潮玩，北森 zhiye 拦截，live 80 岗）'
where not exists (select 1 from sources where source_url = 'https://popmart.zhiye.com/social/jobs');
