-- ============================================================
-- Seed more foreign-ATS sources (Greenhouse / Lever) — 在华/港外企岗位
-- ============================================================
-- Extends 011. Same source-driven design: one greenhouse/lever adapter covers
-- any company via a single source row; parse() filters to 大中华区 only, so a
-- board's global roles never reach the China radar.
--
-- Each board below was probed live (2026-06-02) end-to-end through the real
-- adapter parse() + normalizer.validate_job_quality(); only boards with genuine
-- 大中华区-located jobs whose jd_url is a stable per-job detail page were kept:
--   Jane Street  greenhouse  54 HK jobs   (job-boards.greenhouse.io/.../jobs/{id})
--   Scopely      greenhouse  13 Shanghai  (job-boards.greenhouse.io/.../jobs/{id})
--   IMC Trading  greenhouse  14 HK jobs   (job-boards.eu.greenhouse.io/.../jobs/{id})
--   Animoca      lever        5 HK jobs   (jobs.lever.co/animocabrands/{uuid})
-- Excluded (data-quality red line): boards whose only China matches were generic
-- "Remote" with no real China presence (Samsara/Databricks/Cloudflare/GitLab/
-- Stripe/Roblox), and Elastic (1 marginal job, careers-SPA query-param jd_url).
--
-- Idempotent: guarded by source_url (multiple companies share an adapter_name).

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Jane Street', 'https://boards-api.greenhouse.io/v1/boards/janestreet/jobs?content=true', 'official', 'greenhouse', 'http', 'Jane Street（Greenhouse，在港岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/janestreet/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Scopely', 'https://boards-api.greenhouse.io/v1/boards/scopely/jobs?content=true', 'official', 'greenhouse', 'http', 'Scopely（Greenhouse，上海游戏工作室岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/scopely/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'IMC Trading', 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true', 'official', 'greenhouse', 'http', 'IMC Trading（Greenhouse，在港岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Animoca Brands', 'https://api.lever.co/v0/postings/animocabrands?mode=json', 'official', 'lever', 'http', 'Animoca Brands（Lever，在港 Web3 岗位）'
where not exists (select 1 from sources where source_url = 'https://api.lever.co/v0/postings/animocabrands?mode=json');
