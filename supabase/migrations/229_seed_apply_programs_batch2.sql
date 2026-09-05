-- 229 — 项目制投递入口第二批（apply_programs）
--
-- 背景见迁移 226：这张表收的是「有官方投递入口、但客观上没有逐个岗位详情页」的公司。
-- 226 只种了 2 条（中通蓝天计划 / 中国银行招聘公告），其余候选当天本机 ConnectError，没核实就没入库。
-- 本次（2026-09-05）把候选逐个渲染核实了一遍，结论分两半，两半都重要：
--
-- ⚠️ 【结论一】「国有大行 = 公告制」这个前提基本是错的，六家里五家有稳定的逐岗详情页。
--    逐个 live 核实（点进列表 → 打开详情 → 换新标签页冷加载复验）：
--      · 工商银行 https://job.icbc.com.cn/pc/index.html#/main/social/postDetail/{postId}
--      · 建设银行 https://job3.ccb.com/cn/job/job_detail.html?planId=…&planPost=…&planType=SH
--      · 农业银行 https://career.abchina.com/build/index.html#/PositionDetails/:{jobPublishId}
--      · 交通银行 https://job.bankcomm.com/#/social/recruitmentInfo/?positionId={id}
--      · 浦发银行 https://job.spdb.com.cn/jobDetail?jobId={id}&type=1   ← 纯 httpx 零鉴权即可拿到正文
--      · 中国移动 https://job.10086.cn/personal/job/detail.html?id={uuid}（必投清单里零源，正文完整）
--    这些**不属于本表**，它们该走 must_apply_gap_attempts 那条线接成正常源。
--    ⚠️ 农行/交行/工行的详情是 window.open 打开的，页面上点一下「像没反应」——
--       别据此判「没有详情页」，要去读它的 onClick 源码（本轮就是这么发现的）。
--
-- 【结论二】真正符合本表语义的是下面 4 家，逐条核实记录写在各自的 insert 上面。
--    宁波银行**刻意不收**：它有 351 个逐岗记录、点开有完整 JD，只是 Vue 就地渲染没有 URL。
--    那是「我们抓不到」，不是「对方没有一岗一页」——给它挂「公告制」徽章就是对用户说假话。
--    中国石化 / 中国邮政也不收：前者校招报名已结束、社招「暂无数据」，整个门户是空的；
--    后者没有招聘专属入口（招聘公告混在邮票图稿征集、采购招标的「信息公告」里）。
--
-- 红线不变（同 226）：verified_at 为空即不对外展示；这些条目不是岗位，不进 jobs、不渲染成岗位卡片。

-- ── 1. 国家电网（announcement） ──────────────────────────────────────────────
-- 2026-09-05 渲染 https://zhaopin.sgcc.com.cn/ （302 到 /sgcchr/static/home.html）看到：
--   整页只有公告 —— 「公司公告」区是《国家电网有限公司2026年招聘高校毕业生公告》，
--   「招聘公告」区是 26 条以上省公司公告（国网北京/天津/河北/冀北/山西…《2026年高校毕业生招聘公告（第三批）》）。
--   顶部导航只有 首页 / 单位一览 / 应聘指南 / 帮助中心；点进「单位一览」只有总部、分部、
--   27 家省公司、直属单位的**名字列表**，没有任何岗位。岗位与投递在「我的求职」里，需登录。
--   → 公开面确实没有逐个岗位的详情页。按批次发公告，下一批（2027 届）按往年节奏在 10 月出。
insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '国家电网', '高校毕业生招聘公告', 'announcement',
       'https://zhaopin.sgcc.com.cn/sgcchr/static/home.html',
       '国家电网按「批次 + 省公司」发公告招人：总部先发一份总公告，再由各省电力公司分批发自己的公告（例如「2026年高校毕业生招聘公告（第三批）」）。'
       '要投得在这个平台注册账号，再按公告报名——官网公开页面只有公告，没有一个个岗位的详情页。',
       null, '能源/化工', now()
where not exists (select 1 from apply_programs where entry_url = 'https://zhaopin.sgcc.com.cn/sgcchr/static/home.html');

-- ── 2. 国家能源集团（announcement） ─────────────────────────────────────────
-- 2026-09-05 渲染 https://zhaopin.chnenergy.com.cn/index1 看到：
--   「热门公告」三条均为 2026-09-02 发布的 2027 年度公告（直招公告 / 统招公告 / 总部「菁英」管培生招聘公告），
--   公告本身有稳定链接 /annc/showgg?id={uuid}。
--   「热招岗位」确实按岗位列出（岗位名 / 学历 / 专业 / 部门 / 地点 / 招聘人数 / 报名截止日期），
--   但每张卡片上唯一的动作是「申请」，其 onclick=hoomIndexApply(...) 的函数体第一句就是
--   myalert("您还未登录或登录已超时，请重新登录！") 后 return —— 没有任何逐岗 URL。
--   岗位列表页 /recTypeSerch?kinds=1&schType=1 同样把信息平铺在列表里，点不进单个岗位。
insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '国家能源集团', '2027年度高校毕业生招聘（直招 / 统招 / 「菁英」管培生）', 'announcement',
       'https://zhaopin.chnenergy.com.cn/index1',
       '国家能源集团把校招拆成几个专项来发公告：直招、统招、总部「菁英」管培生，另有藏青疆专招和乡村振兴专招。'
       '岗位是按公告成批挂出来的，官网只在列表里平铺岗位名和条件，点不进单个岗位；要投得先注册账号，再在对应公告下报名。',
       '报名截止日期：2026年10月07日（总部“菁英”管培生专招）', '能源/化工', now()
where not exists (select 1 from apply_programs where entry_url = 'https://zhaopin.chnenergy.com.cn/index1');

-- ── 3. 波司登（talent_pool） ────────────────────────────────────────────────
-- 2026-09-05 渲染 https://www.bosideng.com/job 看到：
--   页面标题「JOB OPPORTUNITIES 工作机会」，筛选器（招聘类型 社招/校招、职业类别、城市）都在，
--   但结果区是「暂无数据」；页面给的投递方式只有两条：
--   「投递通道一 直接投递简历至邮箱（注明投递岗位）」、「投递通道二 扫描以下任意二维码，投递对应岗位」。
--   → 官网没有在招岗位列表，更没有逐岗详情页，投递靠邮箱/二维码。
insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '波司登', '工作机会（邮箱 / 二维码投递）', 'talent_pool',
       'https://www.bosideng.com/job',
       '波司登官网的「工作机会」页有筛选器，但岗位列表长期是空的，实际投递走页面上给的邮箱和二维码——'
       '投的时候要自己注明想去的岗位。所以这里没有岗位可点，只能把简历投过去等对方匹配。',
       null, '消费/零售', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.bosideng.com/job');

-- ── 4. 韵达速递（talent_pool） ──────────────────────────────────────────────
-- 2026-09-05 抓取 https://www.yundaex.com/cn/hr_online.php 看到：
--   面包屑是「首页 > 人才计划 > 在线招聘」，但正文只有公司简介 + 总部联系方式 + 简历投递邮箱，
--   全页没有任何岗位列表、没有在线投递系统；页面结尾写着
--   「注：全国各分拨中心长期招聘一线操作员工，具体请联系总部。」
--   同站的 /cn/hr_jihua.php（人才计划）只是介绍校企合作、订单班、管培生的图文，同样没有岗位。
--   （校园招聘页 /cn/hr_xiaoyuan.php 当前 302 回首页。）
insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '韵达速递', '在线招聘（简历投递邮箱）', 'talent_pool',
       'https://www.yundaex.com/cn/hr_online.php',
       '韵达官网没有在线职位系统：「在线招聘」页只有公司介绍和一个简历投递邮箱，页面自己写明各地分拨中心长期招人、'
       '具体要联系总部。所以搜不到韵达的岗位不是漏抓，是对方本来就没把岗位挂到网上。',
       null, '物流/供应链', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.yundaex.com/cn/hr_online.php');
