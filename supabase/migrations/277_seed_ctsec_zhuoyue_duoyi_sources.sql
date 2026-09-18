-- 277 — 接入 财通证券（hotjob 社招+校招）、卓越教育（hotjob 社招+校招）、多益网络（自建站 校招+社招）
--
-- 来源：2026-09-18 缺口漏斗把「入口找到了、却被拦在路由门外」的原因逐家归类后修的两处路由
-- （crawler/platform_fingerprint.py：hotjob 租户首页 /{SU…}/pb/index.html → social.html；
--   自建壳的首屏 JS 包里写死的 ATS 租户地址）+ 一个新 adapter（adapters/duoyi.py）。
-- 财通 / 卓越两家是「平台早就认得出（hotjob），只是 URL 形态没被路由」的典型 —— 落地页不带板块后缀，
-- 漏斗此前记 adapter_source_url_unroutable；多益是自建 Vue SPA，/v40/api 公开 JSON、列表即全文。
--
-- ── 接入前 live 验过的事实（2026-09-18，纯 httpx，零浏览器、零登录）──
-- ① should_skip(source_url) 六条源都**实测跑过** → None（不跳过）。
-- ② 端到端跑了 fetch → parse → normalize → validate_job_quality（不是只探接口），数字见各行 notes。
-- ③ hotjob 两家：逐岗详情按 CRAWL_DETAIL_CAP=3 真开 3 条全 HTTP 200 + 拿到正文；
--    公司名只认租户自报的 suite/config.companyName（财通证券 / 卓越教育，与 slug 无关，CLAUDE.md 红线）。
--    多益：三个 jd_url 用浏览器真渲染（hash 路由）——真 id 渲出标题 + 职责 + 要求 + 「投递简历」，
--    伪 id 渲出空壳；判死走接口 `positions/{id}/jds`（enrich._detail_duoyi，真伪 id 对拍）。
-- ④ 抓全率：hotjob 走接口自报 totalPage 翻到底（fetch_complete=True）；多益 pageIndex/pageSize
--    实测都真实生效（page1 ∩ page2 = 0、page2 = total − 20），去重后条数 = 自报 total。
-- ⑤ 归属：财通/卓越 是租户自报公司名；多益 两个 host 是同一后端、渠道只认 host 前缀（xz=校招 10 /
--    sz=社招 20），两渠道 id 空间不重叠（33 ∩ 57 = 0），不会互相污染。
--
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187/269/276），显式赋值整批迁移会回滚。
-- ⚠️ 多益校招行的 adapter_name 是 `duoyi_campus`（与社招 `duoyi` 同一个类，见 run.py）：URL `xz.duoyi.com`
--    没有任何 campus 令牌，走 URL 规则会被判成 social → campus-crawl 车道整条漏掉；迁移 276 把它钉进
--    classify_source_board 规则②（同 269 顺丰/美的的理由：adapter 只抓校招是确定事实，URL 长什么样不是）。
-- ⚠️ crawl_method 只认 http / playwright / manual —— 这六条全是纯 httpx，填 http。
-- ⚠️ industry_group / ownership 的取值受 CHECK 约束（迁移 265）：
--    证券 → '金融'；教育培训 → '教育'；游戏 → '互联网/科技'。财通证券是浙江省国资控股 → soe。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '财通证券', 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/social.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'soe', '证券', '金融', 'soe',
       '2026-09-18 接入：财通证券社招板块（wecruit 租户，自报 companyName=财通证券）。入口 www.ctsec.com/careers → wecruit …/pb/index.html，此前落地页无板块后缀被漏斗记 unroutable。live：自报 total=136，parse 136/136，fetch_complete=True；job_type 社会招聘；CRAWL_DETAIL_CAP=3 真开 3 条详情全 HTTP 200 + 正文。'
where not exists (select 1 from public.sources where source_url = 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/social.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '财通证券', 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/school.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'soe', '证券', '金融', 'soe',
       '2026-09-18 接入：财通证券校招板块（同租户 school.html）。live：自报 total=72，parse 72/72，fetch_complete=True；job_type 校园招聘；CRAWL_DETAIL_CAP=3 真开 3 条详情全 HTTP 200 + 正文。'
where not exists (select 1 from public.sources where source_url = 'https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/school.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '卓越教育', 'https://zyjob.hotjob.cn/SU63366915bef57c270741e277/pb/social.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '教育培训', '教育', 'private',
       '2026-09-18 接入：卓越教育社招板块（品牌域 zyjob.hotjob.cn 的 wecruit 租户，自报 companyName=卓越教育）。必投缺口台账此前记 wrong_platform（落地页 /pb/index.html 无板块后缀）。live：自报 total=234，parse 234/234，fetch_complete=True；CRAWL_DETAIL_CAP=3 真开 3 条详情全 HTTP 200 + 正文。'
where not exists (select 1 from public.sources where source_url = 'https://zyjob.hotjob.cn/SU63366915bef57c270741e277/pb/social.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '卓越教育', 'https://zyjob.hotjob.cn/SU63366915bef57c270741e277/pb/school.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '教育培训', '教育', 'private',
       '2026-09-18 接入：卓越教育校招板块（同租户 school.html）。live：自报 total=427，parse 427/427，fetch_complete=True；job_type 校园招聘（标题多带「-校招」后缀）；CRAWL_DETAIL_CAP=3 真开 3 条详情全 HTTP 200 + 正文。'
where not exists (select 1 from public.sources where source_url = 'https://zyjob.hotjob.cn/SU63366915bef57c270741e277/pb/school.html');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '多益网络', 'https://xz.duoyi.com/v40/#/positions', 'official', 'duoyi_campus', 'http',
       true, '{CN}', 'private', '游戏', '互联网/科技', 'private',
       '2026-09-18 接入：多益网络校招官网（recruit=10，渠道按 host 前缀 xz 判定）。接口 GET /v40/api/index/positions/jds/page，列表自带全文。live：自报 total=33，parse 33/33，正文 33/33（≥60 字），jd_url 唯一 33/33，validate_job_quality 33/33 通过，fetch_complete=True；job_type 校园招聘 32 / 实习 1（outerNature=实习）；地点 广州 31 / 杭州 2。jd_url 为 hash 路由 …/v40/#/position-detail/{id}，浏览器真渲染核过 3 条。'
where not exists (select 1 from public.sources where source_url = 'https://xz.duoyi.com/v40/#/positions');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '多益网络', 'https://sz.duoyi.com/v40/#/positions', 'official', 'duoyi', 'http',
       true, '{CN}', 'private', '游戏', '互联网/科技', 'private',
       '2026-09-18 接入：多益网络社招官网（recruit=20，host 前缀 sz）。同一套 /v40/api，与校招 id 空间不重叠（33 ∩ 57 = 0）。live：自报 total=57，parse 57/57，正文 57/57，jd_url 唯一 57/57，validate_job_quality 57/57 通过，fetch_complete=True；job_type 社会招聘；地点 广州 55 / 苏州 2。'
where not exists (select 1 from public.sources where source_url = 'https://sz.duoyi.com/v40/#/positions');
