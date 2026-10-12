-- 328 — 好未来校招：停用被跳走的 Moka 门户源，改接官方自建站 job.tal.com（adapter = tal，三个站点三条源）
--
-- ── 为什么 ──
--   源 app.mokahr.com/campus-recruitment/tal/146099（库里公司名「好未来」）最后一次抓到岗是 2026-09-09（726 个），
--   09-13 起每轮失败「moka job list not found on any route」。门户没关：Moka 把这个路径 302 到了好未来自己写的
--   前端 https://job.tal.com/campus/xes/home（第一跳就跳，不看 cookie）。
--   库里这条源名下 987 个在招行，2026-10-12 用真浏览器逐个打开：打得开 0 / 打不开 987 / 看不清 0，
--   全部落在 job.tal.com 学而思校招首页。巡检对这个落地页 956 行判「标题不在」只盖时间戳、31 行因首页上有同名
--   项目词被判在招，一个月一行都没下架；必投台账里「好未来」的 healthy（健康岗 983）全靠这批行撑着。
--
-- ── 新站是什么（2026-10-12 实测，细节见 crawler/adapters/tal.py 与 docs/crawler-adapter-notes.md）──
--   job.tal.com 用的岗位号就是 Moka 的 uuid，换了前端和接口。三个站点各有自己的「在招职位」页：
--     /campus            好未来招聘官网（集团）  列表自报 139（含下面两个站的岗）
--     /campus/xes        学而思校园招聘          列表自报 30
--     /campus/xesonline  学而思网校校园招聘      列表自报 15
--   逐岗详情页 /positions/<岗位号> 匿名可开、有「申请职位」；列表接口匿名可取、正文在列表里。
--   三个主机的 robots.txt 都是 404（无限制）；BaseAdapter.should_skip 对三个源地址 HEAD 都是 200。
--   本机端到端（should_skip → fetch → parse → 质量门 → normalize → 分类，不写库）：
--     好未来 91（139 剔掉两个品牌站的 45 个、占位岗 1 个、无标题 0）/ 学而思 30 / 学而思网校 15，共 136；
--     质量门 136/136，三条源之间岗位号重复 0，正文 ≥60 字 136/136，抓全标记三条都是 true。
--   ⚠️ 本机是境内网络。CI 的 runner 在境外，连不连得上 job-api.100tal.com 上线前验不了，
--      以上线后的 crawl_runs 为准（接不通就是三条 failed，不会安静成功）。
--
-- ── 归属 ──
--   三个站点页面标题各自报「好未来招聘官网」「学而思校园招聘」「学而思网校校园招聘」，按站点各挂一条源；
--   集团那条源会剔掉另外两个站列出的岗，同一个岗不会两条源各写一行。
--   洞察画像：三个名字是同一家公司的牌子（现有别名里已有「好未来（学而思）」），给画像「好未来」登记别名，
--   不让岗位库冒出「学而思」「学而思网校」两个新画像。
--
-- ── 没接的 ──
--   Moka 后台里按分校拆开的岗（「…-昆明分校-27校招」，库里 632 个还在招）官网列表不列、只列一个角色配多个城市的
--   合并岗；新源只跟官网列表走。旧门户的 campus_apply/tal/146099 别名今天还开着，没接：官方已把主路径指走。
--
-- ── 配套（迁移之外）──
--   旧源名下 987 个在招行用 remove-jobs-by-url-prefix.yml 标 removed（可逆、purge 不删）：
--     url_prefix = https://app.mokahr.com/campus-recruitment/tal/146099#   company = 好未来
--   同租户社招源 social-recruitment/tal/118640（公司名「好未来（学而思）」）不动。
--
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
-- 回滚：update sources set enabled = false where adapter_name = 'tal';
--        update sources set enabled = true where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099';
--        （画像别名留着无害；要撤就从 company_profiles.aliases 里去掉那两个名字）

-- ── A. 停用被跳走的 Moka 校招门户源（行保留，可回滚）────────────────────────────────
update public.sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 停用：Moka 把本门户的 campus-recruitment 路径 302 到好未来自建站 job.tal.com（学而思校招首页），09-13 起每轮失败；库里 987 个在招行的链接真浏览器逐个打开全部落在新站首页。改由 adapter tal 的三条源接官方站点。保留行可回滚。$md$
 where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099'
   and adapter_name = 'moka'
   and enabled;

-- ── B. 三个站点三条源（行业 / 归属列沿用旧校招源的取值）──────────────────────────────
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.source_url, 'official', 'tal', 'http', true, '{CN}',
       s.segment, s.industry, s.industry_group, s.ownership, v.notes
from public.sources s
cross join (values
  ('好未来', 'https://job.tal.com/campus/positions',
   $md$2026-10-12 接入：好未来招聘官网（集团校招站）。列表接口匿名可取、逐岗详情页匿名可开；集团站列表含学而思 / 学而思网校两个站的岗，本源剔掉它们。本机端到端 91 岗，质量门 91/91。取代被跳走的 Moka 门户 campus-recruitment/tal/146099。$md$),
  ('学而思', 'https://job.tal.com/campus/xes/positions',
   $md$2026-10-12 接入：学而思校园招聘站（Moka 门户 146099 现在跳到的就是这个站）。官网只列一个角色配多个城市的合并岗，不列按分校拆开的岗。本机端到端 30 岗，质量门 30/30。$md$),
  ('学而思网校', 'https://job.tal.com/campus/xesonline/positions',
   $md$2026-10-12 接入：学而思网校校园招聘站。本机端到端 15 岗，质量门 15/15。$md$)
) as v(company, source_url, notes)
where s.source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099'
  and s.adapter_name = 'moka'
  and not exists (select 1 from public.sources x where x.source_url = v.source_url);

-- ── C. 画像「好未来」登记两个牌子的别名（已有的不重复加）──────────────────────────────
update public.company_profiles cp
   set aliases = coalesce(cp.aliases, '{}') || coalesce(
         (select array_agg(x) from unnest(array['学而思', '学而思网校']) as x
           where x <> all (coalesce(cp.aliases, '{}'))), '{}'),
       updated_at = now()
 where cp.company = '好未来'
   and not exists (
     select 1 from public.company_profiles o
      where o.id <> cp.id
        and (o.company in ('学而思', '学而思网校') or o.aliases && array['学而思', '学而思网校'])
   );

-- ── D. 没生效就让迁移红，别装成功 ───────────────────────────────────────────────────
do $$
declare
  n_new int;
begin
  if exists (select 1 from public.sources
              where source_url = 'https://app.mokahr.com/campus-recruitment/tal/146099' and enabled) then
    raise exception '328: 旧 Moka 校招源还是启用状态（source_url / adapter_name 没匹配上？）';
  end if;
  select count(*) into n_new from public.sources
   where adapter_name = 'tal' and enabled
     and source_url in ('https://job.tal.com/campus/positions',
                        'https://job.tal.com/campus/xes/positions',
                        'https://job.tal.com/campus/xesonline/positions');
  if n_new <> 3 then
    raise exception '328: job.tal.com 三条源应有 3 条启用，实际 %（旧校招源那一行没匹配上？）', n_new;
  end if;
  if exists (select 1 from public.company_profiles where company = '好未来')
     and not exists (select 1 from public.company_profiles
                      where company = '好未来' and aliases @> array['学而思', '学而思网校']) then
    raise exception '328: 画像「好未来」的别名没登记上（另有画像占着「学而思」/「学而思网校」？需要人来判）';
  end if;
end $$;
