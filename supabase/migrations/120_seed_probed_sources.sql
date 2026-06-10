-- 120 — 扩源（阿里巴巴集团 13 个 BU 招聘门户，新通用 adapter=alibaba，live 全量验证 ~3990 岗）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。
-- 阿里各业务集团共用同一套招聘 SPA（白标多域）：POST {host}/position/search 匿名可调
-- （XSRF cookie），description/requirement 自带 JD 正文；详情深链
-- {host}/off-campus/position-detail?lang=zh&positionId={id} 已 13 域逐一 render-verify 过质量门。
-- 注意：集团目录域 talent.alibaba.com / talent.freshippo.com 的 detail 路由不渲染（回落导航页），
-- 故不入库；盒马无独立可渲染门户，暂记红线。阿里健康 careers.alihealth.cn detail 渲染失败，不入。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '淘天集团', 'https://talent.taotian.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '互联网·电商', '淘天集团（淘宝天猫，阿里 BU 门户，live 707/715 岗，品类+城市分片）'
where not exists (select 1 from sources where source_url = 'https://talent.taotian.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿里云', 'https://careers.aliyun.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '云计算', '阿里云（云计算，阿里 BU 门户，live 820/822 岗）'
where not exists (select 1 from sources where source_url = 'https://careers.aliyun.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿里巴巴控股集团', 'https://talent-holding.alibaba.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '互联网', '阿里巴巴控股集团（集团职能/技术中台，live 510 岗）'
where not exists (select 1 from sources where source_url = 'https://talent-holding.alibaba.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '饿了么', 'https://talent.ele.me/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '本地生活', '饿了么·淘宝闪购（本地生活，阿里 BU 门户，live 300 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.ele.me/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '高德地图', 'https://talent.amap.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '地图出行', '高德地图（出行科技，阿里 BU 门户，live 229 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.amap.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '虎鲸文娱', 'https://jobs.hujing-dme.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '文娱', '虎鲸文娱（优酷/大麦等，阿里 BU 门户，live 199 岗）'
where not exists (select 1 from sources where source_url = 'https://jobs.hujing-dme.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿里国际数字商业', 'https://aidc-jobs.alibaba.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '跨境电商', '阿里国际AIDC（速卖通/Lazada 等，live 166 岗）'
where not exists (select 1 from sources where source_url = 'https://aidc-jobs.alibaba.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '灵犀互娱', 'https://talent.lingxigames.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '游戏', '灵犀互娱（阿里游戏，live 143 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.lingxigames.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '菜鸟', 'https://cn-jobs.cainiao.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '物流科技', '菜鸟集团（智慧物流，阿里 BU 门户，live 133 岗）'
where not exists (select 1 from sources where source_url = 'https://cn-jobs.cainiao.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '钉钉', 'https://talent.dingtalk.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '协同办公', '钉钉（企业协同，阿里 BU 门户，live 113 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.dingtalk.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '通义', 'https://careers-tongyi.alibaba.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', 'AI大模型', '通义（阿里大模型，live 65 岗）'
where not exists (select 1 from sources where source_url = 'https://careers-tongyi.alibaba.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '菜鸟驿站', 'https://talent-post.alibaba.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '物流末端', '菜鸟驿站（社区物流，live 53 岗）'
where not exists (select 1 from sources where source_url = 'https://talent-post.alibaba.com/off-campus/position-list?lang=zh');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '亚博科技', 'https://talent.agtech.com/off-campus/position-list?lang=zh', 'official', 'alibaba', 'http', 'private', '彩票科技', '亚博科技AGTech（阿里系彩票科技，live 7 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.agtech.com/off-campus/position-list?lang=zh');
