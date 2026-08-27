-- 197 — seed：必投清单的 4 个已 live 验证自建招聘门户（美的 / 招商银行 / 民生银行 / 格力）
--
-- 2026-08-27 live 实测：美的公开 form position/list 自报 748 岗且列表含职责/要求；
-- 招商银行公开 JSON 列表自报 138 岗、逐岗 GET detail 返回职责/要求；民生银行公开 form 列表
-- 5 页共 100 岗且详情为带 hash 的逐岗路由；格力 property=1/2 分别 52/12 岗。四家均为
-- 企业自有招聘域名、纯 http 抓取，抽样逐岗详情链接均返回 HTTP 200。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('美的集团', 'https://recruit.midea.com/recruitOut/ihr/social/', 'midea', 'http', '{CN}', 'private', '家电', true),
  ('招商银行', 'https://career.cmbchina.com/positionList/social', 'cmb', 'http', '{CN}', 'soe', '银行', true),
  ('民生银行', 'https://career.cmbc.com.cn/#/app/recruitmentlist', 'cmbc', 'http', '{CN}', 'private', '银行', true),
  ('格力', 'https://zhaopin.greeyun.com/', 'gree', 'http', '{CN}', 'soe', '家电', true),
  -- 沃尔玛：零代码白捡的一条。2026-08-27 逐家核实必投缺口时发现它跑在 Avature 上，
  -- 而 Avature 通用层当天刚落地（迁移 196）→ 不用写任何代码，登记即可抓。
  -- live 实测（用仓库里真实的 AvatureAdapter 跑）：49 岗全部解析、reported_total=49、
  -- fetch_complete=True、质量门 49/49 通过；逐岗链接形如
  -- https://walmartchina.avature.cn/zh_CN/careers/JobDetail/48562（HTTP 200，标题对得上）。
  -- 卡片无 article__content → 正文由 enrich（ENRICH_REGISTRY 的 avature）逐岗补。
  ('沃尔玛', 'https://walmartchina.avature.cn/zh_CN/careers/SearchJobs/?jobRecordsPerPage=10', 'avature', 'http', '{CN}', 'foreign', '零售', true)
on conflict (source_url) do nothing;
