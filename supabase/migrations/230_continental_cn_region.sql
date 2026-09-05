-- 大陆集团（Continental）：给已有的 SmartRecruiters 源补上 CN 抓取地区。
--
-- 病根不是「没有中国招聘入口」，而是**这条源自己把中国岗过滤掉了**：regions 是 {US,SG,Remote}，
-- 而 crawler/adapters/smartrecruiters.py 在 parse 与 _enrich_descriptions 两处都调
-- normalizer.location_in_source_regions(location, self.regions)，CN 不在里面 ⇒ 中国岗直接丢弃，
-- 而 status 照样 success、没有任何失败信号。
--
-- 2026-09-05 live 实测（不是推断）：
--   · api.smartrecruiters.com/v1/companies/continental/postings?country=cn → totalFound=29
--   · jobs.continental.com（TYPO3 前台，POST tx_conjobs_api[itemsPerPage]=100 翻完 8 页）
--     736 条里 countryLabel='China' 的正好也是 29 条，REF 号逐个对得上；且每条都带
--     smartRecruitersId + client:continental ⇒ 官网门户就是 SmartRecruiters 的皮，
--     与我们已用的是**同一个池子**，不需要新增源。
--   · 逐岗详情页抽 3 个实测：https://jobs.smartrecruiters.com/Continental/{id} → HTTP 200，
--     <title> 与岗位名一致（Head of ESH Plant PUD / Tactical Category Manager / O2O 2.0…）。
--
-- ⚠️ 刻意不新增第三条源：这家已有 smartrecruiters + moka（大陆汽车电子（芜湖），
--    portal_identity = continental/56212）两条，再插一条就是迁移 225 壳牌那种影子源。
--
-- ⚠️ 只补 regions 还不够，要配合同批的 geo 改动（认小写 ISO 国别码 "cn"）：
--    这 29 个岗里 8 个的地点是空格分词拼音 + 国别码（"He Fei Shi, An Hui Sheng, cn"），
--    与 CHINA_LOCATION_MARKERS 里的 hefei/ningbo 按词边界一个都对不上 ⇒ code=None ⇒
--    location_in_scope 落 False 分支 ⇒ 补了 CN 也照样被丢。两个改动缺一不可。
update sources
   set regions = array['CN', 'US', 'SG', 'Remote'],
       notes = 'auto_discover: live探活 48 岗；2026-09-05 补 CN 抓取地区（该源同时供给中国岗，'
               || 'live 实测 country=cn 29 岗，逐岗详情页 jobs.smartrecruiters.com/Continental/{id} 实测 200）'
 where source_url = 'https://api.smartrecruiters.com/v1/companies/continental/postings?limit=100';

-- ── 缺口台账：纠正一条会误导排查方向的错误结论 ────────────────────────────────────
-- 台账里「大陆集团」的 official_entry_url 存的是 **https://jobs.lenovo.com/zh_CN/careers
-- （联想的招聘页）** —— 搜「大陆集团」把联想搜出来了。身份核验门挡住了它没入库（红线没破），
-- 但这个错误入口被当成结论存了下来，而 gap_census.classify_company 里
-- `"official_entry_url": prev.get("official_entry_url")` 会把它原样带过每一轮。
-- fail_reason 记的「P1 httpx 道无可用 adapter」同样是错的：adapter 一直都在，且一直在跑。
--
-- ⚠️ 刻意不写 state / next_retry_at：它们是 classify_company 每轮按岗位数重算的
-- （现在是 no_active_jobs —— 别名 + scope 拆分上线后如实反映「国内 0 岗」，正是本迁移要治的）。
-- 手写会被下一轮覆盖，还会掩盖真实状态。本迁移只改 census 会原样保留的那几个字段。
update must_apply_gap_attempts
   set official_entry_url = 'https://jobs.continental.com/en/',
       detected_platform = 'smartrecruiters',
       source_id = 'a3e25d62-b7c4-4252-9e3a-c39d4df39fa5'::uuid,
       fail_reason = '此前记的「无可用 adapter」是错的：adapter 与源一直都在，是 regions 缺 CN '
                     || '把中国岗过滤掉了（迁移 230 已补）。此前记的官方入口是联想的招聘页，搜错了公司。',
       evidence = evidence || jsonb_build_object(
         'manual_note_2026_09_05', jsonb_build_object(
           'root_cause', 'sources.regions missing CN, not a missing entry',
           'verified_cn_jobs_smartrecruiters', 29,
           'verified_cn_jobs_moka_wuhu', 32,
           'jd_url_sample_http_status', 200,
           'same_pool_as_official_portal', true,
           'prior_entry_url_was_wrong_company', 'https://jobs.lenovo.com/zh_CN/careers',
           'also_requires', 'geo ISO country code "cn" (8 of 29 jobs use pinyin city names)'
         )
       ),
       updated_at = now()
 where scope = 'domestic' and company = '大陆集团';
