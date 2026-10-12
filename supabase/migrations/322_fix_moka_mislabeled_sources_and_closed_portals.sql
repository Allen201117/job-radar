-- 322 — Moka：4 条挂错公司名的源纠名、9 条门户已关停的源停用、换接 / 补接 6 条源（2026-10-12，创始人同日同意）
--
-- 逐条证据、全集数字与没验到的边界：docs/reviews/2026-10-11-moka-source-identity-and-closed-portals.md
-- 起因：10-11 全量普查（417 条 Moka + 379 条北森）点名 6 条「源名对不上门户自报」和 8 条「门户已关停」，逐条核完后的处置。
--
-- ── A. 纠名（门户页自报是谁就叫谁；探活出岗 ≠ 归属正确，同 248 / 274 / 291 / 311 / 312）──
--   ① social-recruitment/weiboyi/28976：记成「北京微播视界科技有限公司」（抖音的运营主体），门户自报
--      「北京微播易科技股份有限公司」，页面介绍「微播易——全域KOL内容&电商整合营销平台」；18 个岗是 AE / 媒介 / 策划。
--      来处是迁移 129：清单那行的行业（MCN/营销）和租户代号都是微播易的，只有公司名字段写错。
--   ② social-recruitment/high-flyer/140576：记成「幻方量化 High-Flyer」，页面标题与门户名都是「DeepSeek招聘」；
--      DeepSeek 官方招聘站 talent.deepseek.com 的脚本里写死的投递链接就是本门户；37 个岗全是大模型研发 / 产品岗，
--      正文 10 处写 DeepSeek、0 处写幻方或量化。幻方自己的门户是同租户的 4604（见 C）。
--   ③ social-recruitment/continental/56212：记成「大陆汽车电子（芜湖）有限公司」，门户自报
--      「大陆芯智驾（上海）智能科技有限公司」（页头 Continental Smart Core），32 个岗是智能驾驶算法 / 软件，整页没有「芜湖」。
--      **同时停用**：页面数据带出来的首屏 15 个岗最晚一次更新是 2024-04-16，库里这 32 行四个月没增没减；
--      媒体报道这家合资公司已先后改名智驾大陆、智驾新程（不是官方公告）。「门户没人维护」只有这两条旁证，
--      所以存量走 removed（可逆），不判撤岗。
--   ④ campus-recruitment/megviihr/146855：记成「旷视科技」，页面标题「极感科技校园招聘」、门户名「【极感】校招门户」，
--      整页没有旷视字样；同租户另有「【旷视】校招门户」38642（见 C）。极感与旷视的关系公开资料没查到，按门户自报改。
--   没改的两条（核过、没挂错，notes 里记一笔免得下次普查再点名）：
--      · campus-recruitment/pengwin/145331「鹏景科技 Pengwin」：门户自报「原子朋克」，但同页页脚「版权所属山西鹏景科技有限公司」、
--        导航「关于鹏景」、正文「在鹏景…」——原子朋克是鹏景在招聘门户上用的名字。
--      · social-recruitment/crland/143066「华润万象生活」：租户是华润置地的、门户自报「华润置地」，但 265 个岗里 257 个的部门
--        沿部门树挂在「华润万象生活」节点下，正文 7 处写万象生活、0 处写华润置地；改成华润置地会让必投「华润万象生活」变零源。
--
-- ── B. 停用 9 条门户已关停的 Moka 源（保留行可回滚）──
--   门户页整页只有「当前网页已关停」（Meshy 的 apply 门户是英文版 "This website has been shut down"）；
--   7 个租户的社招 / 校招 / apply 三个无编号别名共 21 个地址全读过，全是关停页——不是换了门户编号，是整个租户停了。
--   各自最后一次抓到岗：流利说 07-20 / 仙工 07-30 / 人福 09-02 / 观远 09-07 / 游卡 09-13 / 国药试剂 09-18 /
--   Meshy 09-29 / 真格基金 06-29；之后每轮失败（09-13 之前记的是「成功 0 岗」）。名下 235 个在招岗点开全是关停页，
--   存量走 remove-jobs-by-url-prefix.yml 标 removed。
--   ⚠️ 为什么敢停：这 9 条关了 12 天 ~ 11 周。Moka 门户确实会临时关停（阿克苏诺贝尔 2 天、云顶新耀 4 天后原样恢复），
--      所以「看到关停页」本身不构成停用理由；判据是「连续关停超过一周 + 官网招聘链接已不指向它（或官网已无入口）」。
--
-- ── C. 换接 / 补接 6 条源（接入前 live 验过，见下；均未写库）──
--   仙工、Meshy 的招聘搬到了飞书招聘，官网链接为证：
--     · seer-group.com → seer-robotics.ai，「加入我们 / Join Us」指向 seer-group.jobs.feishu.cn/index；门户 meta「到仙工智能，开启你的新工作」。
--     · meshy.ai/careers 页面数据里 44 条岗位链接指向 o9ixctz0o7.jobs.feishu.cn/welcometomeshyai/…；门户标题「加入Meshy AI」。
--       （同页另挂一套 Ashby 岗位 27 个，含美加；与飞书那套有没有重复没逐条比，本迁移不接。）
--   幻方量化、旷视科技各补一条它们自己的门户（纠名之后，这两个名字名下要有它们自己的岗）：
--     · 幻方官网 high-flyer.cn/join 的招聘链接指向 apply/high-flyer/4604（= social-recruitment/high-flyer/4604），3 个岗。
--     · campus_apply/megviihr → 38642，页面标题「旷视MEGVII校园招聘」、门户名「【旷视】校招门户」，3 个岗。
--   接入前 live 验过（2026-10-12；每条源新建 adapter 实例，robots → should_skip → fetch → parse → validate_job_quality →
--   normalize，不写库；详情页**逐岗全部真渲染**后用巡检的 classify 判，不是抽样）：
--     · Meshy 社招 …/index/position        44 岗 = 自报 44，抓全，质量门 44/44，详情页 44/44 在线且有投递按钮（43 国内 + 1 东京）
--     · Meshy 校招 …/Meshycampus/position  28 岗 = 自报 28，抓全，质量门 28/28，详情页 28/28 在线
--     · 仙工 社招 …/index/position         49 岗 = 自报 49，抓全，质量门 49/49，详情页 49/49 在线
--     · 仙工 校招 …/campus/position        37 岗 = 自报 37，抓全，质量门 37/37，详情页 37/37 在线
--     · 幻方 …/social-recruitment/high-flyer/4604   3 岗 = 自报 3，抓全，质量门 3/3，详情页 3/3 在线
--     · 旷视校招 …/campus_apply/megviihr/38642      3 岗 = 自报 3，抓全，质量门 3/3，详情页 3/3 在线
--   ⚠️ 试抓在本机跑：Playwright 驱动系统已装的 Chrome + 国内出口；CI 是自带 chromium + 境外出口，上线后以线上 crawl_runs 为准。
--   ⚠️ 飞书主门户的源地址一律写 /index/position：把自定义门户名（welcometomeshyai）当源地址，adapter 会按「子门户」去取，
--      详情前缀对不上被判「门户已关」。主门户由 adapter 自己读租户自报的门户前缀。
--   观远数据的北森门户（guandata.zhiye.com，27 岗）没接：官网没有链接指向它，仓库的北森 adapter 也还拼不出它的详情地址。
--
-- ── D. 洞察：旧归属下由岗位库派生的指标撤下（同 311 ③ / 312）──
--   纠名 / 停用之后，这些画像名下的岗要么归了别家、要么已经关停，「在招 N 个 / 城市分布 / 职能分布」都是拿错的岗或死岗算的。
--   派生任务对一个岗都没有的公司不会自己撤。只动 origin='derived'；下一轮派生按新归属重算（旷视、幻方、Meshy、仙工有真岗的会重新长出来）。
--
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
-- ⚠️ 存量岗（香港库）不归本迁移管：改名走 rename-job-company.yml（微播易 / DeepSeek / 极感科技三条），
--    下架走 remove-jobs-by-url-prefix.yml（大陆芯智驾 + 9 条关停门户）；都要等在飞的抓取轮过完这些源再 apply。
-- Idempotent：update 的 where 带旧公司名 / enabled / status='active'，insert 带 not exists，重复执行无副作用。
-- 回滚：纠名按 notes 里记的旧名改回；停用的 update sources set enabled=true where source_url in (…)；
--        新接的 update sources set enabled=false where source_url in (C 的 6 个地址)。

-- ── A. 纠名 ──────────────────────────────────────────────────────────────────
update sources
   set company = '微播易',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「北京微播视界科技有限公司」纠正为「微播易」：Moka 租户 weiboyi 页面自报「北京微播易科技股份有限公司」（KOL 营销平台）；微播视界是抖音的运营主体，与这个门户无关。$md$
 where source_url = 'https://app.mokahr.com/social-recruitment/weiboyi/28976'
   and company = '北京微播视界科技有限公司';

update sources
   set company = 'DeepSeek',
       industry = '人工智能',
       industry_group = '互联网/科技',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「幻方量化 High-Flyer」纠正为「DeepSeek」：门户 140576 页面标题与门户名都是「DeepSeek招聘」，talent.deepseek.com 的投递链接指向本门户，37 个岗全是大模型研发 / 产品岗。幻方自己的门户是同租户 4604。$md$
 where source_url = 'https://app.mokahr.com/social-recruitment/high-flyer/140576'
   and company = '幻方量化 High-Flyer';

update sources
   set company = '大陆芯智驾',
       industry = '智能驾驶',
       enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「大陆汽车电子（芜湖）有限公司」纠正为「大陆芯智驾」（门户自报「大陆芯智驾（上海）智能科技有限公司」，页头 Continental Smart Core），并停用：首屏 15 个岗最晚更新于 2024-04-16，库里 32 行四个月没增没减，媒体报道公司已改名智驾大陆 / 智驾新程——门户多半没人维护了（只有旁证）。保留行可回滚。$md$
 where source_url = 'https://app.mokahr.com/social-recruitment/continental/56212'
   and company = '大陆汽车电子（芜湖）有限公司';

update sources
   set company = '极感科技',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 公司名由「旷视科技」纠正为「极感科技」：门户 146855 页面标题「极感科技校园招聘」、门户名「【极感】校招门户」，整页没有旷视字样；旷视自己的校招门户是同租户 38642。$md$
 where source_url = 'https://app.mokahr.com/campus-recruitment/megviihr/146855'
   and company = '旷视科技';

-- 核过、没挂错的两条：只在 notes 里记一笔（公司名不动）
update sources
   set notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 核过归属：门户自报公司名是「原子朋克」，但同页页脚「版权所属山西鹏景科技有限公司」、导航「关于鹏景」、正文「在鹏景…」——原子朋克是鹏景在招聘门户上用的名字，源名没挂错。$md$
 where source_url = 'https://app.mokahr.com/campus-recruitment/pengwin/145331'
   and company = '鹏景科技 Pengwin'
   and coalesce(notes, '') not like '%2026-10-12 核过归属%';

update sources
   set notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 核过归属：租户 crland 是华润置地的、门户自报「华润置地」，但门户自报的 265 个岗里 257 个的部门沿部门树挂在「华润万象生活」节点下（商业航道各大区 / 物业航道各城市公司），正文 7 处写万象生活、0 处写华润置地——源名没挂错，别改成华润置地。$md$
 where source_url = 'https://app.mokahr.com/social-recruitment/crland/143066'
   and company = '华润万象生活'
   and coalesce(notes, '') not like '%2026-10-12 核过归属%';

-- ── B. 停用门户已关停的 9 条 Moka 源 ─────────────────────────────────────────────
update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 停用：Moka 门户页整页只有「当前网页已关停」（该租户的社招 / 校招 / apply 三个别名地址同样关停），已连续关停超过一周。保留行可回滚。去向见迁移 322 头注。$md$
 where source_url in (
         'https://app.mokahr.com/apply/taichi/148086',
         'https://app.mokahr.com/campus-recruitment/taichi/41025',
         'https://app.mokahr.com/social-recruitment/seer/41526',
         'https://app.mokahr.com/social-recruitment/humanwell/148229',
         'https://app.mokahr.com/social-recruitment/guandata/36965',
         'https://app.mokahr.com/social-recruitment/sinopharm/56224',
         'https://app.mokahr.com/campus_apply/liulishuo/2402',
         'https://app.mokahr.com/campus_apply/yokagames/41940',
         'https://app.mokahr.com/apply/zhenfund/39989')
   and enabled;

-- ── C. 换接 / 补接 ───────────────────────────────────────────────────────────
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', v.adapter, v.method, true, '{CN}', 'private', v.industry, v.industry_group, 'private', v.notes
from (values
  ('Meshy', 'https://o9ixctz0o7.jobs.feishu.cn/index/position', 'feishu', 'http', 'AI·3D', '互联网/科技',
   '2026-10-12 接入：官网 meshy.ai/careers 的岗位链接指向本门户（o9ixctz0o7.jobs.feishu.cn/welcometomeshyai），门户标题「加入Meshy AI」。取代已关停的 Moka apply/taichi/148086。'),
  ('Meshy', 'https://o9ixctz0o7.jobs.feishu.cn/Meshycampus/position', 'feishu', 'http', 'AI·3D', '互联网/科技',
   '2026-10-12 接入：飞书门户导航「校园招聘」指向本门户。取代已关停的 Moka campus-recruitment/taichi/41025。'),
  ('上海仙工智能科技有限公司', 'https://seer-group.jobs.feishu.cn/index/position', 'feishu', 'http', 'AMR移动机器人/调度系统', '制造/工业',
   '2026-10-12 接入：官网 seer-group.com（跳 seer-robotics.ai）「加入我们」指向本门户，门户 meta「到仙工智能，开启你的新工作」。取代已关停的 Moka social-recruitment/seer/41526。'),
  ('上海仙工智能科技有限公司', 'https://seer-group.jobs.feishu.cn/campus/position', 'feishu', 'http', 'AMR移动机器人/调度系统', '制造/工业',
   '2026-10-12 接入：飞书门户导航「校园招聘」指向本门户（多为实习）。'),
  ('幻方量化 High-Flyer', 'https://app.mokahr.com/social-recruitment/high-flyer/4604', 'moka', 'playwright', '量化投资', '金融',
   '2026-10-12 接入：幻方官网 high-flyer.cn/join 的招聘链接指向本门户（apply/high-flyer/4604 同一门户），3 个岗。同租户的 140576 是 DeepSeek 的门户，别混。'),
  ('旷视科技', 'https://app.mokahr.com/campus_apply/megviihr/38642', 'moka', 'playwright', '人工智能', '互联网/科技',
   '2026-10-12 接入：租户校招别名 campus_apply/megviihr 指向本门户，页面标题「旷视MEGVII校园招聘」、门户名「【旷视】校招门户」，3 个岗。同租户的 146855 是极感科技的门户，别混。')
) as v(company, url, adapter, method, industry, industry_group, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);

-- ── D. 撤下旧归属下派生的在招指标 ─────────────────────────────────────────────────
update insight_items
   set status = 'retired',
       updated_at = now()
 where company_id in (
         select id from company_profiles
          where company in (
            -- 纠名前的旧名（名下的岗归了别家）；旷视、幻方有自己的真岗，下一轮按真岗重算
            '北京微播视界科技有限公司', '幻方量化 High-Flyer', '大陆汽车电子（芜湖）有限公司', '旷视科技',
            -- 门户关停的（Meshy、仙工换接飞书后下一轮重算）
            'Meshy', '上海仙工智能科技有限公司', '人福医药集团股份公司', '北京观远数据有限公司',
            '国药集团化学试剂有限公司（国药控股）', '流利说 LAIX', '游卡', '真格基金 ZhenFund'))
   and origin = 'derived'
   and status = 'active';
