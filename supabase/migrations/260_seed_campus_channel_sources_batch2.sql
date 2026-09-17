-- 260：秋招校招渠道补源第二批（2026-09-18）——完美世界 / 亿纬锂能 / 华润电力
--
-- 全部走「同一个 ATS 的兄弟板块」，不猜 id、不新增 adapter。每一条都用真实 adapter
-- 端到端探活（fetch → parse → normalizer.validate_job_quality 全过），再抽 3 条 jd_url
-- 丢进 Playwright **真渲染**核对渲染出来的就是那一个岗位（CLAUDE.md：中国 ATS 详情页
-- 多数 JS 渲染，curl 判不了）。探不出岗、或详情页打不开的，本迁移一律没写（清单见文末）。
--
-- ⚠️ 新增「兄弟板块源」之前一律先证明它是**另一批 id**：hotjob 的 jd_url 带 postType，
--    moka 的带 siteId —— 同一个岗若在两个板块下都出现，会算出两个不同的 canonical_jd_url，
--    active 唯一索引拦不住，同岗入库两行（= 影子源，迁移 225 壳牌那种）。
--    本批三条的 id 交集实测均为 0，见各条 notes。
-- board 是 generated 列（school.html / campus-recruitment → campus），不能也不必显式写。

-- ── ① 完美世界：库里那条 campus 源是旧批次子项目，当前活跃的总入口是另一个 siteId ──────
-- 现象：库里 `campus-recruitment/pwrd/140155` 只剩 1 个岗，于是「完美世界 370 个 active 岗、
-- 0 校招」。它不是坏了 —— 它是 2026 届春季校招的**子项目**页（页内锚点 `#/page/25届秋招`），
-- 当前秋招挂在另一个 siteId 上。入口取自 jobs.games.wanmei.com/school.html 顶部导航
-- 「校园招聘」那个 <a href>，**不是猜的**（moka 的 siteId 推不出来，猜=乱爬）。
-- 端到端实测：37 个岗全过质量门（reported_total=37, fetch_complete=True），
-- 抽 3 条真渲染均出对应岗位正文：27届秋招-数值策划（MMO）/ 27届秋招-SLG游戏系统策划 /
-- 27届秋招-游戏C++客户端（发布于 2026-08-26 ~ 09-10），标题自报「27届秋招」。
-- 与 140155 的岗位 id 交集 = 0（140155 现存那 1 个是「产品实习生（人力方向）」）。
-- ⚠️ **刻意不停用 140155**：它仍在产出 1 个有效实习岗、详情页正常渲染，不是 0 产出源。
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
values (
  '完美世界 校招',
  'https://app.mokahr.com/campus-recruitment/pwrd/172467',
  'official', 'moka', 'playwright', true, '{CN}', 'private', '游戏',
  '2026-09-18 端到端探活 37 个校招岗全过质量门（全部「27届秋招-」前缀），抽 3 条 jd_url 真渲染 3/3 命中；'
  '入口取自 jobs.games.wanmei.com/school.html 官网导航自列链接，非猜测。与旧 site 140155 岗位 id 交集=0。'
)
on conflict do nothing;

-- ── ② 亿纬锂能：wecruit 租户一直只登记了 social 板块，校招板块从没接过 ────────────────
-- 端到端实测 school.html：97 个岗全过质量门（reported_total=97, fetch_complete=True），
-- 标题一律「2027-」前缀（2027-财务工程师（湖北）/ 2027-生产管理工程师（启东）/ 2027-IT工程师（惠州）），
-- 抽 3 条真渲染 3/3 命中对应岗位正文（含「学历背景：本科及以上」这类应届口径）。
-- postId 集合对拍：social 1,197 条 ∩ school 97 条 = **0**（不是同一批岗，不会产生影子行）。
-- 同租户 interns.html 实测 reported_total=0，**故意不写**。
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
values (
  '亿纬锂能 校招',
  'https://wecruit.hotjob.cn/SU630487ca0dcad45aa7768a79/pb/school.html',
  'official', 'hotjob', 'http', true, '{CN}', 'private', '锂电',
  '2026-09-18 端到端探活 97 个校招岗全过质量门（全部「2027-」前缀），抽 3 条 jd_url 真渲染 3/3 命中；'
  'postId 与同租户 social 板块交集=0。同租户 interns.html 自报 0 岗，未接。'
)
on conflict do nothing;

-- ── ③ 华润电力：源本来就在，是**淡季被停用后再没开回来** ──────────────────────────────
-- ⚠️ 这条**不是新增**。这条源 2026 年 6 月就存在，连续 8 次以上 `success + jobs_found=0`
--    被按「0 产出源优先 disable」的规矩停用 —— 那是六月，校招板块本来就空。
--    校招板块是**有季节性的**：淡季 0 产出 → 停用 → 秋招开了也没人开回来，整个秋招季这条渠道是瞎的。
--    2026-09-18 实测 school.html 有 74 个岗（reported_total=74, fetch_complete=True），
--    抽 3 条真渲染 3/3 命中（新能源运行工程师HNGZ / 新能源技术监督工程师（光伏方向）JSYJY /
--    火电运维工程师HNYF），正文写着「本科及以上」「成长路径：巡检-副值-主值-值长」= 应届培养口径。
--    postId 集合对拍：social 100 条 ∩ school 74 条 = **0**（不是同一批岗）。
-- 📌 **通用教训**：给 board in ('campus','intern') 的源做「0 产出 → disable」判断时，必须带上
--    「现在是不是校招季」这个前提，否则每年秋招都要靠人肉重新发现一遍。
--    同批复查了全部 12 条被停用的 campus/intern 源，其余 11 条**确认不该开**（见文末清单）。
update public.sources
   set enabled = true,
       notes = coalesce(notes || ' | ', '') ||
               '2026-09-18 重新启用：2026-06 淡季连续 success+0 岗被停用，秋招已开。'
               '端到端探活 74 个校招岗全过质量门，抽 3 条 jd_url 真渲染 3/3 命中；'
               'postId 与同租户 social 板块交集=0。同租户 interns.html 自报 0 岗，未接。'
 where source_url = 'https://wecruit.hotjob.cn/SU6149ff530dcad47003d01511/pb/school.html'
   and enabled = false;

-- ── 同批探活未过、**刻意不写**的（留证据，省得下一个人再挖一遍）──────────────────────
--   中信银行信用卡中心 school.html：列表接口返 10 个岗，但 jd_url 真渲染是「官网不存在，无法继续访问!」
--     —— 同租户的 social 板块**也一样**（库里那 164 行已全部 removed）。即该 wecruit 租户的
--     公开门户不在 wecruit.hotjob.cn 这个 host 上（同「中国中化搬家」那一类）。写它只会新增死链。
--   李宁 school.html（SU6018f8695d83dc072073e990）：只有 1 个岗「绩效管理7275」，
--     而它与库里已有的老版 wt 源 lining.hotjob.cn recruitType=1 返回的是**同一个岗**
--     —— 两个门户各有一套 postId ⇒ 接了就是同岗两行。李宁校招渠道已由 wt 源覆盖（board=mixed）。
--   盒马 hire.freshippo.com/campus/position-list：接口自报 0 条。
--   郑州银行 / 赢家时尚 / 上海瑞金医院 school.html：接口自报 0 条。
--   中海油国聘 &nature=115xW5oQ：listed=400 但归属核名 matched=0（国聘搜索是集团级模糊匹配，
--     核名门按设计拦下，与迁移 255 里那 10 家同一类）。**不放开核名**。
--   亿纬锂能 / 华润电力 interns.html：自报 0 条。
--
-- ── 另外 11 条被停用的 campus/intern 源逐条复查结论（2026-09-18 live，**都维持停用**）────
--   吉利 app.mokahr.com/campus-recruitment/geely/78436（探活 2,242 岗）—— 岗是真的，但它与
--     **已启用**的 campus.geely.com/campus-recruitment/geely/78436 是同一个 moka 门户的两个 host，
--     开了就是同岗两行（库里 `吉利汽车` 已有 2,269 个校招岗，正是那条在供）。这是迁移 225 壳牌那一类。
--   中兴通讯 .../zte/94063（1 岗「中兴捧月」）—— 已启用的是 .../zte/46903（库里 60 个校招岗）。
--   搜狐 .../campus_apply/sohu/5682 —— 与已启用的 .../campus-recruitment/sohu/5682 同一个 site，两种写法。
--   东风汽车 dfmc.hotjob.cn school/interns —— 已由已启用的 moka .../dfmc/164438 覆盖（库里 322 校招岗）；
--     且该 host 本机 httpx 直接 `ConnectError: EOF occurred in violation of protocol`（国内门户 TLS 那一类）。
--   中国中化 wecruit SU611a641a… —— 门户已下线，迁移 259 已处理。
--   携程 .../trip/37757 —— 迁移 249 判定为重复源，已停用。
--   幻方量化 / 第四范式 / 阿克苏诺贝尔 —— 探活 0 岗。
--   耐世特 .../nexteer/92644 —— 探活 2 个真校招岗（耐世特亚太工程技术中心研发管培生），库里该公司
--     0 校招岗，**不是重复源**；但本轮没做逐岗真渲染核验，按「没验过不写」的规矩留到下一批。
