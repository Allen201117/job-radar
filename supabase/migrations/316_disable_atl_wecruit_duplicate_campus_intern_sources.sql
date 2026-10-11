-- 316 — 宁德新能源（ATL）：校招 / 实习各登记了两条源（同一个套件挂在两个域名上），停用 wecruit.hotjob.cn 那两条
--
-- ⚠️ 草稿：等创始人同意后才合 main（push main 即由 migrate.yml 应用到 Supabase）。合完按文末「顺序」处理香港库存量行。
--    前缀取 316：写的时候 314、315 已被另外两个还没合的本地分支占用；合之前再 `ls supabase/migrations` 确认没撞。
--
-- 现象：香港 jobs 库里宁德新能源的校招 52 个岗、实习 9 个岗各有两行 active（61 对、122 行），一行公司名「宁德新能源」、
--       另一行「宁德新能源 ATL 校招」/「宁德新能源 ATL 实习」——用户看到两张卡，同一家公司在库里是三个公司名。
-- 根因：同一个 hotjob 套件 SU5ff30f5b…（租户自报 companyName=新能源科技有限公司、suiteName=ATL新能源招聘官网）
--       在 sources 里登记了两份、都启用：
--         atl.hotjob.cn      school.html 411363e9… / interns.html 892740de…   公司名「宁德新能源」                  ← 保留
--         wecruit.hotjob.cn  school.html 485edff7… / interns.html bfc0263a…   公司名「宁德新能源 ATL 校招 / 实习」  ← 本迁移停用
--       两个域名回的是同一份数据，jd_url 只差域名 → canonical_jd_url 不同，active 唯一索引拦不住。
--       社招那一对（f615f4c2… / 3cdad585…）由迁移 314 处理，本迁移不碰；两个迁移互不依赖，先后都行。
--
-- 为什么留 atl.hotjob.cn 那份：
--   ① 公司名不带渠道后缀。jobs.company 取自 sources.company，带后缀的名字原样显示在岗位卡上；渠道由 board 列区分。
--   ② 用户操作落在它上面的多：16 条（另一份 4 条；20 条都来自同一个用户）。
--   ③ 迁移 314 给社招留的也是 atl.hotjob.cn，三个渠道保持同一个域名。
--   代价：atl.hotjob.cn 是租户自己绑的品牌域名，平台域名是 wecruit.hotjob.cn。哪天对方解绑品牌域名，这两条源会连不上
--   （记 failed，不是静默 0 岗），那时把 source_url 的域名换成平台域名即可。
--
-- ── 上线前 live 验过的事实（2026-10-11，不写库）──
-- ① sources：上面 6 行都在、都 enabled。最近一轮（2026-10-10 22:5x UTC）两边校招都是 success 52/52、实习 success 1/1，都记抓全。
-- ② 香港库按 jd_url 里的 postId 对拍：校招 52 对、实习 9 对，两边都是 active；只在一边有的 0 行（两个方向各 0）；
--    成对的两行标题 / 地点 / 招聘类型不同的各 0 对；同域名同岗位号多行 0。
-- ③ 两道门（HotJobAdapter._gate，两道门都真探到了答复）：两个域名的 school.html、interns.html 都放行；
--    两个域名的 suite/config 自报相同（companyId 相同）。
-- ④ 浏览器真渲染（门户页里同源 iframe，等「库里的标题 + 立即投递 + 正文」都出现）：两个域名各 61 条详情页
--    全部渲染出岗位本身；每批混入的 3 个假岗位号都显示「该职位招聘已经关闭」。
-- ⑤ 实习：列表页与列表接口现在只回 1 个岗（秋招校园大使；门户导航里这个渠道叫「校园大使」），库里每份 9 行。
--    多出来的 8 行（末见 2026-08-18）不是死岗：详情接口 state=200、canDelivery=true，详情页渲染出完整岗位和「立即投递」
--    ——对方只是不再把它们放进列表。不下架；逐岗探活（认 state=1017）够得着它们（18 行最近一次探活都在
--    2026-10-10 23:47~23:50 北京时间），对方关闭后会自己下架。
--
-- ── 顺序（存量在香港 jobs 库，不是本迁移能做的）──
-- 1) 合本迁移。合之前 `gh run list --status in_progress` 看有没有在飞的抓取轮。
-- 2) 等创建时间早于迁移生效的抓取轮（daily-job-crawl / campus-crawl / enrich-crawl）过完这两条源再动存量：run.py 的源清单是
--    整轮开跑时一次读进去的，在飞的那一轮仍按 enabled=true 抓，会把 removed 翻回 active（迁移 311 踩过）。
-- 3) remove-jobs-by-url-prefix 把 wecruit.hotjob.cn 那份的 active 行标 removed（可逆），只标保留门户下有在招孪生的：
--      url_prefix        https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/posDetail.html
--      only_twins_under  https://atl.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/posDetail.html
--      twin_key          postid
--      company           「宁德新能源 ATL 校招」（预期 52 行）、「宁德新能源 ATL 实习」（预期 9 行），各跑一次，先 dry-run。
--    2026-10-11 拿脚本自己拼出来的 SQL 在真库上只读数过：52 / 9，带不带孪生条件相同。
-- 4) 隔几分钟回读一次计数（按域名 × 渠道 × 状态），别只看脚本自己报的数。
-- 指向 wecruit.hotjob.cn 那份的 4 条用户操作（同一个用户、落在 3 个校招岗上：saved 1 / ignored 1 / viewed 2）不由本迁移处理。
--
-- 可逆：enabled 改回 true、notes 改回原值；removed 行在源重新启用后的下一轮抓取里自己翻回 active。
-- 幂等：id + source_url + enabled 三重限定，重复执行改 0 行。
-- 不写 board 列（generated）；company / segment / industry / industry_group / ownership / regions 不动。

update public.sources
   set enabled = false,
       notes   = '2026-10-11 停用：与「宁德新能源」校招源（atl.hotjob.cn 上的同一个套件 SU5ff30f5b…）是重复源，两边岗位号逐个相同（52/52），jd_url 只差域名。原备注：' || coalesce(notes, '')
 where id = '485edff7-65ba-4e56-bb40-1b417856cb8e'
   and source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/school.html'
   and enabled;

update public.sources
   set enabled = false,
       notes   = '2026-10-11 停用：与「宁德新能源」实习源（atl.hotjob.cn 上的同一个套件 SU5ff30f5b…）是重复源，两边岗位号逐个相同（9/9），jd_url 只差域名。原备注：' || coalesce(notes, '')
 where id = 'bfc0263a-5ac5-431b-adb2-b79f086f64d2'
   and source_url = 'https://wecruit.hotjob.cn/SU5ff30f5b9b0d78e6f4283a0b/pb/interns.html'
   and enabled;
