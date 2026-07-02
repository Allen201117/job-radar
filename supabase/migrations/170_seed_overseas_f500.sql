-- 170_seed_overseas_f500.sql — Phase 4 定向补 Fortune 500 / 全球大厂海外源
-- 全部经 probe_overseas_f500.py live 探活确认：真返回美/新/远程岗 + jd_url 200（禁猜 slug 入库）。
-- 幂等：按 source_url 防重；regions 直接开 {CN,US,SG,Remote}。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Databricks', 'https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Databricks（greenhouse，Phase4 海外扩源，探活 435 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'GitLab', 'https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'GitLab（greenhouse，Phase4 海外扩源，探活 140 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Figma', 'https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Figma（greenhouse，Phase4 海外扩源，探活 116 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Datadog', 'https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Datadog（greenhouse，Phase4 海外扩源，探活 228 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Brex', 'https://boards-api.greenhouse.io/v1/boards/brex/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Brex（greenhouse，Phase4 海外扩源，探活 237 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/brex/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Scale AI', 'https://boards-api.greenhouse.io/v1/boards/scaleai/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Scale AI（greenhouse，Phase4 海外扩源，探活 126 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/scaleai/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Gusto', 'https://boards-api.greenhouse.io/v1/boards/gusto/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Gusto（greenhouse，Phase4 海外扩源，探活 75 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/gusto/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Airtable', 'https://boards-api.greenhouse.io/v1/boards/airtable/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Airtable（greenhouse，Phase4 海外扩源，探活 32 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/airtable/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Asana', 'https://boards-api.greenhouse.io/v1/boards/asana/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Asana（greenhouse，Phase4 海外扩源，探活 70 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/asana/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Dropbox', 'https://boards-api.greenhouse.io/v1/boards/dropbox/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Dropbox（greenhouse，Phase4 海外扩源，探活 52 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/dropbox/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Robinhood', 'https://boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Robinhood（greenhouse，Phase4 海外扩源，探活 119 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Affirm', 'https://boards-api.greenhouse.io/v1/boards/affirm/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Affirm（greenhouse，Phase4 海外扩源，探活 176 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/affirm/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Chime', 'https://boards-api.greenhouse.io/v1/boards/chime/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Chime（greenhouse，Phase4 海外扩源，探活 64 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/chime/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Roblox', 'https://boards-api.greenhouse.io/v1/boards/roblox/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Roblox（greenhouse，Phase4 海外扩源，探活 208 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/roblox/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Pinterest', 'https://boards-api.greenhouse.io/v1/boards/pinterest/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Pinterest（greenhouse，Phase4 海外扩源，探活 164 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/pinterest/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Lyft', 'https://boards-api.greenhouse.io/v1/boards/lyft/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Lyft（greenhouse，Phase4 海外扩源，探活 134 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/lyft/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Instacart', 'https://boards-api.greenhouse.io/v1/boards/instacart/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Instacart（greenhouse，Phase4 海外扩源，探活 154 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/instacart/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Peloton', 'https://boards-api.greenhouse.io/v1/boards/peloton/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Peloton（greenhouse，Phase4 海外扩源，探活 34 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/peloton/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Marqeta', 'https://boards-api.greenhouse.io/v1/boards/marqeta/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Marqeta（greenhouse，Phase4 海外扩源，探活 30 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/marqeta/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Reddit', 'https://boards-api.greenhouse.io/v1/boards/reddit/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Reddit（greenhouse，Phase4 海外扩源，探活 164 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/reddit/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Squarespace', 'https://boards-api.greenhouse.io/v1/boards/squarespace/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Squarespace（greenhouse，Phase4 海外扩源，探活 12 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/squarespace/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Nubank', 'https://boards-api.greenhouse.io/v1/boards/nubank/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Nubank（greenhouse，Phase4 海外扩源，探活 50 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/nubank/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Coinbase', 'https://boards-api.greenhouse.io/v1/boards/coinbase/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Coinbase（greenhouse，Phase4 海外扩源，探活 121 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/coinbase/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Duolingo', 'https://boards-api.greenhouse.io/v1/boards/duolingo/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Duolingo（greenhouse，Phase4 海外扩源，探活 33 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/duolingo/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Udemy', 'https://boards-api.greenhouse.io/v1/boards/udemy/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Udemy（greenhouse，Phase4 海外扩源，探活 5 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/udemy/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Webflow', 'https://boards-api.greenhouse.io/v1/boards/webflow/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Webflow（greenhouse，Phase4 海外扩源，探活 21 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/webflow/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Vercel', 'https://boards-api.greenhouse.io/v1/boards/vercel/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Vercel（greenhouse，Phase4 海外扩源，探活 55 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/vercel/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Postman', 'https://boards-api.greenhouse.io/v1/boards/postman/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Postman（greenhouse，Phase4 海外扩源，探活 84 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/postman/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Faire', 'https://boards-api.greenhouse.io/v1/boards/faire/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Faire（greenhouse，Phase4 海外扩源，探活 54 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/faire/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Sweetgreen', 'https://boards-api.greenhouse.io/v1/boards/sweetgreen/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Sweetgreen（greenhouse，Phase4 海外扩源，探活 51 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/sweetgreen/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Flexport', 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Flexport（greenhouse，Phase4 海外扩源，探活 55 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/flexport/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Checkr', 'https://boards-api.greenhouse.io/v1/boards/checkr/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Checkr（greenhouse，Phase4 海外扩源，探活 52 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/checkr/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Gemini', 'https://boards-api.greenhouse.io/v1/boards/gemini/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Gemini（greenhouse，Phase4 海外扩源，探活 23 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/gemini/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Anduril', 'https://boards-api.greenhouse.io/v1/boards/andurilindustries/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Anduril（greenhouse，Phase4 海外扩源，探活 2063 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/andurilindustries/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Verkada', 'https://boards-api.greenhouse.io/v1/boards/verkada/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Verkada（greenhouse，Phase4 海外扩源，探活 252 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/verkada/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Cockroach Labs', 'https://boards-api.greenhouse.io/v1/boards/cockroachlabs/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Cockroach Labs（greenhouse，Phase4 海外扩源，探活 26 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/cockroachlabs/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Grafana Labs', 'https://boards-api.greenhouse.io/v1/boards/grafanalabs/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Grafana Labs（greenhouse，Phase4 海外扩源，探活 106 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/grafanalabs/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Temporal', 'https://boards-api.greenhouse.io/v1/boards/temporaltechnologies/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Temporal（greenhouse，Phase4 海外扩源，探活 47 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/temporaltechnologies/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Mozilla', 'https://boards-api.greenhouse.io/v1/boards/mozilla/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Mozilla（greenhouse，Phase4 海外扩源，探活 68 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/mozilla/jobs?content=true');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)
select 'Mercury', 'https://boards-api.greenhouse.io/v1/boards/mercury/jobs?content=true', 'official', 'greenhouse', 'http', '{CN,US,SG,Remote}'::text[], 'Mercury（greenhouse，Phase4 海外扩源，探活 52 海外岗）'
where not exists (select 1 from sources where source_url = 'https://boards-api.greenhouse.io/v1/boards/mercury/jobs?content=true');
