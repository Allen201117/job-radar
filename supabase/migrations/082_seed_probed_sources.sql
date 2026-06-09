-- 082 — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Airbnb', 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', '互联网·旅行', 'Airbnb（互联网·旅行，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Stripe', 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', '金融科技', 'Stripe（金融科技，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'IMC Trading', 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', '量化', 'IMC Trading（量化，probe live 探活 在华 14 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Riot Games', 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', '游戏', 'Riot Games（游戏，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Bosch 博世', 'https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', '汽车·工业', 'Bosch 博世（汽车·工业，probe live 探活 在华 8 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Avery Dennison', 'https://api.smartrecruiters.com/v1/companies/AveryDennison/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', '材料·制造', 'Avery Dennison（材料·制造，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/AveryDennison/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'NVIDIA', 'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs', 'official', 'workday', 'http', 'foreign', '半导体·AI', 'NVIDIA（半导体·AI，probe live 探活 在华 180 岗）'
where not exists (select 1 from sources where source_url = 'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Pfizer 辉瑞', 'https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs', 'official', 'workday', 'http', 'foreign', '医药', 'Pfizer 辉瑞（医药，probe live 探活 在华 190 岗）'
where not exists (select 1 from sources where source_url = 'https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Citi 花旗', 'https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs', 'official', 'workday', 'http', 'foreign', '金融', 'Citi 花旗（金融，probe live 探活 在华 196 岗）'
where not exists (select 1 from sources where source_url = 'https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Mastercard 万事达', 'https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs', 'official', 'workday', 'http', 'foreign', '金融·支付', 'Mastercard 万事达（金融·支付，probe live 探活 在华 17 岗）'
where not exists (select 1 from sources where source_url = 'https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'HSBC', 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com', 'official', 'eightfold', 'http', 'foreign', 'discover', 'HSBC（discover，probe live 探活 在华 477 岗）'
where not exists (select 1 from sources where source_url = 'https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Stripe', 'https://boards-api.greenhouse.io/v1/boards/Stripe/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Stripe（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Stripe/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'AstraZeneca', 'https://astrazeneca.eightfold.ai/api/apply/v2/jobs?domain=astrazeneca.com', 'official', 'eightfold', 'http', 'foreign', 'discover', 'AstraZeneca（discover，probe live 探活 在华 10 岗）'
where not exists (select 1 from sources where source_url = 'https://astrazeneca.eightfold.ai/api/apply/v2/jobs?domain=astrazeneca.com');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Snowflake', 'https://api.ashbyhq.com/posting-api/job-board/snowflake?includeCompensation=true', 'official', 'ashby', 'http', 'foreign', 'discover', 'Snowflake（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/snowflake?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Snowflake', 'https://api.ashbyhq.com/posting-api/job-board/Snowflake?includeCompensation=true', 'official', 'ashby', 'http', 'foreign', 'discover', 'Snowflake（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/Snowflake?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Airbnb', 'https://boards-api.greenhouse.io/v1/boards/Airbnb/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Airbnb（discover，probe live 探活 在华 12 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Airbnb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Riot Games', 'https://boards-api.greenhouse.io/v1/boards/RiotGames/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Riot Games（discover，probe live 探活 在华 45 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/RiotGames/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Bayer', 'https://bayer.eightfold.ai/api/apply/v2/jobs?domain=bayer.com', 'official', 'eightfold', 'http', 'foreign', 'discover', 'Bayer（discover，probe live 探活 在华 3 岗）'
where not exists (select 1 from sources where source_url = 'https://bayer.eightfold.ai/api/apply/v2/jobs?domain=bayer.com');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Western Digital', 'https://api.smartrecruiters.com/v1/companies/westerndigital/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', 'discover', 'Western Digital（discover，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/westerndigital/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Western Digital', 'https://api.smartrecruiters.com/v1/companies/WesternDigital/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', 'discover', 'Western Digital（discover，probe live 探活 在华 5 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/WesternDigital/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Arista Networks', 'https://api.smartrecruiters.com/v1/companies/aristanetworks/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', 'discover', 'Arista Networks（discover，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/aristanetworks/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Arista Networks', 'https://api.smartrecruiters.com/v1/companies/AristaNetworks/postings?limit=100', 'official', 'smartrecruiters', 'http', 'foreign', 'discover', 'Arista Networks（discover，probe live 探活 在华 2 岗）'
where not exists (select 1 from sources where source_url = 'https://api.smartrecruiters.com/v1/companies/AristaNetworks/postings?limit=100');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Hasbro', 'https://boards-api.greenhouse.io/v1/boards/hasbro/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Hasbro（discover，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/hasbro/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Hasbro', 'https://boards-api.greenhouse.io/v1/boards/Hasbro/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Hasbro（discover，probe live 探活 在华 13 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Hasbro/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Zscaler', 'https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Zscaler（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Zscaler', 'https://boards-api.greenhouse.io/v1/boards/Zscaler/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Zscaler（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Zscaler/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MongoDB', 'https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'MongoDB（discover，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'MongoDB', 'https://boards-api.greenhouse.io/v1/boards/Mongodb/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'MongoDB（discover，probe live 探活 在华 6 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Mongodb/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Elastic', 'https://boards-api.greenhouse.io/v1/boards/elastic/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Elastic（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/elastic/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Elastic', 'https://boards-api.greenhouse.io/v1/boards/Elastic/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Elastic（discover，probe live 探活 在华 1 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Elastic/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Flexport', 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Flexport（discover，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'Flexport', 'https://boards-api.greenhouse.io/v1/boards/Flexport/jobs?content=true', 'official', 'greenhouse', 'http', 'foreign', 'discover', 'Flexport（discover，probe live 探活 在华 7 岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/Flexport/jobs?content=true');
