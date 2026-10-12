-- 332 — 接入英科医疗（300677，一次性手套）的官方招聘入口：飞书租户 global-intco 的另外两个门户
--       （2026-10-12 找到入口并全量核实，创始人同日确认「按你的建议来」）
--
-- 背景：迁移 323 把 global-intco.jobs.feishu.cn/index 那条源由「英科医疗」纠正为「英科再生」之后，英科医疗零源零岗。
--   当时只知道「租户里另有 381 个岗不在 index 门户上」，不知道它们挂在哪个公开门户。
-- 入口是怎么找到的（没有猜路径）：英科医疗官网招聘页 intcomedical.com.cn/jobs/index.html（标题「英科医疗-招聘官网」）
--   自己的两个链接 ——「社会招聘」→ global-intco.jobs.feishu.cn/757263，「校园招聘」→ /840753。
--   2022 年用过的 Moka 门户（campus-recruitment/intco、social-recruitment/intco）现在都是「当前网页已关停」。
-- 门户自报（各取门户首页；租户名三个门户都只写「英科」，租户根路径 / 回的是英科再生那个门户）：
--   /757263  <title>「英科医疗社会招聘官网」  website_info.name「英科医疗-社会招聘官网」
--   /840753  <title>「英科医疗校园招聘官网」  website_info.name「英科医疗-校园招聘官网」
-- 核验（全部只读；带各自门户的 website-path 头）：
--   · 列表翻全：757263 = 326、840753 = 119（2027 校园招聘 116 / 日常实习生招聘 2 / 2026 校园招聘 1），
--     与页面自己显示的「开启新的工作（326）/（119）」一致；index = 87。
--   · 三个门户两两的交集：index ∩ 757263 = 17（见下），index ∩ 840753 = 0，757263 ∩ 840753 = 0。
--   · 逐岗读详情接口的 channel_online_status（全集）：326/326、119/119 在自己门户上是 1；
--     反向 —— 757263 独有的 309 个带 index 头、index 独有的 70 个带 757263 头、840753 的 119 个带 757263 头，全是 0。
--   · 浏览器实开：社招「品质客诉专员」（九江，正文是丁腈手套客诉）与校招「【27届校招】工艺工程师」能打开、有投递按钮；
--     同一个社招岗换成 /index/ 前缀显示「该职位已下线」→ 链接必须用各自门户的前缀（adapter 按路径首段自动取）。
--   · 真实 adapter + 质量门不写库试抓：326/326、119/119 通过，都标抓全。
-- 两个门户都挂着的 17 个岗（index ∩ 757263，两边都在线、都能打开）：14 个淮北「-凯泽」（安徽凯泽新材料，英科医疗
--   持股 65%，公告 2026-051 担保表）、九江安环主管（江西英科医疗厂址）、国毅 / 公益基金会运营各 1 → 归英科医疗。
--   由 adapter 的 _SHARED_TENANT_PORTAL_OWNER 落实：英科再生那条源抓的时候剔掉它们，库里已有的 17 行（0 条用户动作）
--   下架成 removed。迁移 323 写的「凯泽是集团里另一家，跟着门户名走」不对，下面顺手更正那条源的 notes。
-- 已知而没处理的：
--   · board 是派生列：/840753/position 的地址里没有 campus 字样，会派生成 social。逐岗分类不受影响（标题都带
--     「【27届校招】」，119/119 判成校招），日常抓取照常；校招专车道不会按板块选它。
--   · 社招门户 326 个里 211 个发布超过两年（最早 2023-08），门户上都还能投 → 与其它飞书源一致，全收。
--   · 两条源共 41 个越南岗（清化市 / 下龙市）地名表不认，会按源的 regions 记成国内岗（英科再生现有 15 行同病）。
--   · 不带头能取到的 465 个里有 91 个在三个门户上读状态都是 0（哪个公开门户都不挂）→ 不接。
-- ⚠️ 只写 sources 允许直填的列（board 是 generated 列）；industry_group 受 CHECK 约束（迁移 265），'医疗/医药' 是已有取值。
-- Idempotent：insert 按 source_url 防重；notes 更正按本文件的标记串防重；末尾终态断言不成立整批回滚
--   （scripts/db-migrate.sh 用 psql -1 跑，一个文件一个事务）。

set local lock_timeout = '10s';

-- ① 两条新源
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.source_url, 'official', 'feishu', 'http', true, '{CN}',
       'private', '医药医疗', '医疗/医药', 'private', v.notes
from (values
  ('英科医疗', 'https://global-intco.jobs.feishu.cn/757263/position',
   $md$2026-10-12 接入（迁移 332）：英科医疗社会招聘官网。入口取自英科医疗官网招聘页 intcomedical.com.cn/jobs/index.html 的「社会招聘」链接。门户首页自报 title「英科医疗社会招聘官网」、website_info.name「英科医疗-社会招聘官网」、tenant_name「英科」（集团共用租户，租户根路径是英科再生的门户）。带 website-path: 757263 取列表 326 岗，与页面显示的「开启新的工作（326）」一致；逐岗读状态 326/326 在线；浏览器实开详情页能打开。与英科再生门户（index）都挂着的 17 个岗归本源（14 个淮北凯泽岗：安徽凯泽新材料是英科医疗持股 65% 的子公司）。211 个岗发布超过两年，门户上仍可投，全收。$md$),
  ('英科医疗', 'https://global-intco.jobs.feishu.cn/840753/position',
   $md$2026-10-12 接入（迁移 332）：英科医疗校园招聘官网。入口取自英科医疗官网招聘页 intcomedical.com.cn/jobs/index.html 的「校园招聘」链接。门户首页自报 title「英科医疗校园招聘官网」、website_info.name「英科医疗-校园招聘官网」、tenant_name「英科」。带 website-path: 840753 取列表 119 岗（2027 校园招聘 116 / 日常实习生招聘 2 / 2026 校园招聘 1），与页面显示的「开启新的工作（119）」一致；逐岗读状态 119/119 在线；浏览器实开详情页能打开。地址里没有 campus 字样，board 派生列是 social；逐岗分类按标题判成校招。$md$)
) as v(company, source_url, notes)
where not exists (select 1 from public.sources x where x.source_url = v.source_url);

-- ② 更正英科再生那条源的 notes（迁移 323 写的两句话已不成立）
update public.sources
   set notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 更正（迁移 332）：上面两句话不再成立。①「英科医疗一侧的公开门户地址没查到，英科医疗未接」——找到了：同租户的 /757263（社招 326 岗）与 /840753（校招 119 岗），英科医疗官网招聘页自己链过去的，已各接一条源。②「15 个淮北凯泽岗跟着门户名走」——凯泽（安徽凯泽新材料）是英科医疗持股 65% 的子公司，这些岗在英科医疗社招门户上也挂着；两个门户都挂的 17 个岗归英科医疗，本源抓的时候剔掉（adapter 登记 _SHARED_TENANT_PORTAL_OWNER），本门户自己的岗是 70 个。$md$
 where source_url = 'https://global-intco.jobs.feishu.cn/index/position'
   and company = '英科再生'
   and coalesce(notes, '') not like '%更正（迁移 332）%';

-- 终态断言：任何一条不成立，整份迁移回滚
do $$
begin
  if (select count(*) from public.sources
       where source_url in ('https://global-intco.jobs.feishu.cn/757263/position',
                            'https://global-intco.jobs.feishu.cn/840753/position')
         and company = '英科医疗' and adapter_name = 'feishu' and enabled
         and industry_group = '医疗/医药') <> 2 then
    raise exception '332: 英科医疗两条源没有都落成';
  end if;
  if (select count(*) from public.sources
       where source_url like 'https://global-intco.jobs.feishu.cn/%' and enabled) <> 3 then
    raise exception '332: global-intco 租户下 enabled 的源不是恰好 3 条';
  end if;
  if exists (select 1 from public.sources
              where source_url = 'https://global-intco.jobs.feishu.cn/index/position'
                and (company <> '英科再生' or coalesce(notes, '') not like '%更正（迁移 332）%')) then
    raise exception '332: 英科再生那条源的名字或 notes 不对';
  end if;
end $$;
