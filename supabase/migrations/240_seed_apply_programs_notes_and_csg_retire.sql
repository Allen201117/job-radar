-- 240 — 给 apply_programs 剩下 6 行补内部 notes（2026-09-07 逐家 live 核验）
--       其中南方电网核出来是**假的**，本迁移把它停用。
--
-- 背景：迁移 238 立了「新增 apply_programs 行必须填 notes」的准入要求，理由是
-- 「这家公司客观上没有一岗一页」是个**会自己变坏**的结论，而 gap_census.classify_company
-- 把这类公司钉在 manual_review 且 next_retry_at=None，没有任何自动复查机制。
-- 238 当时只回填了 3 行（波司登 / 国家电网 / 韵达），剩下 6 行一直空着——
-- 也就是说这 6 行到今天为止**没有任何人写下过它们是怎么判出来的**。本迁移补齐。
--
-- ⚠️ 核验前先过一道廉价的门（宽别名正则查香港 jobs 库 + Supabase sources，
--    并把命中的 company 原文打出来自己看——迁移 239 踩过「用单个关键词查漏掉
--    `中国人民保险 校招` 2,631 个在招岗」的坑）：
--      正则 '华能|Huaneng|CHNG|林业|中林|CFGC|Forestry|稀土|Rare Earth|REGCC|中国银行|中银|中行|
--            Bank of China|BOC|南方电网|南网|CSG|Southern Power|国家开发银行|国开|CDB|Development Bank'
--    结果：华能 / 林业 / 稀土 / 中国银行 / 国开行 五家在 jobs 表 0 行、在 sources 表 0 行；
--    **南方电网命中 22 行**，其中「鼎和财产保险股份有限公司（南方电网）」有 105 个 active，
--    并且 sources 里躺着一条 enabled 的 iguopin 源 —— 第一道门就没过（详见下面第 5 段）。
--
-- 📌 写法约定（承迁移 239）：description / notes 一律用美元引号 $md$...$md$，
--    不要单引号 + 相邻字面量拼接。一行写错整个迁移文件一起回滚（迁移 211 的教训）。
--    本文件已用「临时表 + ROLLBACK」在真 PG 上整份跑过一遍再提交。

-- ── 1. 中国华能：全站唯一的详情页是「公告详情」，按岗位关键字搜出来的也是公告 ──
update apply_programs
   set notes = $md$判定（2026-09-07 真浏览器渲染 + 读它自己的前端路由表）：站点是 uni-app 打的单包 SPA，桌面端也强制跳 /h5/#/，只有一个 bundle ⇒ 路由表就是全站页面清单。25 条路由里招聘侧只有 Announcement/index（公告列表）、noticeDetail（公告详情）、recruit/recruit + recruit/managementTraineeRecruit（按单位分类的招聘信息）、lecture（宣讲会），其余全是登录/简历/收藏/投递记录。**没有任何 jobDetail / positionDetail 路由**。
更硬的一条证据：recruit 页点「招聘单位」跳的是 /pages/noticeDetail/noticeDetail?recruitType&taskType&companyId&columnId；搜索框写着「请输入招聘单位或**岗位**关键字」，但搜索结果渲染的组件是 NoticeItem —— **按岗位关键字搜出来的也是公告**，不是岗位。公告接口 /recruit/announcement/index 自报 total=167，返回行里 positions 恒为 null。
⏳ 复查：① 路由表出现 jobDetail / positionDetail 类页面；② POST /recruit/position/indexPositions 开始返回岗位列表（现在返 {"code":500,"msg":"系统异常"}）。任一成立 ⇒ 撤下本行、改接正常源。
⚠️ 边界一：那个 500 **不作为「对方没有岗位」的证据**（只证明我走的那条路不通，见 CLAUDE.md 那条碑）；本行结论只靠路由表。
⚠️ 边界二：入口页当前**没有一条在窗公告**。首页与公告列表都只吐同样 5 条，全部 status=3（该站字典里 3=过期），窗口 2025-09-12 ~ 2025-10-31（2026 届）。站点自己的「上拉显示更多」当场报 Failed to convert value of type java.lang.String to required type java.lang.Long; For input string: "undefined" —— 翻不动，所以那 167 条里剩下的 162 条是什么**我没看到**。
⚠️ 边界三：社招侧有没有在窗公告**我没验成**（recruit 页要 columnId 等参数，首页搜索按钮点了无反应）。别把边界二读成「社招也空」。
📅 按上一届节奏（2026 届是 2025-09-12 开的），2027 届大概率就在最近几天发；若到 2026-10 底入口仍全是过期公告，应重新评估这行还该不该对用户展示。$md$,
       updated_at = now()
 where entry_url = 'https://zhaopin.chng.com.cn/';

-- ── 2. 中国林业集团：岗位躺在公告的 .xlsx 附件里 ──
update apply_programs
   set notes = $md$判定（2026-09-07 live，服务端渲染页直接读）：栏目结构是 人力资源 → 人才战略 / 教育培训 / 职称评审 / 人才招聘，人才招聘下只有 校园招聘 + 社会招聘 两个子栏，**没有职位栏**。两栏都是新闻式公告列表（校招最新 2026-08-07，社招最新 2026-03-26）。
关键证据：最新校招公告正文原文「一、招聘岗位 招聘单位及岗位信息详见《中国林业集团有限公司2026年夏季校园招聘岗位信息表》（**附件**）」—— 岗位躺在一个 .xlsx 附件里，站上没有任何一个岗位有自己的页面。
⏳ 复查：人才招聘下出现「职位 / 岗位」子栏，或公告正文不再把岗位塞进附件、而是给出逐岗链接 ⇒ 撤下改接源。
⚠️ 边界一：报名系统是国聘白标站 cfgc2026.iguopin.com（React SPA，2026-09-07 探活 200）。**国聘是本项目允许的第三方例外**（创始人 2026-07-26 拍板），所以「能不能从这个白标站接源」是一条真实线索 —— 本次**只探到首页可开，没有做任何评估**。同样的情况见中国稀土集团那行。
⚠️ 边界二：entry_url 指的是**校园招聘这一个子栏**，不是 人才招聘 父栏；且该栏最新一条的报名窗口（截至 2026-08-12）**已经关了**。想让用户同时看到社招，要么另开一行，要么改指父栏 /cfgc/rlzy/rczp/A149007004Gone1.html。$md$,
       updated_at = now()
 where entry_url = 'https://www.cfgc.cn/cfgc/rlzy/rczp/xyzp/A149007004001Gone1.html';

-- ── 3. 中国稀土集团：公告正文根本不托管在自己站上（全部外链微信公众号）──
update apply_programs
   set notes = $md$判定（2026-09-07 live）：人力资源栏下只有 人才队伍 / 招聘动态 / 教育培训 / 网上公示 四个子栏，**没有职位栏**。
关键证据：招聘动态列表里**每一条的 href 都是 mp.weixin.qq.com/s/...** —— 公告正文根本不托管在 regcc.cn 上，站内自然也不会有岗位页。抽读两条正文：2026-05-25「中国稀土集团有限公司及所属企业招聘公告」原文写「二、招聘岗位 招聘岗位职责及任职要求**详见简历投递渠道**」，报名方式「网页投递链接：https://regccsz.iguopin.com/」—— 岗位职责压根不在公告里，在国聘白标投递系统里。
⏳ 复查：招聘动态的条目从 mp.weixin.qq.com 换成 regcc.cn 自己的详情页且内容是单个岗位，或人力资源栏下新增职位 / 岗位子栏 ⇒ 撤下改接源。
⚠️ 边界一：该栏最新两条（2026-08-31 直管企业负责人竞聘 / 2026-08-13 财务总监招聘）都是**系统内公开竞聘或高管岗**，报名走 glryzp@regcc.cn 邮箱 + Word 报名表，普通社会求职者投不了；最近一条面向社会的是 2026-05-25。用户点进来会看到不少自己投不了的条目 —— 这行的用户价值比另外几行弱。
⚠️ 边界二：列表共 6 页，**我只读了第 1 页**并抽读 2 条正文，没有逐条读完。
⚠️ 边界三：同中国林业集团 —— 投递在国聘白标站（regccsz.iguopin.com），能否接源本次未评估。$md$,
       updated_at = now()
 where entry_url = 'https://www.regcc.cn/zgxtjt/zpdt/list.shtml';

-- ── 4. 中国银行：网站地图全集核对，全站只有「招聘公告」一个招聘栏目 ──
update apply_programs
   set notes = $md$判定（2026-09-07 live，用官网**网站地图**做全集核对，不是靠点击）：网站地图页 /custserv/cs1/200812/t20081209_135605.html 上与招聘相关的链接**只有一条**：关于中行 > 招聘公告 /aboutboc/bi4/。全站没有职位 / 岗位栏目。该栏是纯公告列表，共 18 页，最新一条是 2026-09-03「中国银行股份有限公司2027年全球校园招聘公告」。
逐字读了那条 2027 公告：岗位是**成段文字描述**（总行管培生 6 个方向 / 小语种专项计划 / 总行直属机构 10 家 / 审计分部 / 境内分行 4 类 / 港澳台及海外机构 / 综合经营公司），没有一个岗位带链接；原文写「具体的招聘岗位、应聘条件，请登录中国银行校园招聘网站查询」，报名网址 https://campus.chinahr.com/pages/2027-boc（中华英才网），报名截止 2026 年 10 月 9 日 24 点。
⏳ 复查：① 网站地图上出现 bankofchina.com 自有域名下的岗位列表 / 详情页；② 公告里的报名网址从第三方换回自有域名。任一成立 ⇒ 撤下改接源。
⚠️ 边界一（措辞，同迁移 239 邮储那条）：中行**不是没有在线网申系统**，是系统架在第三方平台上（属红线，我们不链过去）。给用户的文案别写成「这家没有网申系统」。
⚠️ 边界二：我另外拿 campus. / job. / hr. / zhaopin. / career.bankofchina.com 试过连接，全部连不上 —— **这条不算证据**，猜子域名 + 连不上正是 CLAUDE.md 明令不能当否定结论用的东西。上面的判定只建立在网站地图与公告原文上。
⚠️ 边界三：entry_url 指的是**栏目页**不是那条 2027 公告，所以 2026-10-09 截止后这行不会失效，只是栏目顶部会换成别的公告。$md$,
       updated_at = now()
 where entry_url = 'https://www.bankofchina.com/aboutboc/bi4/';

-- ── 5. 南方电网：下架 ── 这行是**假的**，它有逐岗详情页，我们库里也早就有它的岗 ──
--
-- 三条互相独立的证据，都指向「没有一岗一页」这句话不成立：
--   ① 前端路由表里有 /post-list-detail，meta.title 就写着「岗位详情」，而且是校招 / 社招两套
--      （postDetail / societyPostDetail）；同级还有 /job-list（meta.title「招聘岗位」）。
--   ② 这两条路由都在路由守卫的**匿名白名单** Ot 里（守卫逻辑：
--      -1 !== Ot.indexOf(t.path) || "/index" === t.path ? 放行 : 跳 /auth/login），
--      匿名直开 #/post-list-detail?postId=... 确实渲染出完整的岗位详情骨架。
--   ③ 匿名 POST /recruitment-dmz/service/webPost/social/querySpecial 返回 count:18 个具名在招岗。
-- 加上第一道门本来就没过：香港 jobs 库里「鼎和财产保险股份有限公司（南方电网）」有 105 个 active。
--
-- 为什么是「下架」而不是「改文案」（同迁移 238 处理中通的口径）：announcement 这一档
-- 渲染给用户的组说明是「对方按公告发布招聘、没有逐个岗位的详情页」，这句话对南方电网就是假的，
-- 而它是**按组渲染的**，改单行 description 改不掉。**用假陈述骗点击比不展示更伤信任**（迁移 226 的红线）。
-- 停用不删：保留可回滚与判断依据，同迁移 235 / 238。
update apply_programs
   set enabled = false,
       notes = $md$2026-09-07 下架：本行「没有逐个岗位的详情页」已被证伪，三条独立证据。
① 路由表：/post-list-detail 的 meta.title 就是「岗位详情」，且注册了校招 / 社招两套组件（postDetail / societyPostDetail）；同级还有 /job-list（meta.title「招聘岗位」）。
② 匿名可达：路由守卫的白名单 Ot 含这两条路由（逻辑 -1 !== Ot.indexOf(t.path) || "/index" === t.path ? 放行 : 跳 /auth/login）。未登录直开 #/post-list-detail?postId=... 渲染出完整骨架：岗位类型 / 学历要求 / 专业要求 / 笔试类别 / 岗位所在地 / 投递截止日期 / 招聘公告 / 职位描述 / 立即申请。
③ 匿名接口有真岗：POST /recruitment-dmz/service/webPost/social/querySpecial 返回 count:18，每条带 id / postName / orgName / postLocationName / 学历 / 招聘人数 / 投递截止（1793091600000 = 2026-10-27）/ announcementId。#/recruitment-social 页当场渲染着其中 12 个，例：「算法开发工程师岗（现货出清算法方向）· 智慧调度事业部 · 硕士研究生 · 广东省广州市 · 南方电网人工智能科技有限公司」。
④ 库里本来就有它的岗：香港 jobs 库「鼎和财产保险股份有限公司（南方电网）」105 个 active（源 adapter=iguopin，last_seen_at 2026-09-07）。鼎和确实是南网子公司 —— 南网自己社招页上就挂着「南方电网产融控股集团有限公司**鼎和财产保险股份有限公司**2026年8月社会招聘公告」。也就是说用户搜「南方电网」本来就搜得到岗，这一页却告诉他「这家没有岗位可看」。
⛏ 留给接源的人（以下是**我没跑通**的部分，别当成已解决）：
· 拿到 id 之后**没能拼出一个能渲染出内容的冷 URL**：#/post-list-detail?postId=<社招 id> 直开加载的是**校招**那套详情组件（页面自报「招聘渠道：校园招聘」），字段全是空。社招 / 校招是两套路由注册，走哪套取决于 SPA 内部状态（currRecruitType），我没找到从冷 URL 复原它的办法。
· 列表接口要先取 /hrcommonauthentication/service/authLoginParam/guest/getGuestToken 拿访客 token；裸 POST 返 401「您的登录状态已失效」。**401 不是墙**，是没带访客 token。
· #/job-list 当前显示「暂无数据 共 0 条」，那是**校招侧**；社招岗在 #/recruitment-social 上。别拿 job-list 为 0 反推「没有岗」—— 本次核验差点就这么错了一次。
· zhaopin.csg.cn 本机 curl 直接 TLS 握手失败（SSL_ERROR_SYSCALL），要走 crawler/cn_portal_tls.py 那套（强制 IPv4 + OP_LEGACY_SERVER_CONNECT）或浏览器。$md$,
       updated_at = now()
 where entry_url = 'https://zhaopin.csg.cn/';

-- ── 6. 国家开发银行：两个招聘栏目内容相同，唯一那条公告连详情页都没有 ──
update apply_programs
   set notes = $md$判定（2026-09-07 真浏览器；curl 直接吃 Akamai 412，同国家电网那条，只能在浏览器里看）：官网网站地图上和招聘沾边的只有两个栏目 —— 新闻中心 > 信息公告 > **招聘公告** /xwzx/xxgg/zpgg/，和 人力资源 > **工作机会** /rlzy/gzjh/。**两栏内容完全一样、且都只有一条**：「国家开发银行2026年校园招聘 [2025-09-12]」。
关键证据：那一条**连自己的详情页都没有** —— 列表项的 href 直接就是 http://cdb2026.zhaopin.com/（智联白标站，属第三方平台红线）。cdb.com.cn 上没有任何岗位页。
⏳ 复查：① 这两栏出现 cdb.com.cn 自有域名下的公告详情页或岗位列表 ⇒ 撤下改接源；② 招聘公告栏出现 2027 届那条（上一届是 2025-09-12 发的，今年同期就该出现）⇒ 只需确认入口仍有内容，不用改这行。
⚠️ 边界一：入口页当前**只有一条一年前的公告**（2025-09-12，2026 届），用户点进来看到的就是这一条。若到 2026-10 底还没有新公告，应重新评估这行还该不该展示。
⚠️ 边界二：另一个等价入口 /rlzy/gzjh/（人力资源 > 工作机会）内容相同；本行沿用 /xwzx/xxgg/zpgg/，换不换都行。
⚠️ 边界三：只核了公开站点，没有登录区可查；官网也没有提及任何别的招聘子域。$md$,
       updated_at = now()
 where entry_url = 'https://www.cdb.com.cn/xwzx/xxgg/zpgg/';

-- ── 收尾断言：把迁移 238 的准入要求变成硬门禁 ──
-- 跑到这里，所有 enabled 的行都必须有 notes。为空说明上面某条 update 的 entry_url 写错了
-- （改过 entry_url、或有人新插了一行没填 notes）——宁可整份回滚，也不要静默留下一行
-- 「没人知道它是怎么判出来的」的对外展示行。
do $$
declare
  missing text;
begin
  select string_agg(company || ' <' || entry_url || '>', ', ')
    into missing
    from apply_programs
   where enabled and notes is null;

  if missing is not null then
    raise exception '迁移 240 断言失败：还有 enabled 的 apply_programs 行没有 notes → %', missing;
  end if;
end $$;
