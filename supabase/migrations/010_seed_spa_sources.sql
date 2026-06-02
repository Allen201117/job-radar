-- ============================================================
-- Seed SPA browser-intercept sources (字节 + 飞书/Lark 招聘系)
-- ============================================================
-- These adapters (run.py ADAPTERS) were added during the Playwright spike but
-- never landed in a migration, so a fresh DB has no source rows for them and
-- both the daily crawl and the on-demand browser-discovery recipe would find
-- nothing to crawl. Seed them idempotently (guarded by adapter_name).

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '字节跳动', 'https://jobs.bytedance.com/experienced/position', 'social', 'bytedance', 'playwright', '字节跳动社招（Playwright 拦截 /api/v1/search/job/posts）'
where not exists (select 1 from sources where adapter_name = 'bytedance');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '蔚来', 'https://nio.jobs.feishu.cn/index/position', 'social', 'nio_feishu', 'playwright', '蔚来招聘（飞书/Lark 招聘系）'
where not exists (select 1 from sources where adapter_name = 'nio_feishu');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '小鹏汽车', 'https://xiaopeng.jobs.feishu.cn/index/position', 'social', 'xpeng_feishu', 'playwright', '小鹏招聘（飞书/Lark 招聘系）'
where not exists (select 1 from sources where adapter_name = 'xpeng_feishu');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '地平线', 'https://horizon.jobs.feishu.cn/index/position', 'social', 'horizon_feishu', 'playwright', '地平线招聘（飞书/Lark 招聘系）'
where not exists (select 1 from sources where adapter_name = 'horizon_feishu');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '小米', 'https://xiaomi.jobs.f.mioffice.cn/index/position', 'social', 'xiaomi_feishu', 'playwright', '小米招聘（飞书/Lark 招聘系 mioffice）'
where not exists (select 1 from sources where adapter_name = 'xiaomi_feishu');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '腾讯', 'https://careers.tencent.com/search.html', 'social', 'tencent', 'http', '腾讯社招（公开 JSON API）'
where not exists (select 1 from sources where adapter_name = 'tencent');
