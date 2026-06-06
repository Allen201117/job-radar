-- 031 — 本土扩源（北森/zhiye 续 3）：逐租户详情路由 render 验证通过的新源
-- beisen adapter 自动探测详情路由（query 恒 ?jobAdId={Id}，path 因租户而异），缓存于 crawler/beisen_routes.json。
-- 锐明技术 route=/Campus/detail、横店集团 route=/campus/detail，均 render 验证。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '锐明技术', 'https://streamax.zhiye.com/Campus', 'official', 'beisen', 'playwright',
       '锐明技术（智能硬件·车载安防，北森 zhiye，详情路由 /Campus/detail 已 render 验证）'
where not exists (select 1 from sources where source_url = 'https://streamax.zhiye.com/Campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '横店集团', 'https://hengdian-ie.zhiye.com/campus/jobs', 'official', 'beisen', 'playwright',
       '横店集团（影视·制造，北森 zhiye，详情路由 /campus/detail 已 render 验证）'
where not exists (select 1 from sources where source_url = 'https://hengdian-ie.zhiye.com/campus/jobs');
