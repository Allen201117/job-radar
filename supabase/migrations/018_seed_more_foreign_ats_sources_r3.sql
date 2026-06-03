-- ============================================================
-- Seed more foreign-ATS sources (round 3) — 在港/京/沪外企岗位
-- ============================================================
-- Extends 011/015/017. Probed live (2026-06-02) end-to-end through the real
-- greenhouse adapter parse() + normalizer.validate_job_quality(); both boards
-- expose genuine 大中华区 jobs with STABLE canonical per-job links
-- (job-boards.greenhouse.io/.../jobs/{id}):
--   OKX 欧易    greenhouse  95 大中华区（以香港为主，含台湾/远程）
--   WorldQuant  greenhouse   5 北京/上海/香港 量化岗
--
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'OKX 欧易', 'https://boards-api.greenhouse.io/v1/boards/okx/jobs?content=true', 'official', 'greenhouse', 'http', 'OKX 欧易（Greenhouse，在港岗位为主）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/okx/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'WorldQuant', 'https://boards-api.greenhouse.io/v1/boards/worldquant/jobs?content=true', 'official', 'greenhouse', 'http', 'WorldQuant（Greenhouse，北京/上海/香港 量化岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/worldquant/jobs?content=true');
