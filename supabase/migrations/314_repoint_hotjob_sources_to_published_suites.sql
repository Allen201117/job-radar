-- 314 — 被两道门拦下的 19 条 hotjob 源逐家复核：登记错套件的改指已发布的套件，对方关站 / 只剩手机版的停用并换源
--
-- 创始人 2026-10-11 同意。⚠️ 合 main 之前必须先按文末「顺序」处理香港库存量行（push main 即由 migrate.yml 应用到 Supabase）。
--
-- 现象：这 19 条启用中的源最近一轮 crawl_runs 都是 skipped，error_message 是
--       「wecruit portal does not exist」（门 1，12 条）或「wecruit channel not published」（门 2，7 条），多数已持续一个多月。
-- 根因：门拦得都对（旧链接真渲染是「官网不存在」/「内部处理中」），但「这个套件没发布这个渠道」不等于「这家公司没开」
--       ——一个租户可以开多个套件（迁移 313 中国电信国际是第一例）。2026-10-11 逐家查了 suite/config、
--       各渠道的 search/condition、官网招聘入口和门户导航：12 家公司共查到 37 个套件号（2 个已被对方关闭）。
--       ⚠️ 平台没有「列出一家公司全部套件」的公开接口，套件是顺着关联手机版、门户导航、官网入口找出来的，不保证找全。
--
-- ── A. 登记错套件，同租户另有已发布的套件（9 条改指 + 1 条重复源停用）──
--   公司            旧套件                 新套件（社招）              依据
--   中信卡中心      SU621d83d4…（手机版）  SU621d903f… 160 岗          官网页脚「人才招聘」→ /zhaopin/ → 这个套件
--   凌志软件        SU650be0e5…（手机版）  SU650be432… 75 岗 / 校招 14  官网不链招聘平台；新套件的关联手机版就是旧套件，门户导航「公司官网」回 linkstec.com
--   和睦家医疗      SU614bda3a…（手机版）  SU61274d27… 249 岗 / 校招 11 官网顶栏「加入我们」→ 这个套件
--   赢家时尚        SU64f06038…（手机版）  SU64004c6d… 40 岗            官网导航「社会招聘」「校园招聘」→ 这个套件
--   宁德新能源 ATL  SU5ff30f5b…（校招站）  SU626b761e… 149 岗           官网「职员招聘」→ SU5ff30f5b…，它的导航「社招职位」→ 这个套件
--   歌尔股份        SU65dd9ebd…（校招站）  SU63c50450… 436 岗           官网「招贤纳士 → 社会招聘」直链这个套件；校招站导航「社会招聘」也指它
--   荣耀            SU61b9b999…（实习站）  SU5ff66964… 379 岗           官网 honor.com/cn/career「社招入口」→ 这个套件
--   每个租户的 companyId 新旧套件相同，companyName 自报与库里公司名对得上（凌志自报「苏州工业园区凌志软件股份有限公司」、
--   ATL 自报「新能源科技有限公司」、荣耀自报「荣耀终端股份有限公司」）。列表每行自报的所属单位都在本公司名下
--   （中信社招：中信银行信用卡中心 50 / 全国分中心 110；和睦家社招：12 个单位、名字都带和睦家；
--   ATL：宁德新能源（ATL-ND）138 / ATLI 11；歌尔、凌志、赢家：只有本公司；荣耀：17 个部门）。
--   宁德新能源另有一条重复源（wecruit.hotjob.cn 上同一个套件，公司名「宁德新能源 ATL」）：停用，留 atl.hotjob.cn 那条。
--
-- ── B. 对方换了平台 / 只剩手机版（5 条停用 + 1 条新增替代源）──
--   新城控股 ×3：套件已被对方关闭——suite/config 回「该官网已关闭，无法继续访问!」，页面显示「系统正在维护中」。
--     官网 seazen.com.cn/join/「我要应聘」现在指向 Moka（app.mokahr.com/social-recruitment/seazen/168435，页面写 49 个在招）。
--     Moka 源没有放进本迁移：本机没有 Playwright 浏览器，moka adapter 的端到端试抓没跑成，只用浏览器看过页面。
--   光启技术 ×2：这个租户在新版平台上只找到手机版套件（templateNum=mc）；电脑版是老版门户
--     kuangchi.hotjob.cn/wt/kuangchi（title「光启集团招聘官网」，列表发布机构「光启技术股份有限公司」等 4 个）。
--     两边岗位名逐个相同（社招 42 / 校招 12；老版门户上校招栏那 12 个岗位号都在社招栏里）。换成一条 wt 源。
--     ⚠️ 光启官网（kc-t.cn）从本机连不上，「官网入口链到这个门户」没有亲眼确认；归属只有门户自报这一层。
--
-- ── C. 对方确实没在电脑版发布这个渠道（4 条源；3 条不动，1 条只换套件号）──
--   华润水泥（现名华润建材科技）实习、易方达基金实习、奇安信实习：同租户所有电脑版套件的实习渠道都没发布，
--     各只有 1 个岗（华润只在手机版套件发布；易方达手机版也没发布；奇安信没找到手机版套件）。本迁移不动。
--     奇安信官网「社会招聘」指向的是老版门户 www.hotjob.cn/wt/qianxin（社招 72 / 实习栏 2），与现有 hotjob 源是
--     同一家的两个前台；换不换前台是另一件事，没有动。
--   和睦家医疗实习：电脑版套件实习渠道没发布（7 个岗只在手机版）。只把套件号换成电脑版——仍被门 2 拦下、
--     不产出，但对方哪天在电脑版发布了会自己放行；留在手机版套件上则永远被门 1 拦着。
--
-- ── 和睦家校招为什么只有 11 岗：依赖同一次提交里的 adapter 改动 ──
--   电脑版套件的校招列表有 34 行，其中 23 行是母集团「新风天域」另一个租户的套件（SU66b18895…）发布的
--   （列表行 currentSuiteKey 指向它）。按和睦家套件拼的详情页这 23 行全部显示「该职位招聘已经关闭」，
--   门户自己点开的是新风天域套件的详情页；其中 7 行是易得康 / 顾连医疗 / 柏盛健康 / 集团总部的岗。
--   adapter 现在不收 currentSuiteKey 不是本套件的行（crawler/adapters/hotjob.py 的 _is_foreign_row）；
--   这 23 行由下面新增的「新风天域」源从它自己的套件抓，链接和公司名都对。
--   ⚠️ 本迁移必须和那处 adapter 改动一起上线，否则和睦家校招会写进 23 条打不开的链接。
--
-- ── 上线前 live 验过的事实（2026-10-11，不写库）──
-- ① 两道门（HotJobAdapter._gate，确认两道门都真探到了答复）：下面每个新地址放行；21 个电脑版套件 × 3 个渠道逐个跑过。
-- ② 真跑 should_skip → fetch → parse → validate_job_quality → normalize，全部 fetch_complete=True、质量门淘汰 0、
--    jd_url 无重复：中信社招 160 / 校招 10，凌志 75 / 14，和睦家社招 249 / 校招 11（列表 34），赢家 40 / 12，
--    ATL 149，歌尔 436，荣耀社招 379 / 博士生 38，新风天域校招 23；光启（wt adapter）42。
-- ③ 浏览器真渲染：每个新地址的列表页显示的在招数与抓到的条数相同（和睦家校招页面显示 34）；详情页**逐条**打开
--    （门户页里同源 iframe，等岗位标题和「立即投递」出现）——中信 160+10、凌志 75+14、和睦家社招 249 + 校招 11、
--    赢家 40+12、ATL 149、歌尔 436、荣耀 379+38、新风天域 23、光启 42，共 1,638 条全部渲染出岗位本身；
--    每批混入的假岗位号都显示「已经关闭」。hotjob 各批在页面里翻出来的岗位号集合与 adapter 抓到的相同（比指纹）。
--    反向：旧地址仍是「官网不存在」（中信）/「内部处理中」（ATL、歌尔、荣耀）/「系统正在维护中」（新城）。
-- ④ 库里没有任何行已经在这些新地址下（香港库按套件号 / 门户前缀查，0 行）。
--
-- ── 顺序（存量在香港 jobs 库，都不是本迁移能做的）──
-- 1) 先把香港库里这些源名下的 removed 行换成新套件号（只换 jd_url / apply_url 里的套件号），走
--    rewrite-jd-url-prefix 工作流的 status=removed（按「公司 + 旧前缀」圈行，9 组）：
--    中信 164、凌志 73 + 校招 13、和睦家 236 + 校招 11、赢家 40、宁德新能源 148、歌尔 410、荣耀 411，共 1,506 行；
--    其中 1,381 行的岗位号今天仍在新列表里，另外 125 行的岗已不在列表（换完仍是 removed、没人看得见）。
--    CI dry-run（2026-10-11）：9 组行数如上、冲突 0；圈到的都是要换的那个渠道
--    （宁德新能源同名同前缀下的校招 / 实习行都是 active，不在范围内）。
--    这样首轮抓取按 canonical 命中旧行、翻回 active 并保留 6~8 月的首见时间；反过来这些岗会以新行入库、首见时间变成当天。
-- 2) 新城控股校招名下还有 1 行 active（末见 2026-09-09，链接现在打开是「系统正在维护中」）：
--    走 remove-jobs-by-url-prefix 工作流标 removed（dry-run：1 行）。
-- 3) 再合本迁移。合之前看一眼有没有正在跑的抓取轮；合完回读每条源的 crawl_runs。
-- 可逆：source_url / company / enabled / notes 改回原值、删掉新增的 5 行即可。幂等：update 都是 id + 旧值双重限定，
-- insert 带 not exists。不写 board 列（generated）；segment / industry / industry_group / ownership / regions 不动。

-- ── A. 改指已发布的套件 ──
update public.sources
   set source_url = 'https://wecruit.hotjob.cn/SU621d903fbef57c221e5ca37f/pb/social.html',
       notes      = '2026-10-11 由手机版套件 SU621d83d4…（电脑版页面显示「官网不存在」）改指电脑版「中信卡中心招聘」社招渠道；官网页脚「人才招聘」指向这个套件。租户自报 companyName=中信银行信用卡中心。live：160/160，fetch_complete=True；浏览器验证列表页 + 160 条详情页。'
 where id = 'f240af3d-b21a-4862-9cc1-4cd27ce7ea1e'
   and source_url = 'https://wecruit.hotjob.cn/SU621d83d4bef57c221e5c9d8c/pb/social.html';

update public.sources
   set source_url = 'https://wecruit.hotjob.cn/SU650be4328ac1ca0dbb8fcdb5/pb/social.html',
       notes      = '2026-10-11 由手机版套件 SU650be0e5… 改指电脑版「凌志软件招聘」社招渠道（新套件的关联手机版就是旧套件）。租户自报 companyName=苏州工业园区凌志软件股份有限公司；官网 linkstec.com 不链招聘平台。live：75/75，fetch_complete=True；浏览器验证列表页 + 75 条详情页。'
 where id = 'a88492c9-3322-4b23-8f80-2d1b17f016d6'
   and source_url = 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/social.html';

update public.sources
   set company    = '苏州凌志软件',
       source_url = 'https://wecruit.hotjob.cn/SU650be4328ac1ca0dbb8fcdb5/pb/school.html',
       notes      = '2026-10-11 由手机版套件 SU650be0e5… 改指电脑版套件的校招渠道；公司名去掉「 校招」后缀（渠道由 board 列区分）。live：14/14，fetch_complete=True；浏览器验证列表页 + 14 条详情页。'
 where id = '286769fb-2951-4f4c-a78c-482422e33c7a'
   and source_url = 'https://wecruit.hotjob.cn/SU650be0e58ac1ca0dbb8fc5c8/pb/school.html';

update public.sources
   set source_url = 'https://wecruit.hotjob.cn/SU61274d270dcad4106f13e9e1/pb/social.html',
       notes      = '2026-10-11 由手机版套件 SU614bda3a… 改指电脑版「和睦家医疗招聘官网」社招渠道；官网 ufh.com.cn 顶栏「加入我们」指向这个套件。租户自报 companyName=和睦家医疗。live：249/249，fetch_complete=True；浏览器验证列表页 + 249 条详情页。'
 where id = 'faae6844-4d41-482e-bcc5-3c69d5aac057'
   and source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/social.html';

update public.sources
   set company    = '和睦家医疗',
       source_url = 'https://wecruit.hotjob.cn/SU61274d270dcad4106f13e9e1/pb/school.html',
       notes      = '2026-10-11 由手机版套件 SU614bda3a… 改指电脑版套件的校招渠道；公司名去掉「 校招」后缀。列表 34 行里 23 行是新风天域集团的套件发布的（按本套件拼的详情页打不开），adapter 不收，由「新风天域」源抓。live：本套件 11/11；浏览器验证 11 条详情页正常、另外 23 条显示「已经关闭」。'
 where id = 'f1965126-7f9e-41a8-a1e1-3c660c594803'
   and source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/school.html';

update public.sources
   set company    = '和睦家医疗',
       source_url = 'https://wecruit.hotjob.cn/SU61274d270dcad4106f13e9e1/pb/interns.html',
       notes      = '2026-10-11 套件号由手机版 SU614bda3a… 换成电脑版；公司名去掉「 实习」后缀。电脑版套件的实习渠道对方没发布（7 个岗只在手机版），这条源仍被门 2 拦下、不产出；对方发布后自动放行。'
 where id = 'bf289adb-4331-4ea2-a281-2fb1cfe223e5'
   and source_url = 'https://wecruit.hotjob.cn/SU614bda3abef57c54dcbaf22f/pb/interns.html';

update public.sources
   set source_url = 'https://wecruit.hotjob.cn/SU64004c6dbef57c71d90a1ee9/pb/social.html',
       notes      = '2026-10-11 由手机版套件 SU64f06038… 改指电脑版「赢家时尚招聘官网」社招渠道；官网 eekagroup.com 导航「社会招聘」指向这个套件。租户自报 companyName=赢家时尚控股有限公司。live：40/40，fetch_complete=True；浏览器验证列表页 + 40 条详情页。'
 where id = '61f03307-144e-4d40-b649-d9ff872d33d2'
   and source_url = 'https://wecruit.hotjob.cn/SU64f060386202cc142abc52eb/pb/social.html';

update public.sources
   set source_url = 'https://atl.hotjob.cn/SU626b761ebef57c796a85418f/pb/social.html',
       notes      = '2026-10-11 由校招站套件 SU5ff30f5b…（社招渠道没发布，页面「内部处理中」）改指社招站套件；官网 atlbattery.com「职员招聘」→ SU5ff30f5b…，其导航「社招职位」→ 本套件。租户自报 companyName=新能源科技有限公司，列表所属机构：宁德新能源（ATL-ND）138 / ATLI 11。live：149/149，fetch_complete=True；浏览器验证列表页 + 149 条详情页。'
 where id = 'f615f4c2-0bbd-4d55-ba17-48f739cbd9c0'
   and source_url = 'https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html';

update public.sources
   set enabled = false,
       notes   = '2026-10-11 停用：与「宁德新能源」社招源是同一个租户的重复源（另一个 host 上的同一个套件），社招已由 atl.hotjob.cn/SU626b761e… 那条源抓。原备注：' || coalesce(notes, '')
 where id = '3cdad585-de56-4889-a33f-6a5e35a43077'
   and source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/social.html'
   and enabled;

update public.sources
   set source_url = 'https://goertek.hotjob.cn/SU63c504500dcad47488051f3c/pb/social.html',
       notes      = '2026-10-11 由校招站套件 SU65dd9ebd…（社招渠道没发布）改指「歌尔股份招聘官网」套件的社招渠道；官网 goertek.com「招贤纳士 → 社会招聘」直链这个套件，校招站导航「社会招聘」也指它。租户自报 companyName=歌尔股份有限公司。live：436/436，fetch_complete=True；浏览器验证列表页 + 436 条详情页。'
 where id = 'ec9b38f0-c82d-4406-81e9-5727031337a1'
   and source_url = 'https://goertek.hotjob.cn/SU65dd9ebd1c240e4b11c4f491/pb/social.html';

update public.sources
   set source_url = 'https://career.honor.com/SU5ff669649b0d78e6f4296c9a/pb/social.html',
       notes      = '2026-10-11 由实习站套件 SU61b9b999…（社招渠道没发布）改指社招套件；官网 honor.com/cn/career「社招入口」指向这个套件。租户自报 companyName=荣耀终端股份有限公司。live：379/379，fetch_complete=True；浏览器验证列表页 + 379 条详情页。'
 where id = '0550d53d-1d85-4237-86a4-87e292e00188'
   and source_url = 'https://career.honor.com/SU61b9b9992f9d24431f5050a5/pb/social.html';

-- ── B. 对方关站 / 只剩手机版：停用 ──
update public.sources
   set enabled = false,
       notes   = '2026-10-11 停用：对方已关闭这个套件（suite/config 回「该官网已关闭」，页面「系统正在维护中」）；官网「我要应聘」现指向 Moka app.mokahr.com/social-recruitment/seazen/168435，尚未接入。原备注：' || coalesce(notes, '')
 where id in ('e159e189-064a-477c-beaf-6aa992889c35',
              '38f87e02-7ab5-4015-a507-b842b37214e1',
              '1f74eb7a-a1ae-433d-b04c-8940fdd38845')
   and source_url like 'https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/%'
   and enabled;

update public.sources
   set enabled = false,
       notes   = '2026-10-11 停用：登记的是手机版套件（templateNum=mc，电脑版页面「官网不存在」），这个租户在新版平台上没找到电脑版套件；改由老版门户 kuangchi.hotjob.cn/wt/kuangchi 那条 wt 源抓（同一批岗）。原备注：' || coalesce(notes, '')
 where id in ('6d7f54f8-7f5a-49b4-96e6-b0b8ecb3c0bb',
              '6eb41239-df65-44a6-8be0-36947b49bbf7')
   and source_url like 'https://wecruit.hotjob.cn/SU60b9cab4bef57c11896a86b4/pb/%'
   and enabled;

-- ── 新增 5 条（同租户已发布、库里没登记的渠道；光启的替代源；和睦家校招里那 23 行的真正出处）──
insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', v.adapter, 'http', true, '{CN}', 'private', v.industry, v.industry_group, 'private', v.notes
from (values
  ('中信银行信用卡中心', 'https://wecruit.hotjob.cn/SU621d903fbef57c221e5ca37f/pb/school.html', 'hotjob', '银行', '金融',
   '2026-10-11 接入：与社招源同一个电脑版套件的校招渠道（2027 年校园招聘）。live：10/10，fetch_complete=True；浏览器验证列表页 + 10 条详情页。'),
  ('赢家时尚', 'https://wecruit.hotjob.cn/SU64004c6dbef57c71d90a1ee9/pb/school.html', 'hotjob', '消费·服饰', '消费/零售',
   '2026-10-11 接入：与社招源同一个电脑版套件的校招渠道；官网 eekagroup.com 导航「校园招聘」指向它。live：12/12，fetch_complete=True；浏览器验证列表页 + 12 条详情页。'),
  ('荣耀 Honor', 'https://career.honor.com/SU60eea1aa0dcad47a7e1ce1ed/pb/school.html', 'hotjob', '手机/智能终端', '制造/工业',
   '2026-10-11 接入：博士生校招套件（迁移 245 当时没核验、没接）；官网 honor.com/cn/career「校招入口 → 博士生」指向它，与应届生套件岗位不重叠。live：38/38，fetch_complete=True；浏览器验证 38 条详情页。'),
  ('新风天域', 'https://wecruit.hotjob.cn/SU66b188951c240e4f7f8eac8c/pb/school.html', 'hotjob', '医疗健康', '医疗/医药',
   '2026-10-11 接入：和睦家母集团的 2027 校园招聘套件（租户自报 companyName=新风天域，suiteName=新风天域集团校园招聘）。和睦家门户校招列表里「业务单元=新风天域集团」的 23 行就是它发布的，详情页只在本套件下能打开。所属单位：和睦家各医院 16 / 易得康 3 / 顾连医疗 2 / 柏盛健康 1 / 集团总部 1。live：23/23，fetch_complete=True；浏览器验证 23 条详情页。'),
  ('光启技术', 'https://kuangchi.hotjob.cn/wt/kuangchi/web/index', 'wt', '科技·军工', '制造/工业',
   '2026-10-11 接入：光启的电脑版门户是老版 wt（title「光启集团招聘官网」，列表发布机构「光启技术股份有限公司」等 4 个），取代登记在手机版套件上的两条 hotjob 源。live（wt adapter）：42/42（其中 12 个同时挂在校招栏），fetch_complete=True；浏览器验证 42 条详情页。官网 kc-t.cn 从本机连不上，官网入口未亲眼确认。')
) as v(company, url, adapter, industry, industry_group, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);
