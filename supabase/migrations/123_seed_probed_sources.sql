-- 123 — 扩源（subagent 自建门户扫描成果，全 live 核验 + 张冠李戴铁律把关）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。
-- 携程=新 adapter ctrip（careers.ctrip.com getJobAd 公开接口零浏览器，hash 路由详情页，
--   质量门已适配 SPA hash 路由：path='/' 时用 fragment 当有效路径）；
-- 其余 7 家落在已支持平台（beisen/moka，含自定义域），均用真实 adapter live 抓出岗位核验。
-- 张冠李戴核正：微博 slug=sina 实为「新浪集团」（title+欢迎加入新浪 实证，微博系其子公司）；
--   猿辅导 slug=fenbi 经核 title=「猿辅导集团」+斑马/飞象星球产品线，确为猿辅导（非粉笔），保留。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '携程', 'https://careers.ctrip.com/', 'official', 'ctrip', 'http', 'private', '在线旅游', '携程集团（OTA，自建门户 getJobAd 零浏览器，live 全量 721 岗：社613/校82/实26）'
where not exists (select 1 from sources where source_url = 'https://careers.ctrip.com/');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '科大讯飞', 'https://iflytek.zhiye.com/social/jobs', 'official', 'beisen', 'playwright', 'private', '人工智能', '科大讯飞（AI语音，beisen，BeisenAdapter live 抓出 600 岗，jd=/social/detail?jobAdId=）'
where not exists (select 1 from sources where source_url = 'https://iflytek.zhiye.com/social/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '唯品会', 'https://app-tc.mokahr.com/social-recruitment/vipshophr/10038', 'official', 'moka', 'playwright', 'private', '电商', '唯品会（特卖电商，moka 自定义域 app-tc，MokaAdapter live 抓出 141 岗）'
where not exists (select 1 from sources where source_url = 'https://app-tc.mokahr.com/social-recruitment/vipshophr/10038');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '58同城', 'https://jobs.58.com/social-recruitment/58/150952', 'official', 'moka', 'playwright', 'private', '互联网', '58同城（生活服务平台，moka 自定义域 jobs.58.com，MokaAdapter live 抓出 475 岗）'
where not exists (select 1 from sources where source_url = 'https://jobs.58.com/social-recruitment/58/150952');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '旷视科技', 'https://app.mokahr.com/social-recruitment/megviihr/38641', 'official', 'moka', 'playwright', 'private', '人工智能', '旷视科技MEGVII（AI视觉，moka，MokaAdapter live 抓出 5 岗，title 核验）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/megviihr/38641');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '新浪集团', 'https://app.mokahr.com/social-recruitment/sina/43535', 'official', 'moka', 'playwright', 'private', '互联网', '新浪集团（含新浪网/微博，moka，slug=sina，title=新浪集团 核验；原 subagent 标微博已核正）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/sina/43535');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '作业帮', 'https://app.mokahr.com/social-recruitment/zuoyebang/150144', 'official', 'moka', 'playwright', 'private', '教育科技', '作业帮（在线教育，moka，title=作业帮招聘官网 核验）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/zuoyebang/150144');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '猿辅导', 'https://app.mokahr.com/social-recruitment/fenbi/45505', 'official', 'moka', 'playwright', 'private', '教育科技', '猿辅导集团（在线教育，moka，slug=fenbi 经核 title=猿辅导集团+斑马/飞象星球 实证非粉笔）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/social-recruitment/fenbi/45505');
