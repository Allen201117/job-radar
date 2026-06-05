-- ============================================================
-- 022 — 扩源 round 4：跨行业在华/港/台官方源（greenhouse ATS）
-- ============================================================
-- 延续 011/015/017/018。全部 live 探活（2026-06-05）：greenhouse boards-api 返回 200，
-- 且含真实大中华区岗位（按 location 计数，greenhouse adapter parse() 已裁到在华/港/台岗）。
-- 行业刻意分散（消费/对冲基金·量化/物流/支付/IoT/安全），扩覆盖面。
--   On 昂跑       greenhouse  97 北京/上海/武汉/成都（消费·运动品牌，含大陆多地）
--   Point72       greenhouse  27 香港（对冲基金）
--   Squarepoint   greenhouse  16 香港（量化）
--   Jump Trading  greenhouse  14 上海/香港（量化）
--   Flexport      greenhouse   8 深圳/上海/台北（物流·供应链）
--   Adyen         greenhouse   7 香港/上海（支付·fintech）
--   Samsara       greenhouse   5 台湾远程（IoT·工业互联）
--   Zscaler       greenhouse   3 台湾/香港（网络安全）
--
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'On 昂跑', 'https://boards-api.greenhouse.io/v1/boards/onrunning/jobs?content=true', 'official', 'greenhouse', 'http', 'On 昂跑（Greenhouse，消费·运动品牌，北京/上海/武汉/成都）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/onrunning/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Point72', 'https://boards-api.greenhouse.io/v1/boards/point72/jobs?content=true', 'official', 'greenhouse', 'http', 'Point72（Greenhouse，对冲基金，香港）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/point72/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Squarepoint', 'https://boards-api.greenhouse.io/v1/boards/squarepointcapital/jobs?content=true', 'official', 'greenhouse', 'http', 'Squarepoint（Greenhouse，量化，香港）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/squarepointcapital/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Jump Trading', 'https://boards-api.greenhouse.io/v1/boards/jumptrading/jobs?content=true', 'official', 'greenhouse', 'http', 'Jump Trading（Greenhouse，量化，上海/香港）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/jumptrading/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Flexport', 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true', 'official', 'greenhouse', 'http', 'Flexport（Greenhouse，物流·供应链，深圳/上海/台北）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Adyen', 'https://boards-api.greenhouse.io/v1/boards/adyen/jobs?content=true', 'official', 'greenhouse', 'http', 'Adyen（Greenhouse，支付·fintech，香港/上海）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/adyen/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Samsara', 'https://boards-api.greenhouse.io/v1/boards/samsara/jobs?content=true', 'official', 'greenhouse', 'http', 'Samsara（Greenhouse，IoT·工业互联，台湾远程）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/samsara/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Zscaler', 'https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true', 'official', 'greenhouse', 'http', 'Zscaler（Greenhouse，网络安全，台湾/香港）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true');
