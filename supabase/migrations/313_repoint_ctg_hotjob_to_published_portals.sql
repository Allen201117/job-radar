-- 313 — 中国电信国际：两条 hotjob 源从「手机版微招聘」套件改指对外发布的电脑版门户（社招、校招各在一个套件）
--
-- 现象：迁移 099 seed 的两条源（…/SU66e002f31eb8056010bbc32d/pb/social.html、…/pb/school.html）
--       社招自 2026-08-26、校招自 2026-09-05 起每轮 skipped（截至 2026-10-10 累计 218 / 172 轮），error_message 恒为
--       「wecruit portal does not exist (suite/config has no site settings)」；香港库名下只剩 removed 行（40 + 2）。
-- 根因：不是对方关站。SU66e002f3… 是这家公司的**手机版**套件（suite/config 自报 suiteName=电信国际微招聘、
--       templateNum=mc，没有站点配置键），拿它拼电脑版 /pb/ 页面，列表页和详情页都显示「官网不存在，无法继续访问!」
--       ——门 1 拦得对，错的是 seed 时登记的套件。
--       同一个租户（companyId 相同、companyName 都自报「中国电信国际有限公司」）在平台上有 6 个套件，
--       2026-10-10 逐个探过 suite/config + 三个渠道的 search/condition + should_skip：
--         SU66dff1b81eb8056010bb9626  电信国际招聘官网  pb  社招已发布（44 岗）       ← 本迁移社招源
--         SU66e407a36202cc2422a1b5e4  校招职位列表      pb  校招已发布（5 岗）        ← 本迁移校招源
--         SU66e4031d6202cc2422a1ac87  校园招聘          pb  只有介绍页，「立即申请」跳到上一行
--         SU6790ba591c240e2ece7af812  飞龙计划          pb  只发布了 recruitType=13（46 个海外国别总经理 / 副总经理选聘岗）
--         SU66e002f31eb8056010bbc32d  电信国际微招聘    mc  手机版（旧源登记的就是它）
--         SU66e00f881eb8056010bbe634  招聘官网          mc  手机版
-- 归属：官网 www.chinatelecomglobal.com 首页轮播第一张图（「加入我們 未來一起來！」）链到
--       SU66dff1b8…/pb/index.html；该门户 logo 链回官网，导航「校园招聘」→ SU66e4031d… →「立即申请」→ SU66e407a3…。
--       列表每行另有自报的所属单位（8 种写法：本部 / 北京分部 / 新加坡事业部 / 日本株式会社 / 亚太 / 阿联酋 /
--       非洲中东埃及代表处 / 翼威科技有限公司），都在同一棵组织树下；翼威科技是中国电信国际的全资子公司
--       （中国电信股份 2024 年对外担保公告）。没有挂别家公司的岗。
--
-- ── 接入前 live 验过的事实（2026-10-10，不写库）──
-- ① should_skip：SU66dff1b8…/social.html → None；SU66e407a3…/school.html → None。
--    这两个套件的其余渠道、以及另外 4 个套件的三个渠道，全部被门 1 / 门 2 拦下（共 18 个渠道逐个跑过）。
-- ② HotJobAdapter 真跑 should_skip → fetch → parse → validate_job_quality → normalize：
--    社招 44/44、校招 5/5，fetch_complete=True，质量门淘汰 0，正文 ≥60 字 49/49，jd_url 无重复。
-- ③ 浏览器真渲染：social.html「在招职位44个」、school.html「在招职位5个」，与抓到的条数相同；
--    详情页社招 44 条、校招 5 条全部渲染出岗位本身 + 「立即投递」（社招 7 条 + 校招 5 条逐个打开看全文，
--    社招其余 37 条在门户页里用同源 iframe 渲染、等标题和按钮出现；假岗位号对照组 15 秒渲染不出来）。
--    反向：旧套件列表页 + 详情页「官网不存在」；
--    SU66dff1b8… 的 school.html / interns.html「内部处理中，请稍后再试」、校招岗详情页一直「正在加载中」。
-- ④ 地区（regions 保持 {CN} 不改；hotjob adapter 不按 regions 丢岗，范围由每个岗的地点判）：
--    社招 44 = 国内 34（大陆 15 / 香港 19）+ 海外 10（新加坡 5 / 日本 3 / 阿联酋 1 / 埃及 1）；校招 5 个全在香港（国内）。
--    2 个「马来西亚、深圳市」一岗两地的按深圳记国内。
-- ⑤ 招聘类型（项目自己的分类器）：社招 44/44 判社招；校招 5 个判校招 4、社招 1
--    （Network Trainee：英文正文里的 "professional skills" 被通用规则认成社招标记，不是本源特有）。
--
-- ⚠️ 实习渠道 6 个套件都没发布、列表也是 0 岗；飞龙计划那 46 个岗是 recruitType=13，adapter 不认这个渠道，
--    且是海外高管选聘，**都刻意不接**。
-- ⚠️ 校招源公司名去掉「 校招」后缀：jobs.company 取自 sources.company，带后缀的名字会原样显示在岗位卡上、
--    并让同一家公司在筛选里变成两家。渠道由 board 列（按 source_url 生成，school.html → campus）区分，不靠公司名。
-- ⚠️ 顺序：先把香港库里「旧套件链接 + 岗位号仍在门户列表里」的 removed 行换成新门户链接（社招 18 行 / 校招 1 行，
--    只换 jd_url / apply_url 里的套件号），再合本迁移——这样首轮抓取按 canonical 命中旧行、复活成 active 并保留
--    6~8 月的首见时间；反过来这 19 个岗会以新行入库、首见时间变成今天。其余 23 行（岗位已不在列表）保持 removed 不动。
-- 可逆：source_url / company / notes 改回原值即可。幂等：id + 旧 source_url 双重限定，重复执行无副作用。
-- 不写 board 列（generated）；segment / industry / industry_group / ownership / regions 不动。

update public.sources
   set source_url = 'https://wecruit.hotjob.cn/SU66dff1b81eb8056010bb9626/pb/social.html',
       notes      = '2026-10-10 由手机版套件 SU66e002f3…（电脑版页面显示「官网不存在」）改指对外发布的「电信国际招聘官网」社招渠道；官网首页轮播图链到这个门户。租户自报 companyName=中国电信国际有限公司。live：44/44，fetch_complete=True；浏览器验证列表页 + 44 条详情页。'
 where id = 'aae8c97d-3b4f-44c3-96a2-15b06f289800'
   and source_url = 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/social.html';

update public.sources
   set company    = '中国电信国际',
       source_url = 'https://wecruit.hotjob.cn/SU66e407a36202cc2422a1b5e4/pb/school.html',
       notes      = '2026-10-10 由手机版套件 SU66e002f3… 改指「校招职位列表」套件的校招渠道（招聘官网导航「校园招聘」→ 介绍页「立即申请」跳到这里）；公司名去掉「 校招」后缀。租户自报 companyName=中国电信国际有限公司。live：5/5，fetch_complete=True；浏览器验证列表页 + 5 条详情页。实习渠道没有发布，没有入库。'
 where id = '49b0e3a6-80fd-4c0d-ab86-e1f83930dde9'
   and source_url = 'https://wecruit.hotjob.cn/SU66e002f31eb8056010bbc32d/pb/school.html';
