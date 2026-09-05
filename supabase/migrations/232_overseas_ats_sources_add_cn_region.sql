-- 24 个「已启用、但 regions 漏配 CN」的外企 ATS 源补上 CN 抓取地区。
--
-- 病根与迁移 230（大陆集团 Continental）完全一样，只是那次只修了一家：这些源的 regions 是
-- {US,SG,Remote}，而 adapter 在 parse 与 _enrich_descriptions 两处都调
-- normalizer.location_in_source_regions(location, self.regions) —— CN 不在里面，
-- 于是**每天把中国岗抓回来、每天当场扔掉**。不是没入口、不是被反爬，是我们自己配的过滤器。
--
-- ── 怎么量的（不是推断，是 live 跑）──────────────────────────────────────────────
-- 对 sources 表里 49 个「enabled + regions 非空 + 不含 CN」的源**逐个真跑一遍 adapter**
-- （regions 强制成 {'CN'}、CRAWL_DETAIL_CAP=0 关掉逐岗富化），数的是走完 fetch+parse 之后
-- **真正会入库**的条数，再排掉「当前 regions 本来就放行的」（裸远程）。
-- 为什么不直接问接口：workday 是 facet + searchText 两条路径拼出来的，只问接口会漏；
-- 而 smartrecruiters 的 ?country=cn 又漏掉港澳。以 adapter 的真实产出为准。
--
-- 结果：49 个源里 **24 个有大中华区岗位、合计 868 个**，另外 25 个确实是 0。
-- 每个数字都做了第二条独立路径的交叉复核（CLAUDE.md 红线：接口返 0 不能证明对方没开）：
--   · smartrecruiters 8 家另问官方 ?country=cn/hk/mo 计数 —— AbbVie 169+1、Expeditors 14+4、
--     Grab 14、Ubisoft 11、ServiceNow hk=1、Continental 29、Wise 0、WeWork 0，逐家与实跑吻合；
--   · 10 个 workday 零结果源另做一遍 facet 深搜 + searchText='China' —— 全部没有中国/港澳 facet，
--     searchText 命中的是「正文提到 China 的美国/越南/土耳其岗」，不是中国岗；
--   · eightfold 的 Netflix 另问 location=China → count=0。
--
-- ── jd_url 红线：每家至少 1 个中国岗实测 HTTP 200 且岗位名对得上 ────────────────────
-- 25/25 通过（含迁移 230 已修的大陆集团）。核验路径按平台分，别用错：
--   · smartrecruiters / greenhouse / lever：直接抓 HTML 比岗位名；
--   · workday：公开站是 SPA，HTML 只有壳 → 公开 jd_url 只验 200，岗位名走同源 CXS 详情端点
--     {host}/wday/cxs/{tenant}/{site}{externalPath}（enrich.py 判死用的就是这条）；
--   · ashby：job board 纯客户端渲染，**任何路由**都返 200 + <title>Jobs</title> ——
--     改问 Ashby 自己的 GraphQL(ApiJobPosting)：伪造 id 返 jobPosting=null，
--     所以「返回了 title」本身就是存在性证明。
--     ⚠️ 这一步差点把 Supercell 误判成死链：内置浏览器打开该 URL 显示「Page not found」，
--     但那是它把路径吃掉了跳到了站点根目录。**渲染器说 404 不算数，要问对方的接口。**
--
-- ── 必须和同 PR 的代码一起上，单独上这条迁移 = 制造回归 ────────────────────────────
-- SmartRecruiters 的 location.country 是 ISO-2 小写码（"cn"/"de"），geo 只认国名 ⇒
-- 只补 regions 的话，derive_job_scope 的「源兜底」会把 121 个海外远程岗（"Remote de"/
-- "Remote ro"…）一起判成 domestic，正是 76ce4ff 刚修掉的「裸远程混进国内岗」那个坑。
-- 同 PR 的 crawler 改动（smartrecruiters 展开国家码 + geo 先看 _is_overseas_pinned 再兜底）
-- 把它按住：live 复测判错的 job_scope 121 → 0（艾伯维 102 / 大陆集团 13 / Grab 4 /
-- Expeditors 1 / 育碧 1）。这两处改动顺带**多捞回约 120 个岗**——"Remote cn" 116 个原本
-- 被当成「地点不明的远程岗」算成海外岗，加上拼音分写的城市（合肥写成 "He Fei Shi"）——
-- 所以下面 868 这个数是**代码改完之后**的口径，比改之前的 746 高。
--
-- ── 刻意不做的三件事 ──────────────────────────────────────────────────────────
-- 1. **中国岗为 0 的 25 个源一律不动**（Salesforce / Samsung / Target / Regeneron /
--    ConocoPhillips / Ryder / Scholastic / Zoetis / ITW / Lendlease / Netflix / Wise /
--    WeWork / OpenAI / Docebo / Instructure / Waymo / Flex / Udacity / Khan Academy /
--    百威 / MasterClass / Newsela / Skillsoft / 2U）。它们名下的「CN 范围」岗全是裸远程或
--    海外远程，补 CN 一个中国岗都多不出来，只会把海外岗染成国内岗。为了「统一」而改 = 注水。
-- 2. **不改 sources.company**。必投覆盖聚合（lib/jobs-store/read.ts 的 companyActiveAggregates）
--    是 where status='active'、**不分 job_scope**，改名会把海外岗算进国内覆盖 —— 往北极星注水。
-- 3. **不新增源**。这些公司的中国岗本来就在这些源里，再插一条只会抢同一行 upsert
--    （迁移 225 壳牌影子源的教训）。
--
-- ── 代价（诚实说明，别以为是免费的）──────────────────────────────────────────────
-- · greenhouse / lever / ashby / smartrecruiters 是「抓全量再后置过滤」，补 CN **不增加**
--   列表请求；smartrecruiters 会多做逐岗 detail 富化，有 _DETAIL_CAP=300/源 封顶。
-- · workday **不一样**：它是服务端 facet 过滤，补 CN 会新增「中国/港澳 facet 组」的分页请求
--   （20 条/页）。17 个 workday 源合计新增 638 个岗，约多 30-60 个列表请求/轮，在 daily 预算内。
--   大头是星展银行 361 个（以香港分行为主），它一家就占了这次总量的 42%。
--
update sources s
   set regions = array['CN', 'US', 'SG', 'Remote'],
       notes = coalesce(s.notes || ' ｜ ', '')
               || '2026-09-05 补 CN 抓取地区：live 跑 adapter 实测该源有 ' || v.cn_jobs
               || ' 个大中华区岗位此前被 regions 后置过滤丢弃；'
               || '样本 jd_url 实测 HTTP 200 且岗位名一致 ' || v.sample_jd_url
  from (values
    ('9095d25b-3424-4b8d-b1f5-9bace1bcb354'::uuid, 361, 'DBS Bank 星展银行',               'https://dbs.wd3.myworkdayjobs.com/en-US/DBS_Careers/job/Guangzhou/Equities-Tech-Business-Analyst--Wealth-Management_WD88467'),
    ('835b839b-31d0-49ce-943f-bf22b31d6bd8'::uuid, 170, 'AbbVie',                      'https://jobs.smartrecruiters.com/AbbVie/3743990015071026'),
    ('2872da13-ae6a-49aa-a352-b384e730c6db'::uuid,  89, 'Jabil',                       'https://jabil.wd5.myworkdayjobs.com/en-US/Jabil_Careers/job/Shenzhen/SCM_J2463925'),
    ('d4b4abc1-df55-433b-b41a-ee63d5fd4427'::uuid,  46, 'JLL 仲量联行 Jones Lang LaSalle', 'https://jll.wd1.myworkdayjobs.com/en-US/JLLCareers/job/Hong-Kong-SAR-China/Part-time-Assistant-5_REQ530640'),
    ('cf44f285-882e-4ab2-8929-3bb7fd17e6f2'::uuid,  43, 'The Walt Disney Company 迪士尼', 'https://disney.wd5.myworkdayjobs.com/en-US/disneycareer/job/Lantau-Island-Hong-Kong/Sales-Assistant--1-Year-Contract-_10159887-1'),
    ('c5bdfc63-6304-4dd5-b84e-a27575e362fd'::uuid,  23, 'Keppel',                      'https://keppel.wd3.myworkdayjobs.com/en-US/KeppelCareers/job/Tianjin/Manager--ELV-Engineering_10015816'),
    ('7fb8f00e-35c9-4580-952b-b546babb5046'::uuid,  19, 'Expeditors',                  'https://jobs.smartrecruiters.com/Expeditors/744000147409769'),
    ('95c55026-2edd-416c-b956-b7c82d834dc0'::uuid,  17, 'Warner Bros. Discovery',      'https://warnerbros.wd5.myworkdayjobs.com/en-US/Global/job/Beijing-No-8-Xinyuan-South-Road/Intern--Sales-Coordinator--Winter-2027-_R000107504'),
    ('9b9bf313-eef1-49c8-91fe-0e1313b1519e'::uuid,  15, 'Wiley',                       'https://wiley.wd1.myworkdayjobs.com/en-US/Wiley_Careers/job/Shanghai-CHN/Assistant-Editor-Microbiome-Microbiology-Bioinformatics_R2600902-1'),
    ('52dd2fcc-987f-4f2f-9752-bae22c469778'::uuid,  14, 'Grab',                        'https://jobs.smartrecruiters.com/Grab/744000147406319'),
    ('f1ffa08d-9207-4521-8ac3-e5a46a3e958d'::uuid,  11, 'Ubisoft',                     'https://jobs.smartrecruiters.com/Ubisoft2/744000147409729'),
    ('49e875b3-cda7-4835-a3e8-4c18f797773d'::uuid,  10, '壳牌',                          'https://shell.wd3.myworkdayjobs.com/en-US/ShellCareers/job/Hong-Kong---The-Millennity/Fleet-Solutions-Key-Account-Manager_R203783-1'),
    ('c11b52f0-358e-43ba-89fb-22184321327b'::uuid,   9, 'Ninja Van',                   'https://jobs.lever.co/ninjavan/68e46f73-47a1-49d7-a8d0-44bf0bcf76c6'),
    ('a77636b5-5f2d-4ecd-a576-a189957cfd3a'::uuid,   8, 'Snap Inc',                    'https://snapchat.wd1.myworkdayjobs.com/en-US/Snap/job/Shenzhen-China/Creative-Strategy-Lead--Fixed-Term--8-months-_R0046602-1'),
    ('abb52c83-a88d-414e-b65a-a43030934053'::uuid,   7, 'Mars, Inc. 玛氏',               'https://mars.wd3.myworkdayjobs.com/en-US/External/job/CHN-Shanghai-Shanghai/Field-Sales-Associate-Director-Provincial_R165412-1'),
    ('9823b541-a080-448e-a0a0-73e4e64cada9'::uuid,   6, 'Supercell',                   'https://jobs.ashbyhq.com/supercell/bdc0c3c3-f381-48c7-bcb1-101cc21b1466'),
    ('1e8b1523-4cc5-41b4-ac21-a0a4ce67f944'::uuid,   5, 'Wells Fargo',                 'https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs/job/Hong-Kong-Hong-Kong/XMLNAME-2027-APAC-Banking-Summer-Analyst---Hong-Kong_R-571608-1'),
    ('4f924ae0-f0e0-48ff-8775-97cda860f0f4'::uuid,   3, 'Blackstone',                  'https://blackstone.wd1.myworkdayjobs.com/en-US/Blackstone_Careers/job/Hong-Kong/VP--Talent-Acquisition---APAC_45015'),
    ('a267d8e6-ccee-42f5-8385-c5c122bb5cc7'::uuid,   3, 'Boeing',                      'https://boeing.wd1.myworkdayjobs.com/en-US/External_Careers/job/CHN---Beijing-China/Business-Operations-Specialist--Office-Management-_JR2026523346-1'),
    ('fdd79c85-8f63-437f-a3df-b7463af83a2b'::uuid,   3, 'Brookfield',                  'https://brookfield.wd5.myworkdayjobs.com/en-US/brookfield/job/Hong-Kong/Student-Analyst--Brookfield-Private-Wealth_R2052445'),
    ('39f00d53-f2c0-4b8b-887b-933d42cb5047'::uuid,   2, 'C.H. Robinson',               'https://chrobinson.wd5.myworkdayjobs.com/en-US/chrobinson/job/Shanghai-China/Gateway-Agent-Ocean_R48812'),
    ('3f344573-a188-4ec0-82e0-fc3dfbf08864'::uuid,   2, 'Adobe',                       'https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced/job/Hong-Kong/Senior-Customer-Success-Manager_R171149'),
    ('9c99e8ab-258c-4050-ad19-ae63bf78de14'::uuid,   1, 'Fidelity Investments 富达',     'https://fmr.wd1.myworkdayjobs.com/en-US/FidelityCareers/job/38F-One-International-Finance-Centre-Central-Hong-Kong/Equity-Research-Associate-Intern---Hong-Kong--Summer-2027-_2132214'),
    ('ed3e2736-2979-4551-bfeb-590c26b254eb'::uuid,   1, 'ServiceNow',                  'https://jobs.smartrecruiters.com/ServiceNow/744000135922419')
  ) as v(id, cn_jobs, company_at_audit, sample_jd_url)
 where s.id = v.id
   -- 幂等闸：已经含 CN 的行不再动（重跑迁移 / 手工先补过 都不会把 notes 追加两遍）
   and not ('CN' = any(s.regions));
