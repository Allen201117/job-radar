-- 261：2027 届秋招覆盖缺口补源第二批（2026-09-18）
--
-- 来源：312 家「已发布 2027 届秋招公告」的公司与库对拍后，剔除必投清单（另有同事在做）剩下的
-- 缺口名单 → crawler/targets_campus_2027.json → discover_domestic.sweep（slug 猜 + 租户探活）
-- → 真 adapter 端到端 job-confirm（fetch → parse → normalizer.validate_job_quality → 抽 3 个
-- jd_url 回读 HTTP 200）。**没过这道门的一条都没写**，猜错的 slug（财通证券 ctsec / 诺亚 noahgroup /
-- 泉峰 chervon / 国家电投 spic 四个 zhiye 子域全路由 404）一律丢弃。
--
-- ⚠️ 归属核验：hotjob/wt 那几条不是靠「slug 命中就算」——discover_domestic.hotjob_probe 的
--    verified=True **只说明 suiteKey 来自 {slug}.hotjob.cn，没有任何公司名核验**。本批逐个读了
--    列表接口自报的 company 字段：中泰证券=各地分公司+中泰期货、新能安=「厦门新能安（XMC）」、
--    信立泰=「深圳信立泰药业股份有限公司」、迪康=「成都迪康药业股份有限公司」、
--    美宜佳门户 <title>=「加入美宜佳控股有限公司」。
-- ⚠️ 同一个 ampace.hotjob.cn 租户同时被「新能安」和「安脉时代智能制造(宁德)」两个目标名猜中，
--    列表自报 company 全是「厦门新能安（XMC）」→ **只写新能安一条**，不给安脉时代另立影子源。
--
-- ⚠️ beisen 为什么多数只写一条路由：实测 /campus 与 /social 返回的是**同一批岗**
--    （国金证券两条都是 411 岗、同一 job_type 分布；换独立进程复跑 /social 仍是 411，排除了
--    adapter 单例缓存的干扰）。北森的 GetJobAdPageList 按租户返全量，与入口路由无关，
--    两条都写等于把同一批岗抓两遍、白烧浏览器档预算。真正分路由的三家（山东得益/新时达/天康生物）
--    两条数字不同，才各写两条。
--    残留风险：若某租户其实是分路由而 /campus 只是子集，我们会少收社招那部分——**不会少收校招**，
--    且 db-report 逐源产出能看出来。
-- ⚠️ board 是 generated 列（classify_source_board），不显式写。
-- ⚠️ 全部 regions 显式 '{CN}'（默认值也是它；写出来是为了避免「漏 CN 把中国岗当场丢掉」那类坑）。
-- ⚠️ sources 表**没有 source_url 唯一约束**，所以去重只能靠 where not exists，不能靠 on conflict。
-- 📌 招聘类型看的是**渠道**不是下面括号里的 job_type：hotjob 的 pb/school.html=校招、
--    pb/interns.html=实习、pb/social.html=社招；飞书 /campus/position=校招门户、
--    /index/position=社招全集（见 CLAUDE.md「飞书 website-path」）；moka 的
--    campus-recruitment/* = 校招门户。括号里的是平台自己的**岗位职类**标签，别当招聘类型读。
--    只有北森的 job_type 才是租户自报的招聘类别（校园招聘/实习生招聘/社会招聘）。
-- 📌 美宜佳实测：不带 website-path 的 /index/position 只有 12 个岗，而 /campus/position 有 30 个
--    ——校招那批**不在**社招全集里，两条都要。/internship/position 该租户不存在（探活报错，未写）。
--
-- 端到端实测数字（2026-09-18，CRAWL_DETAIL_CAP=3，详情全部 HTTP 200）：
--   国金证券         https://gjzq.zhiye.com/campus  → 411 岗，其中校招/实习 102（社会招聘 307、实习生招聘 62、校园招聘 40、人才库 2）
--   中信建投证券       https://csc108.zhiye.com/campus  → 94 岗，其中校招/实习 29（社会招聘 62、校园招聘 29、人才库 3）
--   劲牌           https://jingpai.zhiye.com/campus  → 91 岗，其中校招/实习 70（校园招聘 69、社会招聘 21、实习生招聘 1）
--   齐心集团         https://comix.zhiye.com/campus  → 96 岗，其中校招/实习 12（社会招聘 84、校园招聘 12）
--   全棉时代         https://purcotton.zhiye.com/campus  → 104 岗，其中校招/实习 20（社会招聘 59、门店招聘 25、校园招聘 19、实习生招聘 1）
--   柏楚电子         https://fscut.zhiye.com/campus  → 126 岗，其中校招/实习 53（社会招聘 73、校园招聘 36、实习生招聘 17）
--   星网锐捷         https://starnet.zhiye.com/campus  → 18 岗，其中校招/实习 18（校园招聘 18）
--   南瑞继保         https://nrec.zhiye.com/campus  → 10 岗，其中校招/实习 7（校园招聘 7、社会招聘 3）
--   海四达          https://highstar.zhiye.com/campus  → 77 岗，其中校招/实习 21（社会招聘 54、校园招聘 21、内部招聘 2）
--   创维光伏         https://skyworthpv.zhiye.com/campus  → 4 岗（社会招聘 4）
--   艾诺仪器         https://ainuo.zhiye.com/campus  → 17 岗，其中校招/实习 14（校园招聘 14、社会招聘 3）
--   越疆科技         https://dobot.zhiye.com/campus  → 135 岗，其中校招/实习 39（社会招聘 96、校园招聘 34、实习生招聘 5）
--   睿创微纳         https://raytrontek.zhiye.com/campus  → 258 岗，其中校招/实习 103（社会招聘 155、校园招聘 53、实习生招聘 49、校园大使招聘 1）
--   陕汽控股         https://sxqc.zhiye.com/campus  → 150 岗，其中校招/实习 61（社会招聘 89、校园招聘 61）
--   海正药业         https://hisunpharm.zhiye.com/campus  → 27 岗，其中校招/实习 9（社会招聘 18、校园招聘 9）
--   京新药业         https://jingxinpharm.zhiye.com/campus  → 117 岗，其中校招/实习 68（校园招聘 68、社会招聘 49）
--   哈药集团         https://hayao.zhiye.com/campus  → 74 岗，其中校招/实习 74（校园招聘 74）
--   新疆天业集团       https://xjtianye.zhiye.com/campus  → 6 岗，其中校招/实习 3（社会招聘 3、校园招聘 3）
--   山东得益乳业       https://deyi.zhiye.com/campus  → 44 岗（平台不出类别字段，靠 recruitment_classify 判）
--   山东得益乳业       https://deyi.zhiye.com/social  → 55 岗（平台不出类别字段，靠 recruitment_classify 判）
--   新时达          https://stepelectric.zhiye.com/campus  → 13 岗（平台不出类别字段，靠 recruitment_classify 判）
--   新时达          https://stepelectric.zhiye.com/social  → 136 岗（平台不出类别字段，靠 recruitment_classify 判）
--   天康生物         https://tecon.zhiye.com/campus  → 7 岗（平台不出类别字段，靠 recruitment_classify 判）
--   天康生物         https://tecon.zhiye.com/social  → 4 岗（平台不出类别字段，靠 recruitment_classify 判）
--   北京麦田         https://maitian.zhiye.com/social  → 6 岗（平台不出类别字段，靠 recruitment_classify 判）
--   诺亚控股         https://app.mokahr.com/campus-recruitment/noah/26537  → 25 岗（平台不出类别字段，靠 recruitment_classify 判）
--   诺亚控股         https://app.mokahr.com/social-recruitment/noah/76134  → 15 岗（平台不出类别字段，靠 recruitment_classify 判）
--   延锋           https://app.mokahr.com/campus-recruitment/yanfeng/45086  → 190 岗（平台不出类别字段，靠 recruitment_classify 判）
--   延锋           https://app.mokahr.com/social-recruitment/yanfeng/45085  → 512 岗（平台不出类别字段，靠 recruitment_classify 判）
--   盛弘电气         https://app.mokahr.com/campus-recruitment/sinexcel/74287  → 29 岗（平台不出类别字段，靠 recruitment_classify 判）
--   盛弘电气         https://app.mokahr.com/social-recruitment/sinexcel/74286  → 41 岗（平台不出类别字段，靠 recruitment_classify 判）
--   宇通集团         https://app.mokahr.com/campus-recruitment/yutong/172567  → 40 岗（平台不出类别字段，靠 recruitment_classify 判）
--   中泰证券         https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/social.html  → 469 岗（分支机构岗位分类 397、中泰期货职位类别 45、总部岗位分类 27）
--   中泰证券         https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/interns.html  → 7 岗（业务序列 7）
--   新能安          https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/school.html  → 68 岗（电源&电子研发类 22、材料&电芯研发类 14、智能制造类 12、支持类 6、项目&运营类 6）
--   新能安          https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/social.html  → 369 岗（社招-研发类 147、社招-运营类 77、社招-支持类 52、社招-客户一线类 21、电子研发类 20）
--   信立泰药业        https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/school.html  → 39 岗（研发 17、生产 8、职能 7、销售 7）
--   信立泰药业        https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/social.html  → 98 岗（销售 73、研发 11、职能 8、生产 6）
--   迪康药业         https://dikang.hotjob.cn/wt/DIKANG/web/index  → 33 岗，其中校招/实习 8（营销类 17、生产类 8、生产类 校园招聘 6、研发类 校园招聘 2）
--   美宜佳          https://meiyijia.jobs.feishu.cn/index/position  → 12 岗（销售 2、生活服务 2、人力资源 2、审计 2、财务 / 审计  / 税务 1）
--   美宜佳          https://meiyijia.jobs.feishu.cn/campus/position  → 30 岗（百货 / 连锁 / 零售 25、采购 / 贸易 / 交通 / 物流 5）

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '国金证券', 'https://gjzq.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '证券',
       '2026-09-18 端到端探活：411 岗全过质量门（自报类别：社会招聘 307、实习生招聘 62、校园招聘 40、人才库 2）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://gjzq.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '中信建投证券', 'https://csc108.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '证券',
       '2026-09-18 端到端探活：94 岗全过质量门（自报类别：社会招聘 62、校园招聘 29、人才库 3）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://csc108.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '劲牌', 'https://jingpai.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '酒类·快消',
       '2026-09-18 端到端探活：91 岗全过质量门（自报类别：校园招聘 69、社会招聘 21、实习生招聘 1）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://jingpai.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '齐心集团', 'https://comix.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '办公用品·B2B',
       '2026-09-18 端到端探活：96 岗全过质量门（自报类别：社会招聘 84、校园招聘 12）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://comix.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '全棉时代', 'https://purcotton.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '消费品·零售',
       '2026-09-18 端到端探活：104 岗全过质量门（自报类别：社会招聘 59、门店招聘 25、校园招聘 19、实习生招聘 1）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://purcotton.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '柏楚电子', 'https://fscut.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '激光控制系统',
       '2026-09-18 端到端探活：126 岗全过质量门（自报类别：社会招聘 73、校园招聘 36、实习生招聘 17）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://fscut.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '星网锐捷', 'https://starnet.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '网络通信设备',
       '2026-09-18 端到端探活：18 岗全过质量门（自报类别：校园招聘 18）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://starnet.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '南瑞继保', 'https://nrec.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '电力保护与控制',
       '2026-09-18 端到端探活：10 岗全过质量门（自报类别：校园招聘 7、社会招聘 3）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://nrec.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '海四达', 'https://highstar.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '锂电池',
       '2026-09-18 端到端探活：77 岗全过质量门（自报类别：社会招聘 54、校园招聘 21、内部招聘 2）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://highstar.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '创维光伏', 'https://skyworthpv.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '光伏',
       '2026-09-18 端到端探活：4 岗全过质量门（自报类别：社会招聘 4）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://skyworthpv.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '艾诺仪器', 'https://ainuo.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '电子测量仪器',
       '2026-09-18 端到端探活：17 岗全过质量门（自报类别：校园招聘 14、社会招聘 3）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://ainuo.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '越疆科技', 'https://dobot.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '机器人',
       '2026-09-18 端到端探活：135 岗全过质量门（自报类别：社会招聘 96、校园招聘 34、实习生招聘 5）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://dobot.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '睿创微纳', 'https://raytrontek.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '红外芯片',
       '2026-09-18 端到端探活：258 岗全过质量门（自报类别：社会招聘 155、校园招聘 53、实习生招聘 49、校园大使招聘 1）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://raytrontek.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '陕汽控股', 'https://sxqc.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '商用车',
       '2026-09-18 端到端探活：150 岗全过质量门（自报类别：社会招聘 89、校园招聘 61）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://sxqc.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '海正药业', 'https://hisunpharm.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：27 岗全过质量门（自报类别：社会招聘 18、校园招聘 9）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://hisunpharm.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '京新药业', 'https://jingxinpharm.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：117 岗全过质量门（自报类别：校园招聘 68、社会招聘 49）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://jingxinpharm.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '哈药集团', 'https://hayao.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：74 岗全过质量门（自报类别：校园招聘 74）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://hayao.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '新疆天业集团', 'https://xjtianye.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'soe', '化工',
       '2026-09-18 端到端探活：6 岗全过质量门（自报类别：社会招聘 3、校园招聘 3）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://xjtianye.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '山东得益乳业', 'https://deyi.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '乳制品',
       '2026-09-18 端到端探活：44 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://deyi.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '山东得益乳业', 'https://deyi.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '乳制品',
       '2026-09-18 端到端探活：55 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://deyi.zhiye.com/social');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '新时达', 'https://stepelectric.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '工业机器人·电梯控制',
       '2026-09-18 端到端探活：13 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://stepelectric.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '新时达', 'https://stepelectric.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '工业机器人·电梯控制',
       '2026-09-18 端到端探活：136 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://stepelectric.zhiye.com/social');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '天康生物', 'https://tecon.zhiye.com/campus', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '生物制药·农牧',
       '2026-09-18 端到端探活：7 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://tecon.zhiye.com/campus');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '天康生物', 'https://tecon.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '生物制药·农牧',
       '2026-09-18 端到端探活：4 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://tecon.zhiye.com/social');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '北京麦田', 'https://maitian.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '房产经纪',
       '2026-09-18 端到端探活：6 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://maitian.zhiye.com/social');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '诺亚控股', 'https://app.mokahr.com/campus-recruitment/noah/26537', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '财富管理',
       '2026-09-18 端到端探活：25 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/campus-recruitment/noah/26537');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '诺亚控股', 'https://app.mokahr.com/social-recruitment/noah/76134', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '财富管理',
       '2026-09-18 端到端探活：15 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/social-recruitment/noah/76134');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '延锋', 'https://app.mokahr.com/campus-recruitment/yanfeng/45086', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '汽车零部件',
       '2026-09-18 端到端探活：190 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/campus-recruitment/yanfeng/45086');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '延锋', 'https://app.mokahr.com/social-recruitment/yanfeng/45085', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '汽车零部件',
       '2026-09-18 端到端探活：512 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/social-recruitment/yanfeng/45085');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '盛弘电气', 'https://app.mokahr.com/campus-recruitment/sinexcel/74287', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '电力电子',
       '2026-09-18 端到端探活：29 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/campus-recruitment/sinexcel/74287');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '盛弘电气', 'https://app.mokahr.com/social-recruitment/sinexcel/74286', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '电力电子',
       '2026-09-18 端到端探活：41 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/social-recruitment/sinexcel/74286');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '宇通集团', 'https://app.mokahr.com/campus-recruitment/yutong/172567', 'official', 'moka', 'playwright',
       true, '{CN}', 'private', '客车',
       '2026-09-18 端到端探活：40 岗全过质量门；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://app.mokahr.com/campus-recruitment/yutong/172567');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '中泰证券', 'https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/social.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'soe', '证券',
       '2026-09-18 端到端探活：469 岗全过质量门（自报类别：分支机构岗位分类 397、中泰期货职位类别 45、总部岗位分类 27）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/social.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '中泰证券', 'https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/interns.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'soe', '证券',
       '2026-09-18 端到端探活：7 岗全过质量门（自报类别：业务序列 7）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://zts.hotjob.cn/SU62bd501c0dcad406d143caea/pb/interns.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '新能安', 'https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/school.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '锂电池',
       '2026-09-18 端到端探活：68 岗全过质量门（自报类别：电源&电子研发类 22、材料&电芯研发类 14、智能制造类 12、支持类 6、项目&运营类 6）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/school.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '新能安', 'https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/social.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '锂电池',
       '2026-09-18 端到端探活：369 岗全过质量门（自报类别：社招-研发类 147、社招-运营类 77、社招-支持类 52、社招-客户一线类 21、电子研发类 20）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://ampace.hotjob.cn/SU6619d98e1eb8053acd618afb/pb/social.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '信立泰药业', 'https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/school.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：39 岗全过质量门（自报类别：研发 17、生产 8、职能 7、销售 7）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/school.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '信立泰药业', 'https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/social.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：98 岗全过质量门（自报类别：销售 73、研发 11、职能 8、生产 6）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://salubris.hotjob.cn/SU68b7fe15720ec026827c5d67/pb/social.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '迪康药业', 'https://dikang.hotjob.cn/wt/DIKANG/web/index', 'official', 'wt', 'http',
       true, '{CN}', 'private', '医药',
       '2026-09-18 端到端探活：33 岗全过质量门（自报类别：营销类 17、生产类 8、生产类 校园招聘 6、研发类 校园招聘 2）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://dikang.hotjob.cn/wt/DIKANG/web/index');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '美宜佳', 'https://meiyijia.jobs.feishu.cn/index/position', 'official', 'feishu', 'http',
       true, '{CN}', 'private', '连锁便利店',
       '2026-09-18 端到端探活：12 岗全过质量门（自报类别：销售 2、生活服务 2、人力资源 2、审计 2、财务 / 审计  / 税务 1）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://meiyijia.jobs.feishu.cn/index/position');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select '美宜佳', 'https://meiyijia.jobs.feishu.cn/campus/position', 'official', 'feishu', 'http',
       true, '{CN}', 'private', '连锁便利店',
       '2026-09-18 端到端探活：30 岗全过质量门（自报类别：百货 / 连锁 / 零售 25、采购 / 贸易 / 交通 / 物流 5）；抽 3 个 jd_url 回读 HTTP 200。'
where not exists (select 1 from public.sources where source_url = 'https://meiyijia.jobs.feishu.cn/campus/position');
