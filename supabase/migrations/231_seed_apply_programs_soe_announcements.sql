-- 230 — 央企/国企「公告制」投递入口（apply_programs 第三批）
--
-- 背景：央国企是校招阶段很重要的一类投递类型，而其中一部分**客观上不存在「一岗一页」**——
-- 对方按「公告」批量招聘（一个单位一个批次一条公告），官网没有逐个岗位的详情页，
-- 过不了本项目的 jd_url 红线，于是此前在产品里完全不存在。
--
-- ⚠️ 本批每一家都过了三道排除门（2026-09-05 全部 live 核验，非推断）：
--   ① 国聘（iguopin）上有没有它？——对国资委 95 家央企逐家跑 recom-job 关键词检索 +
--      crawler/company_name_match 严格核名：**70 家在国聘上有逐岗页**（形如
--      https://www.iguopin.com/job/detail?id=...），那 70 家一律不进这里、该去补正常源。
--   ② 它自己的官网招聘页有没有逐岗详情页？——逐个用真实浏览器渲染确认。
--      被这一门挡掉的实例：中国商飞 zhaopin.comac.cc 有 329 个校招岗列表；
--      中国融通 job.crtc-hr.com 有职位检索页（当前无在招）；
--      国家能源集团 zhaopin.chnenergy.com.cn 有「热招岗位」逐岗卡片。
--   ③ must_apply_gap_attempts 台账状态——已 healthy 的不重复处理。
--
-- ⚠️ 一条刻意的口径说明（南方电网 / 国家电网 这类会被质疑的）：
--   台账的 healthy 是**公司级**口径（库里有没有健康在招岗），而这张表承载的是**通道级**事实
--   （这条投递通道有没有一岗一页）。南方电网库里那 102 个岗全部是国聘集团展开来的
--   子公司**社招**岗，校招供给为 0，而它的校招通道（zhaopin.csg.cn）确证是公告制：
--   208 条「XX单位2026年校园招聘公告」，「招聘岗位」区块里只有**业务类别**且显示「暂无数据」，
--   招聘流程写的是「投递志愿」不是投岗位。所以两者不冲突，这里是**加法不是替代**。
--
-- ⚠️ 收录标准（四条全满足才写，宁可少收）：
--   1. 入口页 live 打开且页面自证是该公司；2. 渲染后确认只有公告条目、没有逐岗详情页；
--   3. 入口是活的（近一个招聘年度内有更新）；4. 库里没有同一通道来的岗位。
--   被 3 挡掉的：中国盐业（最新公告 2025-09-02，一年零更新）、矿冶科技（最新 2023-09-21）。
--   被「第三方平台红线」挡掉的：华侨城——校招通道跳智联企业专区 oct.zhaopin.com，非官方域名。
--   无法核实因而不收的：国家管网 zhaopin.pipechina.com.cn（本机 TLS 握手被重置）、
--   中国邮政（集团站没有招聘专栏，hr.chinapost.com.cn 502）、中国国际技术智力合作（列表无日期，
--   证不出入口是活的）。
--
-- 国家电网已由迁移 229 收录（entry_url = .../sgcchr/static/home.html），本批不再重复。

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '南方电网', '校园招聘公告', 'announcement', 'https://zhaopin.csg.cn/',
       '南方电网按「公告」招人：每条公告对应一个单位（各省电网公司 / 超高压 / 数字电网等）的一批招聘，'
       '报名时投的是「志愿」——选业务类别加单位，再统一笔试面试，官网没有逐个岗位的详情页。',
       null, '能源/化工', now()
where not exists (select 1 from apply_programs where entry_url = 'https://zhaopin.csg.cn/');

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '中国华能', '高校毕业生招聘公告', 'announcement', 'https://zhaopin.chng.com.cn/',
       '华能的招聘官网按单位分批发公告，一条公告写明招聘日期区间和用人单位（集团总部 / 能源研究院 / '
       '数智中心等），没有逐个岗位的详情页；集团官网的「招聘信息」栏同样是公告列表。',
       null, '能源/化工', now()
where not exists (select 1 from apply_programs where entry_url = 'https://zhaopin.chng.com.cn/');

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '中国林业集团', '校园招聘公告', 'announcement', 'https://www.cfgc.cn/cfgc/rlzy/rczp/xyzp/A149007004001Gone1.html',
       '中林集团的校园招聘全部走公告：官网「校园招聘」栏挂着历年「XX年（春季 / 夏季）校园招聘公告」，'
       '每条公告是一个批次，笔试面试与拟录用名单也在同一栏公示，没有逐个岗位的详情页。',
       null, '农林/生态', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.cfgc.cn/cfgc/rlzy/rczp/xyzp/A149007004001Gone1.html');

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '中国稀土集团', '招聘动态（含校园招聘）', 'announcement', 'https://www.regcc.cn/zgxtjt/zpdt/list.shtml',
       '中国稀土集团把招聘信息统一发在官网「招聘动态」栏：集团及所属企业的招聘公告、管理岗位公开竞聘公告、'
       '校园招聘启动通知都在这里，一条公告对应一批岗位，没有逐个岗位的详情页。',
       null, '能源/化工', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.regcc.cn/zgxtjt/zpdt/list.shtml');

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '国家开发银行', '校园招聘公告', 'announcement', 'https://www.cdb.com.cn/xwzx/xxgg/zpgg/',
       '国开行一年发一条校园招聘公告（挂在官网「新闻中心 > 信息公告 > 招聘公告」栏），'
       '公告里写清总行 / 各分行的招聘方向和报名方式，官网没有逐个岗位的详情页。',
       null, '金融', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.cdb.com.cn/xwzx/xxgg/zpgg/');
