-- 295 — 补体验走查暴露的供给缺口：5 家公司 8 条官方源（2026-09-23 逐条 live 核实）
--
-- 来由：09-20~22 体验走查的「方向不符拦光」7 条里 5 条是**库里真没货**（长春实习项目助理 0、宁波实习机械 1、
-- 苏南/杭州校招实验员 7、上海/杭州有机合成 0 新鲜岗、广州风控实习个位数）。按缺的岗位方向列了 16 家候选公司，
-- 逐家找官方入口 → 认平台 → adapter 真抓 → 核归属 → 真浏览器开详情页，过门的只有下面这 8 条。
--
-- 验收口径（每条都真跑过，不是估算）：parse = valid = jd_url 唯一数；fetch_complete=True 且 reported_total 与抓到数相等；
-- 随机 3~4 条详情页用真浏览器渲染，全部 200 + 页面里有该岗标题 + 无「停止招聘/已下线」文案；
-- 同公司多渠道按岗位 id 对拍，渠道间 0 重叠（不会一个岗存两行）。
--
--   公司       渠道        平台 / 入口                                                     在招  正文≥60字  归属依据
--   长光卫星   校招        hotjob  cgwx.hotjob.cn/SU680597f91eb80570a8beb7c5/pb/school.html   16    16       租户 suite/config 自报 companyName=长光卫星技术股份有限公司；官网 jl1.cn 校招公告指向此系统
--   长光卫星   社招        同租户 /pb/social.html                                          30    27       同上
--   金赛药业   校招        moka    app.mokahr.com/campus-recruitment/gensci/144980            13     0*      官网 genscigroup.com/about/career 页源码 data-url 直链
--   金赛药业   社招        moka    app.mokahr.com/social-recruitment/gensci/43519            140     0*      同租户 gensci；详情页真渲染标题逐条对得上
--   广州银行   社招+校招   wt      sc.hotjob.cn/wt/GZCB/web/index                            125   122       门户页真渲染标题「广州银行招聘」（curl 被 WAF 405，只能浏览器核）
--   敏实集团   社招        hotjob  wecruit.hotjob.cn/SU61304acdbef57c061649be2e/pb/social.html 83    83       租户自报 companyName=敏实集团；官网 minthgroup.com 招聘页直链
--   药石科技   社招        北森    pharmablock.zhiye.com/social                                71    71       页面自报「南京药石科技股份有限公司AI招聘官网」
--   药石科技   校招        北森    pharmablock.zhiye.com/campus                                35    35       同上
--   * Moka 列表不带正文，由每晚 backfill_moka_summaries 逐岗渲染补；补上之前按薄卡处理，不进有效在招计数。
--   ⚠️ 金赛两条源的 location 大多为空（社招 136/140）：Moka 这个租户列表不给地点。空地点的岗在 /today 会按「城市未知」
--      放行——这是全库通病，另有任务在修（标题里的城市回填 location），不在本迁移范围。
--
-- 没接、以及为什么（留档，别再重复排查）：
--   广发银行   校招/实习在北森 chinalife.zhiye.com（与中国人寿**共用租户**），adapter 忽略 /custom/gfcampus 门户参数、
--              抓回整个租户 2,964 岗（大半是人寿的保险岗），全贴成「广发银行」＝张冠李戴。社招在自建 INSS，无 adapter。
--              顺带查出：现有「中国人寿」源（chinalife.zhiye.com/custom/intern）名下 3,579 个在招岗里约 521 个是银行岗，
--              已另开任务按租户逐岗归属修正。
--   广州农商行 自建「干部管理系统」（皓云原智），无 adapter。
--   吉林银行   官网只有招聘公告（公告制，无逐岗页）；另有 jlbank.zhaopin.com 是智联定制站（第三方，红线）。
--   毕得医药   北森 bidepharmatech.zhiye.com 存在，但页面自报「社会招聘 共0个职位 / 校园招聘 共0个职位」——今天真没岗，不加空源。
--   皓元医药 / 美迪西  自建站，岗位在弹窗或同一页里，无逐岗详情链接（过不了 jd_url 红线）。
--   九洲药业   中企动力 CMS，数据接口被 WAF 拦，需新写浏览器 adapter。
--   拓普集团 / 宁波华翔  招聘官网是智联 / 51job 托管站（第三方，红线）。
--   谱尼测试   只收邮件简历，无招聘系统。
--   SGS        全球招聘页渲染后无任何岗位链接，Workday 站点名没找到。
--   长光卫星实习 / 敏实校招·实习：实习 0 岗；敏实校招 6 岗 0 条过质量门、实习 1 岗详情页打不出标题——都不加。
--   敏实另有老系统 wt/minth（99 岗）与 wecruit 社招是同一批岗，官网只挂 wecruit，只接这一条防重复。
--
-- 药石科技这两条依赖同一 commit 的 adapter 改动：北森老版 CMS 多了一种「position-item」行模板
-- （adapters/china_ats._cms_parse_position_items），之前整源静默 0 岗。改动只在 <li> 模板一行都没匹到时启用，
-- 全部 367 条 enabled 北森源第一页改前改后逐源对拍：366 条逐字相同，只有药石变了。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, industry, industry_group, ownership, notes)
select v.company, v.source_url, 'official', v.adapter_name, v.crawl_method,
       true, '{CN}', v.industry, v.industry_group, v.ownership, v.notes
  from (values
    ('长光卫星', 'https://cgwx.hotjob.cn/SU680597f91eb80570a8beb7c5/pb/school.html', 'hotjob', 'http',
     '商业航天', '制造/工业', 'unknown',
     '2026-09-23 接入（体验走查供给缺口）：hotjob 校招，live 16/16 有效、jd_url 唯一、抓全；租户自报 长光卫星技术股份有限公司；详情页真渲染 3/3。'),
    ('长光卫星', 'https://cgwx.hotjob.cn/SU680597f91eb80570a8beb7c5/pb/social.html', 'hotjob', 'http',
     '商业航天', '制造/工业', 'unknown',
     '2026-09-23 接入：hotjob 社招，live 30/30 有效、正文 27/30、抓全；详情页真渲染 3/3。实习板块当天 0 岗未接。'),
    ('金赛药业', 'https://app.mokahr.com/campus-recruitment/gensci/144980', 'moka', 'playwright',
     '生物医药', '医疗/医药', 'unknown',
     '2026-09-23 接入：官网 genscigroup.com 招聘页直链的 Moka 校招门户，live 13 岗；列表无正文待 moka 正文回填；详情页真渲染 3/3。'),
    ('金赛药业', 'https://app.mokahr.com/social-recruitment/gensci/43519', 'moka', 'playwright',
     '生物医药', '医疗/医药', 'unknown',
     '2026-09-23 接入：Moka 社招门户（同租户 gensci，与校招门户岗位 0 重叠），live 140 岗；地点多为空（租户列表不给）；详情页真渲染 3/3。'),
    ('广州银行', 'https://sc.hotjob.cn/wt/GZCB/web/index', 'wt', 'http',
     '银行', '金融', 'soe',
     '2026-09-23 接入：wt 租户 GZCB（门户真渲染标题「广州银行招聘」），live 125/125 有效、正文 122、抓全；含校招 46、实习 3；详情页真渲染 3/3。'),
    ('敏实集团', 'https://wecruit.hotjob.cn/SU61304acdbef57c061649be2e/pb/social.html', 'hotjob', 'http',
     '汽车零部件', '汽车/出行', 'private',
     '2026-09-23 接入：官网 minthgroup.com 直链的 wecruit 社招，租户自报 敏实集团，live 83/83 有效、正文 83、抓全；详情页真渲染 3/3。老系统 wt/minth 是同一批岗，不接。'),
    ('药石科技', 'https://pharmablock.zhiye.com/social', 'beisen', 'http',
     '医药研发外包', '医疗/医药', 'private',
     '2026-09-23 接入：北森老版 CMS「position-item」模板（同 commit 补解析），live 71/71 有效、正文 71、抓全（与页面分页自报 7×10+1 对上）；详情页真渲染 4/4。'),
    ('药石科技', 'https://pharmablock.zhiye.com/campus', 'beisen', 'http',
     '医药研发外包', '医疗/医药', 'private',
     '2026-09-23 接入：同租户校招，live 35/35 有效、正文 35、抓全（3×10+5）；与社招 0 重叠；详情页真渲染 4/4。实习板块当天 0 岗未接。')
  ) as v(company, source_url, adapter_name, crawl_method, industry, industry_group, ownership, notes)
 where not exists (select 1 from public.sources s where s.source_url = v.source_url);
