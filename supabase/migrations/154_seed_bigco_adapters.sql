-- 154 — 缺失大厂专用 adapter（2026-06-19 live 验证）。
-- 每个可用源均已从公开招聘页实抓到真实在华岗位，并验证逐岗详情页可渲染标题与正文。
-- 顺丰未入库：campus 站强制短信登录；旧社招域超时；job.sf-express.com TLS/HTTP2 失败。

-- 美团：升级 153 的 company_spa 探路源。公开 getJobList 可直连，详情页按 jobUnionId 稳定打开。
update sources
set adapter_name = 'meituan',
    crawl_method = 'http',
    notes = '美团（2026-06-19 live 验证：公开 getJobList，3079 岗；逐岗 detail?jobUnionId= 可渲染正文）'
where source_url = 'https://zhaopin.meituan.com/web/position';

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '美团 Meituan', 'https://zhaopin.meituan.com/web/position', 'official', 'meituan', 'http', 'private', '本地生活/互联网', '美团（2026-06-19 live 验证：公开 getJobList，3079 岗；逐岗 detail?jobUnionId= 可渲染正文）'
where not exists (select 1 from sources where source_url = 'https://zhaopin.meituan.com/web/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '快手 Kuaishou', 'https://zhaopin.kuaishou.cn/#/official/social/?workLocationCode=domestic', 'official', 'kuaishou', 'playwright', 'private', '短视频/互联网', '快手（2026-06-19 live 验证：浏览器签名 open/positions/simple，1487 个国内社招；逐岗 hash 详情页）'
where not exists (select 1 from sources where source_url = 'https://zhaopin.kuaishou.cn/#/official/social/?workLocationCode=domestic');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '哔哩哔哩 bilibili', 'https://jobs.bilibili.com/social/positions', 'official', 'bilibili', 'http', 'private', '视频社区/互联网', '哔哩哔哩（2026-06-19 live 验证：匿名 CSRF + positionList，525 个社招；逐岗 /social/positions/{id}）'
where not exists (select 1 from sources where source_url = 'https://jobs.bilibili.com/social/positions');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '拼多多 Pinduoduo', 'https://careers.pddglobalhr.com/campus/grad', 'official', 'pinduoduo', 'http', 'private', '电商/互联网', '拼多多（2026-06-19 live 验证：公开 position/list，27 个 2026/2027 届校招；逐岗 detail?positionId=）'
where not exists (select 1 from sources where source_url = 'https://careers.pddglobalhr.com/campus/grad');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'vivo', 'https://hr.vivo.com/jobs', 'official', 'vivo', 'http', 'private', '手机/智能终端', 'vivo（2026-06-19 live 验证：公开 portal/page，709 个社招；逐岗 job-detail?_irjc=&_irjid=）'
where not exists (select 1 from sources where source_url = 'https://hr.vivo.com/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '比亚迪 BYD', 'https://job.byd.com/portal/pc/#/social/socialMainPageSocial', 'official', 'byd', 'playwright', 'private', '新能源汽车/制造', '比亚迪（2026-06-19 live 验证：公开 queryList 2163 岗；浏览器点击捕获前端生成的加密逐岗详情 URL）'
where not exists (select 1 from sources where source_url = 'https://job.byd.com/portal/pc/#/social/socialMainPageSocial');
