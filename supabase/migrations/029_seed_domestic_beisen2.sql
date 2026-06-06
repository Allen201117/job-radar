-- 029 — 本土扩源（北森/zhiye 续）：逐租户详情路由自动探测 + render 验证通过的源
-- beisen adapter 升级：详情路由 query 恒为 ?jobAdId={Id}，path 因租户而异，fetch 时 render-verify
-- 候选 path 自动捕获真路由（chinalife=/custom/zwxq、杰瑞/爱慕=/campus/detail），缓存于 crawler/beisen_routes.json。
-- 中国人寿已在 027；此处新增杰瑞、爱慕。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '杰瑞集团', 'https://jereh.zhiye.com/campus', 'official', 'beisen', 'playwright',
       '杰瑞集团（油气装备·制造，北森 zhiye，详情路由 /campus/detail 已 render 验证）'
where not exists (select 1 from sources where source_url = 'https://jereh.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '爱慕集团', 'https://aimer.zhiye.com/campus', 'official', 'beisen', 'playwright',
       '爱慕集团（消费·服装，北森 zhiye，详情路由 /campus/detail 已 render 验证）'
where not exists (select 1 from sources where source_url = 'https://aimer.zhiye.com/campus');
