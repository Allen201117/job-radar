-- Marqeta / Temporal 已从 Greenhouse 迁到 Ashby（2026-09-19 live 核实）：
-- boards-api.greenhouse.io/v1/boards/{marqeta,temporaltechnologies}/jobs 均连续多日 404
-- （非 403/超时，是「board 不存在」）；对方官网 careers 页（marqeta.com/company/careers、
-- temporal.io/careers）自己嵌的详情页 apply 链接现指向 jobs.ashbyhq.com/marqeta-inc/{uuid}
-- 与 jobs.ashbyhq.com/temporal/{uuid}，即官网自证的真实 ATS + board slug。
-- api.ashbyhq.com/posting-api/job-board/marqeta-inc 与 …/temporal 均匿名 200，
-- 分别返回 39 / 65 条在招岗（2026-09-19 live 核实，非猜测 slug）。
update sources
   set source_url = 'https://api.ashbyhq.com/posting-api/job-board/marqeta-inc?includeCompensation=true',
       adapter_name = 'ashby'
 where source_url = 'https://boards-api.greenhouse.io/v1/boards/marqeta/jobs?content=true';

update sources
   set source_url = 'https://api.ashbyhq.com/posting-api/job-board/temporal?includeCompensation=true',
       adapter_name = 'ashby'
 where source_url = 'https://boards-api.greenhouse.io/v1/boards/temporaltechnologies/jobs?content=true';
