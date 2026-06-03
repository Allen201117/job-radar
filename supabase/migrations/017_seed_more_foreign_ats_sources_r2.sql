-- ============================================================
-- Seed more foreign-ATS sources (round 2) — 在港/沪外企岗位
-- ============================================================
-- Extends 011/015. Same source-driven greenhouse adapter; parse() filters to
-- 大中华区 only. Probed live (2026-06-02) end-to-end through the real adapter
-- parse() + normalizer.validate_job_quality(); kept only boards with genuine
-- 大中华区-located jobs whose jd_url is a STABLE per-job detail page:
--   Flow Traders  greenhouse  13 HK   (job-boards.greenhouse.io/.../jobs/{id})
--   DRW           greenhouse   3 HK   (job-boards.greenhouse.io/.../jobs/{id})
--   Akuna Capital greenhouse   2 沪    (akunacapital.com/careers/job/{id}/ — per-job path)
-- Excluded this round (data-quality red line — jd_url is a JS-embed gh_jid deep
-- link that resolves to a LISTING, not a per-job page, verified via browser):
--   Jump Trading / Tower Research / Squarepoint — revisit only via browser-intercept.
--
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Flow Traders', 'https://boards-api.greenhouse.io/v1/boards/flowtraders/jobs?content=true', 'official', 'greenhouse', 'http', 'Flow Traders（Greenhouse，在港岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/flowtraders/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'DRW', 'https://boards-api.greenhouse.io/v1/boards/drweng/jobs?content=true', 'official', 'greenhouse', 'http', 'DRW（Greenhouse，在港岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/drweng/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Akuna Capital', 'https://boards-api.greenhouse.io/v1/boards/akunacapital/jobs?content=true', 'official', 'greenhouse', 'http', 'Akuna Capital（Greenhouse，上海岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/akunacapital/jobs?content=true');
