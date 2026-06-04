-- ============================================================
-- Seed 校招 / 实习 官方源 — 扩大校招/实习覆盖（任务 4.1 续）
-- ============================================================
-- 现状：字节只抓 jobs.bytedance.com/experienced（社招）；百度默认源是 social-list（社招）。
-- 这里补两条同域名、同平台的校招/实习官方源：
--   · 字节 campus：jobs.bytedance.com/campus（与社招同飞书系平台、同拦截接口），
--     走新 adapter bytedance_campus（list/detail 路径换成 /campus；实习关键词已纳入广度抓取）
--   · 百度校招：talent.baidu.com/jobs/campus-list（与社招同站，baidu adapter 的 __INITIAL_DATA__
--     解析对 recruitType 通用，换列表 URL 即可，无需改代码）
-- 数据安全：即便某源链接不对，run.py 的质量门（validate_job_quality）只会记 failed/partial_success，
-- 不会把坏 jd_url 写成 active 岗位。上线后请跑一次抓取核验，失败的源在 /sources 关掉即可。
-- 幂等：按 source_url 去重。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '字节跳动', 'https://jobs.bytedance.com/campus/position', 'official', 'bytedance_campus', 'playwright', '字节跳动校招/实习（飞书系，与社招同平台同接口）'
where not exists (select 1 from sources where source_url = 'https://jobs.bytedance.com/campus/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '百度', 'https://talent.baidu.com/jobs/campus-list', 'official', 'baidu', 'http', '百度校招（与社招同站，校招列表；adapter 解析对 recruitType 通用）'
where not exists (select 1 from sources where source_url = 'https://talent.baidu.com/jobs/campus-list');
