-- ============================================================
-- 首批 5 个企业招聘源
-- ============================================================

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes) values
  ('百度', 'https://talent.baidu.com/jobs/list', 'mixed', 'baidu', 'http', '百度招聘官网'),
  ('京东', 'https://zhaopin.jd.com/web/job/job_info_list/3', 'social', 'jd', 'http', '京东社会招聘'),
  ('海尔', 'https://maker.haier.net/client/job/index', 'mixed', 'haier', 'http', '海尔招聘官网'),
  ('Apple', 'https://jobs.apple.com/en-us/search', 'mixed', 'apple', 'http', 'Apple careers, REST API'),
  ('Siemens', 'https://jobs.siemens.com/careers/search', 'mixed', 'siemens', 'http', 'Siemens global careers')
on conflict do nothing;
