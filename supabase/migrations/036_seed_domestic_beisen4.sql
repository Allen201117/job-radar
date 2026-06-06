-- 036 — 本土500强扩源（北森/zhiye 续 4）：真实 zhiye.com 招聘页（搜索得到，非猜测），路由 render 验证
-- 三一集团 route=/campus/detail、潍柴集团 route=/custom/detail，缓存于 crawler/beisen_routes.json。
-- Idempotent: guarded by source_url。本土覆盖优先（CLAUDE.md：中国本土 > 外企）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '三一集团', 'https://sany.zhiye.com/campus', 'official', 'beisen', 'playwright',
       '三一集团（工程机械500强，北森 zhiye，详情路由 /campus/detail 已 render 验证）'
where not exists (select 1 from sources where source_url = 'https://sany.zhiye.com/campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '潍柴集团', 'https://weichai.zhiye.com/custom/xiaoyuan', 'official', 'beisen', 'playwright',
       '潍柴集团（动力·装备500强，北森 zhiye，详情路由 /custom/detail 已 render 验证，live 21 岗）'
where not exists (select 1 from sources where source_url = 'https://weichai.zhiye.com/custom/xiaoyuan');
