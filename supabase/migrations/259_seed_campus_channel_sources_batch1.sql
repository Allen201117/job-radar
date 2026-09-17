-- 259：秋招校招渠道补源第一批（2026-09-17）——京东方 / 中国中化 / 万科
--
-- 每一条都**用真实 adapter 端到端探活过**：fetch → parse → normalizer.validate_job_quality 全过，
-- 再抽样把 jd_url 丢进 Playwright 真渲染、核对渲染出来的就是那一个岗位
-- （CLAUDE.md：中国 ATS 详情页多数 JS 渲染，curl 判不了）。0 岗的一律没写。

-- ── ① 京东方（必投清单，台账记「校招渠道 missing」）────────────────────────────────
-- 它的北森官方门户一直在，只是库里从来没有这条源；台账里只有一条国聘通用搜索源，
-- 而国聘对「京东方」是模糊分词（346 条结果里 0 条是 BOE，捞回来的是「宁波吉德电器」
-- 「东方市人社局」「中国东方电气」），等于没有。
-- 门户自报主体：<title>京东方科技集团股份有限公司</title>（2026-09-17 实测）。
-- 端到端实测：解析 1,076 个岗全部过质量门，其中北森自报「校园招聘」699 个、社会招聘 373、海外 3；
-- 抽 2 个 jd_url 真渲染，渲染出的正是对应岗位（产品经理岗 / 采购企划岗）。
-- ⚠️ 这条源在 2026-09-17 之前**接不出岗**：beisen_routes.json 里 boe.zhiye.com 留着过期的
--    `{ssr_path:"zwxq"}` 登记，配不了新版接口的 uuid → 每行 jd_url 空串 → 整源 0 岗且不报错。
--    已在同一批改动里修掉（crawler/adapters/china_ats.py），没有那个修复这条源写了也白写。
-- board 是 generated 列（adapter=beisen → mixed），不能也不必显式写。
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
values (
  '京东方 BOE',
  'https://boe.zhiye.com/social',
  'official',
  'beisen',
  'http',
  true,
  '{CN}',
  'private',
  '显示面板·半导体',
  '2026-09-17 端到端探活：1076 岗全过质量门（北森自报校园招聘 699）；门户 title 自报「京东方科技集团股份有限公司」。'
)
on conflict do nothing;

-- ── ② 中国中化：门户搬家了，不是对方关门 ────────────────────────────────────────
-- 旧的 wecruit 租户 SU611a641a… 近 7 天 111 次抓取 0 次成功，错误恒为
-- 「wecruit portal does not exist (suite/config has no site settings): pages show 官网不存在」。
-- 这句话是**我们这边的观测**，很容易被读成「中化不招人了」——实际是租户换了域名和 suiteKey：
-- 真门户在 sinochem.hotjob.cn / SU610b91ee0dcad4106ff11c21，2026-09-17 端到端实测全部抓通且抓全：
--   school.html  595 个校招岗（fetch_complete=True，reported_total=595）
--   interns.html  18 个实习岗
--   social.html  383 个社招岗
-- 抽 3 个详情页真渲染：总部管理培训生（薪火计划）/ 雏凤计划：化工工艺研发工程师 /
-- 市场产品线实习生（2027届）—— 3/3 渲染出对应岗位正文。门户 title 自报「中国中化招聘官网」。
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
values
  ('中国中化 ChemChina 校招',
   'https://sinochem.hotjob.cn/SU610b91ee0dcad4106ff11c21/pb/school.html',
   'official', 'hotjob', 'http', true, '{CN}', 'private', '化工·央企',
   '2026-09-17 端到端探活 595 个校招岗全过质量门；取代已下线的 wecruit SU611a641a… 门户。'),
  ('中国中化 ChemChina 实习',
   'https://sinochem.hotjob.cn/SU610b91ee0dcad4106ff11c21/pb/interns.html',
   'official', 'hotjob', 'http', true, '{CN}', 'private', '化工·央企',
   '2026-09-17 端到端探活 18 个实习岗全过质量门。'),
  ('中国中化 ChemChina',
   'https://sinochem.hotjob.cn/SU610b91ee0dcad4106ff11c21/pb/social.html',
   'official', 'hotjob', 'http', true, '{CN}', 'private', '化工·央企',
   '2026-09-17 端到端探活 383 个社招岗全过质量门；取代已下线的 wecruit SU611a641a… 门户。')
on conflict do nothing;

-- 旧租户两条源停用（**不删**，保留行可回滚，见 CLAUDE.md「0 产出的源优先 disable」）。
-- 它们不是「抓法不对」，是门户本身不存在了：adapter 的 should_skip 门 1 与 Playwright 真渲染
-- 都确认页面文案就是「官网不存在，无法继续访问!」。留着只会每天空烧 111 次并把 failed 刷满台账。
update public.sources
   set enabled = false,
       notes = coalesce(notes || ' | ', '') ||
               '2026-09-17 停用：wecruit 租户 SU611a641a… 门户已下线（页面自报「官网不存在」），'
               '近 7 天 33/33 次 failed。真门户已迁到 sinochem.hotjob.cn/SU610b91ee0dcad4106ff11c21，本迁移同批新增。'
 where id in ('ea174799-e4ab-465b-b828-66fa7a8afa13',   -- 中国中化 ChemChina（社招）
              'a2a17f04-ed50-4aaf-afd2-8454168a5974');  -- 中国中化 ChemChina 校招

-- ── ③ 万科：校招门户是另一个 portal id，猜不出来，从万科官网自己给的链接拿到 ──────────
-- moka 的 `social-recruitment/<slug>/<id>` 推不出 campus 的 id（禁止猜），入口取自
-- www.vanke.com/mobile/join/talent 页面自己列出的链接。
-- 端到端实测：2 个岗全过质量门（fetch_complete=True, reported_total=2），
-- 两个 jd_url 真渲染均出对应岗位正文（经营管理方向-储备店长 / 科技赋能方向-开发工程师）。
-- ⚠️ 诚实边界：门户 title 写的是「万科集团2024新动力校园招聘」，是个旧批次的壳，眼下只有 2 个岗。
--    写它是因为「真有在招岗 + 详情页真的打得开」，不是因为它看起来气派。
-- ⚠️ 同页还列了万物云 / 印力的校招入口，是**不同法人主体**，不并进万科（归属准确性高于覆盖率）。
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
values (
  '万科企业 校招',
  'https://app.mokahr.com/campus-recruitment/vanke/37550',
  'official', 'moka', 'playwright', true, '{CN}', 'private', '地产',
  '2026-09-17 端到端探活 2 个校招岗全过质量门；入口取自 vanke.com 官网自列链接，非猜测。'
)
on conflict do nothing;
