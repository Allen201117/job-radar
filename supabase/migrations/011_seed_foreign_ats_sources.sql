-- ============================================================
-- Seed foreign-ATS sources (Greenhouse / Lever) — 在华外企岗位
-- ============================================================
-- Generic greenhouse/lever adapters cover any company via one source row.
-- These boards were probed live (2026-06-02) and confirmed to expose 大中华区
-- 岗位; the adapters filter to China-only inside parse(), so they never pollute
-- the radar with global roles. Add more companies by appending source rows.
-- Idempotent: guarded by source_url (multiple companies share an adapter_name).

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '爱彼迎 Airbnb', 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true', 'official', 'greenhouse', 'http', 'Airbnb（Greenhouse，在华岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Agoda', 'https://boards-api.greenhouse.io/v1/boards/agoda/jobs?content=true', 'official', 'greenhouse', 'http', 'Agoda（Greenhouse，在华岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/agoda/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'MongoDB', 'https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true', 'official', 'greenhouse', 'http', 'MongoDB（Greenhouse，在华岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '拳头游戏 Riot Games', 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true', 'official', 'greenhouse', 'http', 'Riot Games（Greenhouse，在华岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Epic Games', 'https://boards-api.greenhouse.io/v1/boards/epicgames/jobs?content=true', 'official', 'greenhouse', 'http', 'Epic Games（Greenhouse，在华岗位）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/epicgames/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '币安 Binance', 'https://api.lever.co/v0/postings/binance?mode=json', 'official', 'lever', 'http', 'Binance（Lever，在华/港岗位）'
where not exists (select 1 from sources where source_url = 'https://api.lever.co/v0/postings/binance?mode=json');
