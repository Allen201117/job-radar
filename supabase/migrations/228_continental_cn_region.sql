-- 大陆集团（Continental）：给已有的 SmartRecruiters 源补上 CN 抓取地区。
--
-- 背景：必投清单里「大陆集团」长期显示零源零岗，但库里其实已经有两条源。真正的病根不是
-- 「没有中国招聘入口」，而是**这条源自己把中国岗过滤掉了** —— regions 是 {US,SG,Remote}，
-- 而 crawler/adapters/smartrecruiters.py 在 parse 和 _enrich_descriptions 两处都调
-- normalizer.location_in_source_regions(location, self.regions)，CN 不在里面 ⇒ 中国岗直接丢弃。
--
-- 2026-09-05 live 实测（不是推断）：
--   · api.smartrecruiters.com/v1/companies/continental/postings?country=cn → totalFound=29
--   · jobs.continental.com（TYPO3 前台，POST tx_conjobs_api[itemsPerPage]=100 翻完 8 页）
--     736 条里 countryLabel='China' 的正好也是 29 条，REF 号逐个对得上
--     ⇒ 官网门户与我们已用的 SmartRecruiters 是**同一个池子**，不需要新增源、也不该新增源。
--   · 逐岗详情页抽 3 个实测：https://jobs.smartrecruiters.com/Continental/{id} → HTTP 200，
--     <title> 与岗位名一致（Head of ESH Plant PUD / Tactical Category Manager / O2O 2.0…）。
--
-- ⚠️ 刻意不做的两件事：
--   1. 不新增第三条源。这家已有 smartrecruiters + moka（大陆汽车电子（芜湖），
--      portal_identity = continental/56212）两条，再插一条就是影子源（见迁移 225 壳牌的教训）。
--   2. 不把 sources.company 从 'Continental' 改成 '大陆集团 Continental'。改名确实能让必投
--      pattern '%大陆集团%' 命中（库里 'Bosch 博世' 就是这么匹配的），但必投覆盖聚合
--      （lib/jobs-store/read.ts 的 companyActiveAggregates）是 `where status='active'`、
--      **不分 job_scope**，改名会把 346 个美国岗 + 6 个新加坡岗一起算进「大陆集团」的国内覆盖。
--      那是往北极星里注水。要不要让必投覆盖只认 domestic 是口径级决定，另案处理。
update sources
   set regions = array['CN', 'US', 'SG', 'Remote'],
       notes = 'auto_discover: live探活 48 岗；2026-09-05 补 CN 抓取地区（该源同时供给中国岗，'
               || 'live 实测 country=cn 29 岗，逐岗详情页 jobs.smartrecruiters.com/Continental/{id} 实测 200）'
 where source_url = 'https://api.smartrecruiters.com/v1/companies/continental/postings?limit=100';

-- ── 缺口台账：把「大陆集团」的结论改写成实测事实 ────────────────────────────────────
-- 台账原来记的是 state=wrong_platform / fail_reason='P1 httpx 道无可用 adapter'，
-- 而 official_entry_url 竟然是 **https://jobs.lenovo.com/zh_CN/careers（联想的招聘页）** ——
-- 搜索「大陆集团」把联想搜出来了。身份核验门挡住了它（没入库，红线没破），
-- 但这条错误的入口被当成结论存了下来，且 next_retry_at=2026-10-05 还要再搜一次。
--
-- 实测真相（2026-09-05，见本文件上半段）：这家**既不缺入口也不缺 adapter**，
-- 两条源都在跑（smartrecruiters 全球池 + moka 大陆汽车电子（芜湖）），
-- 中国岗一直在被 regions 过滤掉。补上 CN 之后中国供给 = 29（SmartRecruiters）+ 32（芜湖）。
--
-- 但**必投指标仍然会显示为缺口**，这是本次没有自行解决、需要人拍板的一件事：
--   gap_census.classify_company 用 pattern '%大陆集团%' 去匹配 jobs.company / sources.company，
--   而库里两条源叫 'Continental' 和 '大陆汽车电子（芜湖）有限公司'，都不含「大陆集团」四个字
--   ⇒ healthy_total 恒为 0 ⇒ 状态永远好不了，跟有没有岗无关。
--   三条出路各有代价，都属口径级决定：① 改 sources.company 为双语名（像 'Bosch 博世'）——
--   但必投覆盖聚合不分 job_scope，会把 346 个美国岗算进国内覆盖；② 建清单别名表——
--   属跨 session 共用口径，改前需协调；③ 让必投覆盖只认 domestic，之后 ① 才安全。
-- 所以这里记 manual_review + next_retry_at=NULL：技术侧已解决，别再让漏斗每 45 天
-- 拿「大陆集团」去搜一次、再搜出一个联想来。
update must_apply_gap_attempts
   set state = 'manual_review',
       official_entry_url = 'https://jobs.continental.com/en/',
       detected_platform = 'smartrecruiters',
       source_id = 'a3e25d62-b7c4-4252-9e3a-c39d4df39fa5'::uuid,
       fail_reason = '供给侧已解决（源和 adapter 本来就有，是 regions 缺 CN 把中国岗过滤了）；'
                     || '剩下的是命名/口径问题：清单 pattern %大陆集团% 匹配不上库里的 '
                     || 'Continental 与「大陆汽车电子（芜湖）有限公司」，需人工决定改名/别名/口径',
       next_retry_at = null,
       evidence = evidence || jsonb_build_object(
         'manual_note_2026_09_05', jsonb_build_object(
           'verified_cn_jobs_smartrecruiters', 29,
           'verified_cn_jobs_moka_wuhu', 32,
           'jd_url_sample_http_status', 200,
           'same_pool_as_official_portal', true,
           'prior_entry_url_was_wrong_company', 'https://jobs.lenovo.com/zh_CN/careers',
           'blocked_by', 'must_apply pattern vs sources.company naming'
         )
       ),
       updated_at = now()
 where scope = 'domestic' and company = '大陆集团';
