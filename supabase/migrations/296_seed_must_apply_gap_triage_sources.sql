-- 296 — 必投缺口 61 家逐家实地复核后，接入 8 家「现成抓取程序就能接」的公司（9 条源）
--
-- 为什么是这 8 家：缺口漏斗（gap_funnel）自动找入口找错了——台账里记的入口大片是别人家的网站
-- （ABB→艾伯维 AbbVie、赛力斯/福耀→第三方招聘站、君实生物→一个「声明」静态页、百胜中国→国聘源
-- 但国聘源在这一档被设计成跳过、永远 0 岗），后面「反爬 / 拿不到逐岗链接 / 没 adapter」都是对着
-- 错页面下的结论。2026-09-23 对缺口里没有历史结论的 61 家逐家实地核（官网→真正列岗的页面→
-- 平台→真 id/假 id 对拍→在招数），其中 12 家落在已有抓取程序上；本迁移接其中 8 家。
-- 另 4 家不在这里：百胜中国见下方「⛔ 刻意没接」；盒马已有源（CI 海外出口拿不到 XSRF cookie，另一 session 在查）、
-- 优酷已在「虎鲸文娱」源里（本次改为按标题前缀派生归属，不加源）、万达电影已改名儒意电影、
-- 其招聘站就是已接入的「儒意影业」源（清单重复，待创始人定）。
--
-- ── 每条接入前 live 验过的事实（2026-09-23，本机 adapter 端到端 fetch→parse→validate_job_quality）──
--   ABB           abb.wd3.myworkdayjobs.com   Workday「China」分组 379 岗（+香港 1），接口 facet 计数
--   赛力斯集团     sokon.zhiye.com/social      303 = 平台自报 303（校招 178/社招 105/实习 20），正文 303/303
--   君实生物       junshibiosciences.zhiye.com 82 = 自报 82，正文 82/82
--   蓝思科技       hnlens.zhiye.com/social     44 = 自报 44（全是校招；其中越南 6 个会按海外归类）
--   利欧集团       leoglobal.jobs.feishu.cn    68 = 自报 68，正文 65/68（旧北森 leogroup 租户已失效）
--   华东医药 社招  app.mokahr.com …/6456       86；校招 …/67935 75
--   编程猫         app.mokahr.com …/38020      14
--   传化智联       app.mokahr.com …/117946     1
--   · 北森 / 飞书 / Workday：should_skip(source_url) 全部 None；详情页真开 3 条全 HTTP 200。
--   · 北森的「/campus」对新版租户返回的是同一批（social/detail 链接），所以赛力斯/蓝思只接一条。
--   · 北森三个租户 beisen_httpx_ready() 全为 True → 走 httpx 快车道。
--   · ABB 本机全量没跑完（Workday 逐岗补正文 + 遵守对方 Retry-After 限流，很慢），以接口分组计数为准，
--     上线后回读线上 crawl_runs 核实。
--
-- ── 归属（CLAUDE.md 红线：只认租户/页面自报，不认 slug）──
--   赛力斯「赛力斯集团招聘门户网」/ 君实「君实生物」/
--   蓝思「蓝思科技2027校招门户」/ 利欧「加入利欧集团」/ 华东医药「华东医药股份有限公司 - 社会招聘」
--   （页脚 © 华东医药股份有限公司）/ 传化智联「传化智联股份有限公司 - 社会招聘」——
--   ⚠️ 传化的 Moka 租户 slug 叫 wynca（与新安化工共用），**只能按 portalId 页面自报核**，别按 slug 扩。
--   编程猫的 Moka 页面不写公司名 → 以官方招聘站 hr.codemao.cn（标题「编程猫」）直接链到本门户为据。
--   ABB：Workday 租户 abb 是 ABB 集团全球招聘站；台账原入口 careers.abbvie.com 是艾伯维（另一家公司）。
--
-- ⛔ 刻意没接：百胜中国（yumchina.zhiye.com，北森老版 SSR，社招 2392 + 校招 96，全部能抓、链接唯一）。
--    两个问题要先解决：① 现有程序没抠列表表格里的「工作地点」列，2392 个岗全无地点，而 /today 召回对
--    「城市未知」放行 → 会给每个城市的用户推其它城市的门店岗；② 列表「发布时间」约 65% 在 2017~2023 年
--    （2017 年 451 个、2026 年 507 个），分不清是常年招的门店储备岗还是没撤的僵尸岗。等创始人定口径。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
-- 回滚：update sources set enabled=false where notes like '2026-09-23 缺口复核接入%';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', v.adapter, v.method, true, '{CN}', v.segment, v.industry,
       v.industry_group, v.ownership, v.notes
from (values
  ('ABB', 'https://abb.wd3.myworkdayjobs.com/wday/cxs/abb/External_Career_Page/jobs', 'workday', 'http', 'foreign', '电气/自动化', '制造/工业', 'foreign',
   '2026-09-23 缺口复核接入：ABB 集团 Workday 全球站，中国分组 379 岗。台账原入口 careers.abbvie.com 是艾伯维（英文名子串误配，已修）。'),
  ('赛力斯集团', 'https://sokon.zhiye.com/social', 'beisen', 'http', 'private', '汽车·新能源', '汽车/出行', 'private',
   '2026-09-23 缺口复核接入：北森租户 sokon，页面自报「赛力斯集团招聘门户网」。live 303 = 自报 303。原台账入口是第三方招聘站。'),
  ('君实生物', 'https://junshibiosciences.zhiye.com/social', 'beisen', 'http', 'private', '医药·生物', '医疗/医药', 'private',
   '2026-09-23 缺口复核接入：北森租户 junshibiosciences，页面自报「君实生物」。live 82 = 自报 82。'),
  ('蓝思科技', 'https://hnlens.zhiye.com/social', 'beisen', 'http', 'private', '消费电子', '制造/工业', 'private',
   '2026-09-23 缺口复核接入：北森租户 hnlens，页面自报「蓝思科技2027校招门户」。live 44 = 自报 44（全校招，含越南 6）。'),
  ('利欧集团', 'https://leoglobal.jobs.feishu.cn/index/position', 'feishu', 'http', 'private', '泵业/数字营销', '传媒/文娱', 'private',
   '2026-09-23 缺口复核接入：飞书租户 leoglobal，页面自报「加入利欧集团」。live 68 = 自报 68。旧北森 leogroup 已失效。'),
  ('华东医药', 'https://app.mokahr.com/social-recruitment/eastchinapharm/6456', 'moka', 'playwright', 'private', '医药', '医疗/医药', 'private',
   '2026-09-23 缺口复核接入：Moka 门户自报「华东医药股份有限公司 - 社会招聘」。live 86 岗。'),
  ('华东医药', 'https://app.mokahr.com/campus-recruitment/eastchinapharm/67935', 'moka', 'playwright', 'private', '医药', '医疗/医药', 'private',
   '2026-09-23 缺口复核接入：Moka 门户自报「华东医药股份有限公司 - 校园招聘」。live 75 岗。'),
  ('编程猫', 'https://app.mokahr.com/social-recruitment/codemaohr/38020', 'moka', 'playwright', 'private', '少儿编程', '教育', 'private',
   '2026-09-23 缺口复核接入：官方招聘站 hr.codemao.cn（标题「编程猫」）直链本门户。live 14 岗。'),
  ('传化智联', 'https://app.mokahr.com/social-recruitment/wynca/117946', 'moka', 'playwright', 'private', '物流科技', '物流/供应链', 'private',
   '2026-09-23 缺口复核接入：Moka 门户自报「传化智联股份有限公司 - 社会招聘」。⚠️ slug wynca 与新安化工共用，只按 portalId 核。live 1 岗。')
) as v(company, url, adapter, method, segment, industry, industry_group, ownership, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);
