-- Keep seeded source URLs aligned with currently verified public careers pages.

update sources
set
  source_url = 'https://jobs.siemens.com/en_US/externaljobs/SearchJobs',
  notes = 'Siemens Careers Marketplace SearchJobs page'
where adapter_name = 'siemens';

update sources
set
  notes = 'Apple public careers search page'
where adapter_name = 'apple';

update sources
set
  source_url = 'https://talent.baidu.com/jobs/social-list',
  notes = '百度官方社招 SSR 列表页，详情链接为 /jobs/detail/{recruitType}/{postId}'
where adapter_name = 'baidu';
