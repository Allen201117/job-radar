-- 196 — seed：必投清单的 3 个已 live 验证 ATS 平台入口（Avature / Gllue / cnstaff）
--
-- 2026-08-27 live 实测：欧莱雅 Avature 中国 facet 的 HTML 搜索页 offset=0/20/40 各返回 20 张
-- 含真实 JobDetail href 的卡片；龙湖 Gllue /jobs 共自报 307 个职位且详情 SSR 含「职位描述」；
-- 光明乳业 cnstaff joblist API 遍历社招/校招的所有职类并集为 35 个 job_id（只读「全部」会漏岗），
-- 其详情页由 job_id 路由并核验标题。三条均为企业自有招聘域名，纯 http 抓取。
--
-- 194 已被 north_star_snapshots 占用，故本 seed 使用下一个空闲递增前缀 196。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('欧莱雅',   'https://careers.loreal.com/zh_CN/jobs/SearchJobs?3_110_3=18009', 'avature', 'http', '{CN}', 'foreign', '美妆', true),
  ('龙湖集团', 'https://longfor.career.gllue.com/jobs',                         'gllue',   'http', '{CN}', 'private', '地产', true),
  ('光明乳业', 'https://brightdairy.cnstaff.com/',                              'cnstaff', 'http', '{CN}', 'soe',     '食品', true)
on conflict (source_url) do nothing;
