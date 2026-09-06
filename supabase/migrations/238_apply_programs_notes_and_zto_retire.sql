-- 238 — apply_programs 加内部 notes（复查判据）+ 中通行下架（我们已经在供它的岗了）
--
-- ── 背景：/programs 每一行都是「今天为真、明天可能为假」的结论 ──
-- 这张表存的不是数据，是**人工判断**：「这家公司客观上没有一岗一页」。
-- 这类判断会自己变坏，而且查实过（2026-09-05）**没有任何机制会发现它变坏**：
--   gap_census.classify_company 对「有 apply_programs 行、无源无岗」的公司判 manual_review
--   并显式把 next_retry_at 置 None，而复验车道 _REVALIDATE_STATES 刻意不含 manual_review。
--   （已有一半自解锁：manual_review 排在 healthy/active/enabled_sources 三档之后，
--     一旦有人接了源就自动回到正常重试轨道；缺的是「没人先接源时谁去探」这一半。）
-- 结论：既然没有自动复查，就把**怎么复查**写在这一行自己身上——比一条没人看的定时任务可靠。
--
-- ⚠️ notes 是**内部字段，不给用户看**：读侧 lib/apply-programs-store.ts 显式列出要 select 的列，
--    不含 notes，所以加这一列不会渲染到 /programs 页面上（description 才是给用户看的）。
--    复查方法里可能含接口路径，那是运维信息，不该出现在求职者眼前。

alter table apply_programs add column if not exists notes text;

comment on column apply_programs.notes is
  '内部备注：这行是怎么判出来的 + 怎么复查 + 什么信号说明该撤下。不对用户展示。
   准入要求：新增 apply_programs 行必须填它——「对方没有一岗一页」是会自己变坏的结论，
   而 gap_census 把这类公司钉在 manual_review 且 next_retry_at=None，没有任何自动复查。';

-- ── 一、给存量行补上复查判据 ──

-- 波司登是唯一「会变」的那个：官网 JS 里 /api/jobs/getlist 与 /job/detail/{id} 路由都在，
-- 机器齐全，只是眼下一个岗都没发。它一发岗，这行就该撤下改接正常源。
update apply_programs
   set notes = '判定（2026-09-05 live）：GET https://www.bosideng.com/api/jobs/getlist 返回 '
               '{"errcode":0,"data":{"list":[],"total":0}} —— 岗位列表真的是空的，实际投递走页面上的邮箱 + 二维码。'
               || E'\n⏳ 复查（这行会自己变坏，唯一会变的一行）：重跑上面那个 GET。'
               '**total 由 0 变正 ⇒ 立刻把本行 enabled=false，改接正常源**——'
               '它的逐岗详情路由 /job/detail/{id} 已经存在于 JS bundle 里，不是要新造。',
       updated_at = now()
 where entry_url = 'https://www.bosideng.com/job';

-- 国家电网：复查过两轮，第二轮用的是「捞全站页面清单」而不是点击（前一轮的方法不足以下结论）。
update apply_programs
   set notes = '判定（2026-09-05 两轮）：第二轮用「同源 fetch 站点自己的 JS → 抽出全站页面清单」复核'
               '（curl 直接吃 Akamai 412，只能在已打开的页面里抓）。全站 12 个页面里，'
               'jobSearch/jobPost/jobColl/jobConc/jobJust 全在登录区，清单里**没有任何 jobDetail 类页面**；'
               '单位详情页 unitInfo.html 只有公司介绍 + 招聘公告 + 公示，无岗位列表。'
               || E'\n⏳ 复查：重捞一次页面清单，出现 jobDetail/positionDetail 类页面即应重新评估。'
               '注意公开页面与登录区是两回事——本行只断言「公开页面没有逐岗页」。',
       updated_at = now()
 where entry_url = 'https://zhaopin.sgcc.com.cn/sgcchr/static/home.html';

update apply_programs
   set notes = '判定（2026-09-05 live）：hr_online.php 正文只有公司简介 + 简历投递邮箱，'
               '页面自己写「全国各分拨中心长期招聘一线操作员工，具体请联系总部」；'
               'hr_xiaoyuan.php（校园招聘）**302 回首页**。全站没有岗位系统、没有 ATS。'
               || E'\n⏳ 复查：hr_xiaoyuan.php 不再 302，或出现任何 ATS 子域（job./hr./campus. 等）即重新评估。',
       updated_at = now()
 where entry_url = 'https://www.yundaex.com/cn/hr_online.php';

-- ── 二、中通行下架：我们现在**已经在供它的岗**，这行已经变成假话 ──
--
-- 这行说「官网不按岗位一个个挂，而是投递到项目」。2026-09-05 已证伪：
-- /social 与 /campus-position 下有完整逐岗列表，详情页 hr.zto.com/position-detail?id={id}
-- 冷加载可渲染；已接成正常源（迁移 236，adapter zto / zto_campus），
-- 香港库当前有中通 101 个在招岗（社招 77 / 校招 23 / 实习 1）。
--
-- 为什么是「下架」而不是「改文案」：campus_program 这一档渲染给用户的组说明是
-- 「对方按项目收简历，**不按岗位逐个挂出**」——这句话现在对中通就是假的，而它是**按组渲染的**，
-- 改单行 description 改不掉。用户看到中通挂在「项目制投递」下，会得出「中通校招没有岗位可看」，
-- 而事实是他在岗位库里能搜到 23 个中通校招岗。**用假陈述骗点击比不展示更伤信任**（迁移 226 的红线）。
-- 同 migration 235 处理国家能源集团的口径：**停用不删**，保留可回滚 + 保留这段判断依据。
--
-- ⚠️ 蓝天计划本身是真实存在的（hr.zto.com/campus 是项目介绍 + 宣讲会日程），
--    但它现在是「岗位之外的补充信息」，不再是「唯一投递入口」——不该占 /programs 的位置。
update apply_programs
   set enabled = false,
       notes = '2026-09-05 下架：本行「官网不按岗位一个个挂」已被证伪。'
               '/social 与 /campus-position 有完整逐岗列表，详情页 hr.zto.com/position-detail?id={id} '
               '冷加载可渲染；已接成正常源（迁移 236，adapter zto/zto_campus），'
               '当时香港库有中通 101 个在招岗（社招 77 / 校招 23 / 实习 1）。'
               '蓝天计划页面本身仍在（项目介绍 + 宣讲会），但已不是唯一投递入口。'
               || E'\n停用不删：保留可回滚与判断依据，同迁移 235 处理国家能源集团的口径。',
       updated_at = now()
 where entry_url = 'https://hr.zto.com/campus';
