-- 255 — 国聘「应届生」校招通道：给已有的国聘社招源各配一条按职位性质筛的兄弟源（2026-09-17）
--
-- 现象：秋招季国内必投 321 家里 123 家 campus_channel=missing，其中 16 家的唯一源是国聘关键词搜索；
-- 国聘关键词搜索单次封顶 400 条、逐岗核验封顶 300，大集团的校招岗被社招挤出窗口（国家电网 / 中国石化
-- 「全部」400 条里应届生就占满 400），列表里 nature_cn=校招 的岗根本进不了库。
-- 修法：adapter 支持 `&nature=115xW5oQ`（= 国聘自己的「应届生」性质码，取自 xiaoyuan.iguopin.com
-- 「应届生职位 → 更多」的真实跳转；列表接口真实请求体 search.nature 是数组），一家一条校招源。
-- `&channel=campus` 只为让 sources.board 派生成 campus（接口不读它）。
-- 归属核验（match / 集团 group_id）与社招源完全相同，不放开任何旁路。
--
-- 每一行都用真实 adapter 端到端探活（CRAWL_DETAIL_CAP=3：列表 → 归属核验 → 逐岗详情 200）通过才写：

--   中国平安: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   中国建筑: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   中国电建: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   泰康保险: 自报 99 岗，核验样本 3 条全部 job_type=校园招聘
--   中公教育: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   国家电网: 自报 400 岗，核验样本 1 条全部 job_type=校园招聘
--   协鑫: 自报 79 岗，核验样本 1 条全部 job_type=校园招聘
--   中国中铁: 自报 12 岗，核验样本 2 条全部 job_type=校园招聘
--   恒力集团: 自报 42 岗，核验样本 2 条全部 job_type=校园招聘
--   中远海运: 自报 126 岗，核验样本 3 条全部 job_type=校园招聘
--   国泰海通: 自报 9 岗，核验样本 3 条全部 job_type=校园招聘
--   中国铁建: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   南方电网: 自报 307 岗，核验样本 3 条全部 job_type=校园招聘
--   中南传媒: 自报 146 岗，核验样本 3 条全部 job_type=校园招聘
--   中国中冶: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   中国能建: 自报 400 岗，核验样本 3 条全部 job_type=校园招聘
--   奔驰: 自报 11 岗，核验样本 3 条全部 job_type=校园招聘
-- 探活未过、刻意不写的（接口返 0 / 归属核验后为空 / 报错）：
--   圆通: reported_total=0 valid=0 campus_typed=0
--   粉笔: reported_total=0 valid=0 campus_typed=0
--   华图教育: reported_total=400 valid=0 campus_typed=0
--   学大教育: reported_total=400 valid=0 campus_typed=0
--   大悦城: reported_total=400 valid=0 campus_typed=0
--   华润置地: reported_total=290 valid=0 campus_typed=0
--   中国石油: reported_total=400 valid=0 campus_typed=0
--   百胜中国: reported_total=94 valid=0 campus_typed=0
--   京东方: reported_total=343 valid=0 campus_typed=0
--   爱尔眼科: reported_total=43 valid=0 campus_typed=0
--   中海油: reported_total=400 valid=0 campus_typed=0

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国平安', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%B9%B3%E5%AE%89&match=%E5%B9%B3%E5%AE%89&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'private', '金融', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%B9%B3%E5%AE%89&match=%E5%B9%B3%E5%AE%89&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国建筑', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%BB%BA%E7%AD%91&match=%E4%B8%AD%E5%BB%BA&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '地产/建筑', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%BB%BA%E7%AD%91&match=%E4%B8%AD%E5%BB%BA&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国电建', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E7%94%B5%E5%BB%BA&match=%E7%94%B5%E5%BB%BA&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '能源/化工', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E7%94%B5%E5%BB%BA&match=%E7%94%B5%E5%BB%BA&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '泰康保险', 'https://www.iguopin.com/job?company=%E6%B3%B0%E5%BA%B7&match=%E6%B3%B0%E5%BA%B7&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '金融', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 99 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E6%B3%B0%E5%BA%B7&match=%E6%B3%B0%E5%BA%B7&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中公教育', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%85%AC%E6%95%99%E8%82%B2&match=%E4%B8%AD%E5%85%AC%E6%95%99%E8%82%B2&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '教育', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%85%AC%E6%95%99%E8%82%B2&match=%E4%B8%AD%E5%85%AC%E6%95%99%E8%82%B2&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '国家电网', 'https://www.iguopin.com/job?company=%E5%9B%BD%E7%BD%91&match=%E5%9B%BD%E7%BD%91&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '能源/化工', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E5%9B%BD%E7%BD%91&match=%E5%9B%BD%E7%BD%91&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '协鑫', 'https://www.iguopin.com/job?company=%E5%8D%8F%E9%91%AB&match=%E5%8D%8F%E9%91%AB&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '能源/化工', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 79 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E5%8D%8F%E9%91%AB&match=%E5%8D%8F%E9%91%AB&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国中铁', 'https://www.iguopin.com/job?company=%E4%B8%AD%E9%93%81&match=%E4%B8%AD%E9%93%81&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '地产/建筑', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 12 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E9%93%81&match=%E4%B8%AD%E9%93%81&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '恒力集团', 'https://www.iguopin.com/job?company=%E6%81%92%E5%8A%9B%E7%9F%B3%E5%8C%96&match=%E6%81%92%E5%8A%9B%E7%9F%B3%E5%8C%96&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '能源/化工', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 42 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E6%81%92%E5%8A%9B%E7%9F%B3%E5%8C%96&match=%E6%81%92%E5%8A%9B%E7%9F%B3%E5%8C%96&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中远海运', 'https://www.iguopin.com/job?company=%E4%B8%AD%E8%BF%9C%E6%B5%B7%E8%BF%90&match=%E4%B8%AD%E8%BF%9C%E6%B5%B7%E8%BF%90&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '物流/供应链', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 126 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E8%BF%9C%E6%B5%B7%E8%BF%90&match=%E4%B8%AD%E8%BF%9C%E6%B5%B7%E8%BF%90&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '国泰海通', 'https://www.iguopin.com/job?company=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A&match=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '金融', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 9 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A&match=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国铁建', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E9%93%81%E5%BB%BA&match=%E9%93%81%E5%BB%BA&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '地产/建筑', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E9%93%81%E5%BB%BA&match=%E9%93%81%E5%BB%BA&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '南方电网', 'https://www.iguopin.com/job?company=%E5%8D%97%E6%96%B9%E7%94%B5%E7%BD%91&match=%E5%8D%97%E6%96%B9%E7%94%B5%E7%BD%91&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '能源/化工', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 307 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E5%8D%97%E6%96%B9%E7%94%B5%E7%BD%91&match=%E5%8D%97%E6%96%B9%E7%94%B5%E7%BD%91&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中南传媒', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%8D%97%E4%BC%A0%E5%AA%92&match=%E4%B8%AD%E5%8D%97%E5%87%BA%E7%89%88%E4%BC%A0%E5%AA%92&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '传媒/文娱', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 146 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%8D%97%E4%BC%A0%E5%AA%92&match=%E4%B8%AD%E5%8D%97%E5%87%BA%E7%89%88%E4%BC%A0%E5%AA%92&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国中冶', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%86%B6&match=%E4%B8%AD%E5%86%B6&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '地产/建筑', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%86%B6&match=%E4%B8%AD%E5%86%B6&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '中国能建', 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E8%83%BD%E6%BA%90%E5%BB%BA%E8%AE%BE&match=%E4%B8%AD%E5%9B%BD%E8%83%BD%E6%BA%90%E5%BB%BA%E8%AE%BE&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '地产/建筑', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 400 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E8%83%BD%E6%BA%90%E5%BB%BA%E8%AE%BE&match=%E4%B8%AD%E5%9B%BD%E8%83%BD%E6%BA%90%E5%BB%BA%E8%AE%BE&nature=115xW5oQ&channel=campus');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
select '奔驰', 'https://www.iguopin.com/job?company=%E5%A5%94%E9%A9%B0&match=%E5%A5%94%E9%A9%B0&nature=115xW5oQ&channel=campus', 'official', 'iguopin', 'http', true, 'soe', '汽车/出行', '{CN}',
       '2026-09-17 国聘应届生校招通道（nature=115xW5oQ），真实 adapter 端到端探活通过：自报 11 岗'
where not exists (select 1 from sources where source_url = 'https://www.iguopin.com/job?company=%E5%A5%94%E9%A9%B0&match=%E5%A5%94%E9%A9%B0&nature=115xW5oQ&channel=campus');
