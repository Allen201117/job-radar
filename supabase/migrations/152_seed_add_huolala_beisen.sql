-- 152 — 定向补缺失大厂（原则#3：定向补目标公司，live 探活确认产出真岗后才入库）。
-- 货拉拉 Lalamove：beisen 平台，2026-06-19 live 探活 huolala.zhiye.com/api/JobAd/GetJobAdPageList
-- 返回 Count=472 真岗（海外销售岗/海外运营岗/培训专员…），同城货运/物流科技平台，目标用户相关。
-- Idempotent: guarded by source_url。社招页 /social（200 确认），beisen adapter playwright 拦截 GetJobAdPageList。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '货拉拉 Lalamove', 'https://huolala.zhiye.com/social', 'official', 'beisen', 'playwright', 'private', '物流科技', '货拉拉（同城货运/物流科技平台，2026-06-19 live 探活 在华 472 岗）'
where not exists (select 1 from sources where source_url = 'https://huolala.zhiye.com/social');
