-- 315 — 新城控股（Seazen）改接 Moka 门户：社招 + 校招两条源
--
-- 为什么：原三条 hotjob 源（seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce 的 social / school / interns）用不了了——
-- 对方关闭了这个套件，suite/config 回「该官网已关闭，无法继续访问!」，三条源每轮都被门拦下记 skipped
-- （停用它们的是迁移 314）。官网 www.seazen.com.cn/join/ 的「我要应聘」现在直链 Moka：
-- app.mokahr.com/social-recruitment/seazen/168435。接入前 sources 里没有任何 seazen 的 Moka 源
-- （438 条 moka 源全量扫过），香港库 app.mokahr.com/%/seazen/% 下 0 行。
--
-- ── 接入前 live 验过的事实（2026-10-11；MokaAdapter 端到端 robots → should_skip → fetch → parse →
--    validate_job_quality → normalize，不写库；两条源的详情页逐岗全部真渲染，不是抽样）──
--   社招 …/social-recruitment/seazen/168435
--     · 49 岗 = 页面自报「49 结果」；分页器 2 页翻到 2 页，fetch_complete=True；robots 放行、should_skip=None。
--     · 质量门 49/49，淘汰 0；jd_url 49 个互不相同。
--     · 详情页 49/49 渲染出本岗标题 +「申请职位」按钮，撤岗文案 0 处；49 个页面内容互不相同。
--     · 正文 ≥60 字 47/49。另 2 个是对方自己写得短：「会计主管」正文只有「暂无」，「帮厨」正文 40 字。
--   校招 …/campus-recruitment/seazen/168436
--     · 11 岗 = 页面自报「11 结果」；单页，fetch_complete=True；robots 放行、should_skip=None。
--     · 质量门 11/11，淘汰 0；jd_url 11 个互不相同；详情页 11/11 标题 +「申请职位」；正文 ≥60 字 11/11。
--   社招与校招两批岗位 id 没有重叠。
--   ⚠️ 试抓是在本机跑的：Playwright 驱动系统已装的 Chrome（本机没有 Playwright 自带的 chromium）。
--      CI 上是自带 chromium + 境外出口，上线后以线上 crawl_runs 为准。
--
-- ── 归属（CLAUDE.md 红线：只认官网 / 门户页自报，不认 slug）──
--   官网标题「新城控股集团股份有限公司【官网】」，它的「我要应聘」直链本社招门户；门户页眉 logo「seazen 新城控股」，
--   页面标题「新城集团 - 社会招聘」/「新城集团 - 校园招聘」，页脚「© 新城集团」。
--   所属部门逐岗看过：校招 11 岗全是「新城控股」；社招 49 岗是内部部门 / 各地商管公司 / 区域
--   （生态运营部、用户体验部、工程物业部、XX商管公司、华北区域、山东区域、项目储备、其它…），没有别家公司。
--   源名沿用原三条 hotjob 源社招那条的「新城控股 Seazen」（校招不再加「校招」后缀，同迁移 296 华东医药的写法；
--   社招 / 校招由 source_url 自动归类）。
--
-- ── 校招只接一个门户 ──
--   校招有两个门户 id：168436 与 166704，adapter 各抓一遍，11 个岗位 id 完全相同（两个都接 = 同一个岗两行）。
--   接 168436：平台别名 /campus-recruitment/seazen 与 /campus_apply/seazen 都 302 到它（= 当前生效的那一期，
--   MokaAdapter 判「校招门户换期」也以这个别名为准）；166704 只在第三方转载页里见过。官网没有链校招站。
--
-- ⚠️ 已知不足（Moka 卡片地点解析的老问题，全库 Moka 源同病，本迁移不解决）：
--   社招 49 岗：36 个地点正确；5 个把「所属部门」当成了地点（「华北区域」×4 页面写的是天津市、「山东区域」×1 是青岛市）；
--   3 个页面写了地点但没取到（两地并列 2 个、只写「中国」1 个）；5 个页面本身没写地点。
--   校招 11 岗：卡片和详情页都没有工作地点。
-- ⚠️ 实习没接：这两个门户里 60 个岗的职位性质全是「全职」。只看了这两个门户，平台没有按租户列门户的公开入口，
--    所以「没看到实习门户」不等于「对方没有」。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
-- 回滚：update sources set enabled=false
--        where source_url in ('https://app.mokahr.com/social-recruitment/seazen/168435',
--                             'https://app.mokahr.com/campus-recruitment/seazen/168436');

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select v.company, v.url, 'official', 'moka', 'playwright', true, '{CN}', 'private', '房地产',
       '地产/建筑', 'private', v.notes
from (values
  ('新城控股 Seazen', 'https://app.mokahr.com/social-recruitment/seazen/168435',
   '2026-10-11 接入：官网 seazen.com.cn/join/「我要应聘」直链本门户，门户自报「新城集团 - 社会招聘」、logo 新城控股。live 49 岗 = 页面自报 49。原 hotjob 套件已被对方关闭（迁移 314 停用）。'),
  ('新城控股 Seazen', 'https://app.mokahr.com/campus-recruitment/seazen/168436',
   '2026-10-11 接入：Moka 门户自报「新城集团 - 校园招聘」，所属部门全是新城控股。live 11 岗 = 页面自报 11。⚠️ 另一个门户 id 166704 是同一批 11 个岗，别再接。')
) as v(company, url, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);
