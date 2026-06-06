-- 026 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Airbnb', 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true', 'official', 'greenhouse', 'http', 'Airbnb（互联网·旅行，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Stripe', 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true', 'official', 'greenhouse', 'http', 'Stripe（金融科技，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'IMC Trading', 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true', 'official', 'greenhouse', 'http', 'IMC Trading（量化，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Riot Games', 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true', 'official', 'greenhouse', 'http', 'Riot Games（游戏，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Bosch 博世', 'https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=100', 'official', 'smartrecruiters', 'http', 'Bosch 博世（汽车·工业，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select 'Avery Dennison', 'https://api.smartrecruiters.com/v1/companies/AveryDennison/postings?limit=100', 'official', 'smartrecruiters', 'http', 'Avery Dennison（材料·制造，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/AveryDennison/postings?limit=100');
