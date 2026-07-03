-- 171_seed_overseas_f500.sql — Phase 4 定向补 Fortune 500 / 全球大厂海外源
-- 全部经 probe_overseas_f500.py live 探活确认：真返回美/新/远程岗 + jd_url 200（禁猜 slug 入库）。
-- 幂等：按 source_url 防重；regions 直接开 {CN,US,SG,Remote}。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Perplexity', 'https://api.ashbyhq.com/posting-api/job-board/perplexity?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Perplexity（ashby，Phase4 海外扩源，探活 60 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/perplexity?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Linear', 'https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Linear（ashby，Phase4 海外扩源，探活 16 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Vanta', 'https://api.ashbyhq.com/posting-api/job-board/vanta?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Vanta（ashby，Phase4 海外扩源，探活 68 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/vanta?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Replit', 'https://api.ashbyhq.com/posting-api/job-board/replit?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Replit（ashby，Phase4 海外扩源，探活 86 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/replit?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'ElevenLabs', 'https://api.ashbyhq.com/posting-api/job-board/elevenlabs?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'ElevenLabs（ashby，Phase4 海外扩源，探活 47 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/elevenlabs?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Mercor', 'https://api.ashbyhq.com/posting-api/job-board/mercor?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Mercor（ashby，Phase4 海外扩源，探活 58 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/mercor?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Sierra', 'https://api.ashbyhq.com/posting-api/job-board/sierra?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Sierra（ashby，Phase4 海外扩源，探活 82 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/sierra?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Decagon', 'https://api.ashbyhq.com/posting-api/job-board/decagon?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Decagon（ashby，Phase4 海外扩源，探活 93 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/decagon?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Baseten', 'https://api.ashbyhq.com/posting-api/job-board/baseten?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Baseten（ashby，Phase4 海外扩源，探活 67 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/baseten?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Cohere', 'https://api.ashbyhq.com/posting-api/job-board/cohere?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Cohere（ashby，Phase4 海外扩源，探活 39 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/cohere?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Harvey', 'https://api.ashbyhq.com/posting-api/job-board/harvey?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Harvey（ashby，Phase4 海外扩源，探活 252 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/harvey?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Supabase', 'https://api.ashbyhq.com/posting-api/job-board/supabase?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Supabase（ashby，Phase4 海外扩源，探活 39 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/supabase?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'LangChain', 'https://api.ashbyhq.com/posting-api/job-board/langchain?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'LangChain（ashby，Phase4 海外扩源，探活 74 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/langchain?includeCompensation=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Fireworks AI', 'https://api.ashbyhq.com/posting-api/job-board/fireworksai?includeCompensation=true', 'official', 'ashby', 'http', '{CN,US,SG,Remote}'::text[], 'Fireworks AI（ashby，Phase4 海外扩源，探活 5 海外岗）'
where not exists (select 1 from sources where source_url = 'https://api.ashbyhq.com/posting-api/job-board/fireworksai?includeCompensation=true');
