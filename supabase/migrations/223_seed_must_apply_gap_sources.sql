-- 223 — 必投清单「A 类缺口」补源（连一行 source 都没有的公司）
--
-- 背景（2026-09-04 缺口普查）：必投清单 11 行业 × 30 家 = 330 家里，93 家在 sources 表里
-- **一行都没有**。本迁移接入其中 6 家 —— 每一家都跑过真 adapter 的 live 探活，
-- 「列表接口能返数」不算通过，必须**逐岗详情页实测能打开且页面上真有这个岗位**才入库。
--
-- ⚠️ 本轮最重要的**否定结论**（写在这里，免得下一个人再花一天重走）：
--   · **国聘（iguopin）对这 93 家是死路**。逐个关键词翻到底（每词扫 ~380 条）后，
--     只有「韵达 3 条 / 工商银行 1 条」能过核名门，其余 91 家 0 条 —— 国聘的关键词搜索是
--     集团级模糊匹配，搜「中国建设银行」返回的是乐山市商业银行。这类源加进来就是张冠李戴。
--   · **万达集团不是新发现**：wanda.hotjob.cn 早已在库（625 岗）。它和「万达电影」是清单里
--     **两条不同的公司**，而那 448 个岗 org 全是珠海万达商管/宝贝王/文旅，**没有一个属于
--     万达电影** —— 所以不许把这个源改名成「万达电影」去点亮指标。
--
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'；写 'browser' 会让**整批**回滚（迁移 211 踩过）。
-- ⚠️ **不要写 board 列**：它是 GENERATED ALWAYS AS classify_source_board(adapter_name, source_url)
--    的派生列（迁移 187），显式赋值会报 `cannot insert a non-DEFAULT value into column "board"`
--    并让整批回滚（本迁移第一版就是这么挂的）。板块由 adapter + URL 自动算：
--    wt/beisen → mixed；campus.10jqka.com.cn 命中 URL 校招令牌 → campus。

-- ① 中国太平洋保险（金融）—— 老版 WinTalent，与中国电信/海澜之家同一个 www.hotjob.cn 共享 host。
-- live 2026-09-04：社招 15 岗，orgName 全是「中国太平洋保险（集团）股份有限公司」。
-- jd_url 实测：www.hotjob.cn/wt/CPIC/mobweb/position/detail?...&postIdsAry=206101 → 200 且含岗位名。
-- ⚠️ 之前判「太保无公开门户」是错的：talent.cpic.com.cn 确实是要登录的内部 HCM，
--    但招聘挂在 hotjob 的 wt 上，brand code = CPIC。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '中国太平洋保险', 'https://www.hotjob.cn/wt/CPIC/web/index', 'official', 'wt', 'http',
       'soe', '金融', 
       '中国太平洋保险（老版 WinTalent，brand=CPIC，与中国电信 CT / 海澜之家 HLA 共用 www.hotjob.cn）。'
       'live 2026-09-04：社招 15 岗（校招/实习渠道当前 0），逐岗 mobweb/position/detail 实测可开。'
where not exists (select 1 from sources where source_url = 'https://www.hotjob.cn/wt/CPIC/web/index');

-- ② 巴斯夫（能源/化工）—— 同上，brand code = BASF。当前只有 1 个在华岗，量小但真实。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '巴斯夫', 'https://www.hotjob.cn/wt/BASF/web/index', 'official', 'wt', 'http',
       'foreign', '能源/化工', 
       '巴斯夫中国（老版 WinTalent，brand=BASF）。live 2026-09-04：社招 1 岗，'
       'orgName「巴斯夫（中国）有限公司」，逐岗详情页实测可开。量小属正常波动，勿据此 disable。'
where not exists (select 1 from sources where source_url = 'https://www.hotjob.cn/wt/BASF/web/index');

-- ③ 儒意影业（传媒/文娱）—— 北森新版租户 ruyifilm.zhiye.com。
-- live 2026-09-04：61 岗过质量门（在华 45），jd_url = /social/detail?jobAdId={uuid} 实测可开。
-- ⚠️ 同批探到的 huace.zhiye.com **不是华策影视、是华测导航（CHC Navigation）**，已丢弃。
--    北森租户 slug 撞名很常见，入库前必须核对门户页 title 自报的公司名。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '儒意影业', 'https://ruyifilm.zhiye.com/social', 'official', 'beisen', 'playwright',
       'private', '传媒/文娱', 
       '儒意影业（北森租户 ruyifilm，门户 title 自报「儒意电影」）。live 2026-09-04：61 岗，'
       '含影城储备干部等院线岗。⚠️ 岗位行不自带 company，靠 sources.company 兜底。'
where not exists (select 1 from sources where source_url = 'https://ruyifilm.zhiye.com/social');

-- ④ 壳牌（能源/化工）—— Workday 租户 shell/wd3，site = shellcareers。
-- live 2026-09-04：在华 9 岗，jd_url 实测 .../job/Hong-Kong---The-Millennity/...R203783-1 可开。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, regions, notes)
select '壳牌', 'https://shell.wd3.myworkdayjobs.com/wday/cxs/shell/shellcareers/jobs', 'official', 'workday', 'http',
       'foreign', '能源/化工', '{CN}',
       '壳牌（Workday 租户 shell.wd3，site=shellcareers）。live 2026-09-04：在华 9 岗。'
       'jobs.shell.com 会 302 到这里，所以源直接填 wday/cxs JSON 端点。'
where not exists (select 1 from sources where source_url = 'https://shell.wd3.myworkdayjobs.com/wday/cxs/shell/shellcareers/jobs');

-- ⑤ 掌阅科技（传媒/文娱）—— 飞书招聘，租户 id 是随机串 q7w8vltyes（jobs.zhangyue.com 302 过来）。
-- live 2026-09-04：133 岗（社招+实习混在同一门户，标题里就有「短剧运营实习生」）。
-- ⚠️ 该租户**没有** campus / internship 子门户：带 website-path 三个值都返 count=None，
--    只有不带头的默认门户有货。不要照搬别家去派生 /campus/position 子源（会得到 0 岗死源）。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '掌阅科技', 'https://q7w8vltyes.jobs.feishu.cn/index/position', 'official', 'feishu', 'http',
       'private', '传媒/文娱', 
       '掌阅科技（飞书招聘，租户 q7w8vltyes；jobs.zhangyue.com 302 到此）。'
       'live 2026-09-04：133 岗，社招+实习同门户。无 campus/internship 子门户。'
where not exists (select 1 from sources where source_url = 'https://q7w8vltyes.jobs.feishu.cn/index/position');

-- ⑥ 同花顺（金融）—— 自建门户 campus.10jqka.com.cn，新增 adapter `tonghuashun`。
-- live 2026-09-04：99 岗（2027届校园招聘 38 / AIME计划 27 / 日常实习 23 / ACMer摘星 8 / 云软件校招 3），
-- 全部在杭州；jd_url = /job/detail?id=2160 实测渲染出「AIME基座预训练算法工程师」标题 + 完整 JD。
-- ⚠️ 是本轮唯一给必投「金融」补上**校招**供给的源 —— 六大行全部卡在公告制/登录墙（见下）。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '同花顺', 'https://campus.10jqka.com.cn/job/list', 'official', 'tonghuashun', 'http',
       'private', '金融', 
       '同花顺自建门户（campus.10jqka.com.cn）。live 2026-09-04：99 岗，社招/校招/实习共用同一列表接口。'
       '⚠️ 三个坑见 crawler/adapters/tonghuashun.py 文件头：信封是 ex_data 不是 data；'
       'series_id 参数被服务端忽略（按系列循环会把同一批抓 N 遍）；pageSize 被硬顶到 10。'
where not exists (select 1 from sources where source_url = 'https://campus.10jqka.com.cn/job/list');
