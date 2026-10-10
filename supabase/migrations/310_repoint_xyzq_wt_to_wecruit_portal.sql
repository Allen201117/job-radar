-- 310 — 兴业证券：旧版 wt 入口换成新版门户（hotjob adapter），校招渠道单列一条源
--
-- 现象：这条 wt 源 2026-10-08 14:59（北京）起连续 8 轮 failed，error_message 恒为
--       `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`；此前每轮 success / 94 岗。
-- 根因：不是对方故障、也不是限流——**对方换了门户**。xyzq.hotjob.cn 被改绑成新版 wecruit 门户的壳页：
--       任何路径（列表接口、详情页、不存在的路径）都回同一份 3.5KB HTML，壳页再 POST
--       /wecruit/common/getSLD 拿到 `https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/index.html` 去加载。
--       对方官网 www.xyzq.com.cn 的招聘链接（www.hotjob.cn/wt/xyzq/web/index?brandCode=xyzq）也 302 到同一个门户。
--       库里 94 个在招岗的旧链接现在打开都是门户首页，不是岗位。
-- 归属：租户自报 suite/config.companyName = 兴业证券股份有限公司（门户标题「兴业证券招聘官网」）。
--
-- ── 接入前 live 验过的事实（2026-10-10）──
-- ① should_skip 三个渠道都真跑过：social.html → None、school.html → None、
--    interns.html → 「channel not published (recruitType=12)」。
-- ② HotJobAdapter 真跑 fetch → parse：社招 29/29、校招 42/42，fetch_complete=True，正文 ≥60 字 71/71。
-- ③ 浏览器真渲染：social.html「在招职位29个」、school.html「在招职位42个」；社招 / 校招详情页各开 1 条，
--    渲染出岗位本身 + 「立即投递」。interns.html 停在「内部处理中，请稍后再试」、实习岗详情页一直「正在加载中」。
-- ④ 与库对拍（全集，两个方向）：库里 94 个旧岗位号（wt postId）↔ 新门户三个渠道 94 个 externalKey，
--    两边各 0 个落单，标题 94/94 逐字相同（社招 29 / 校招 41+博士后 1 / 实习 23）。
--
-- ⚠️ 实习渠道（interns.html，23 个岗）**刻意不入库**：新门户没发布这个渠道，页面打不开（同迁移 228 的口径：
--    只收「渠道确实发布、页面确实能打开」的）。对方哪天发布了，再补一条 …/pb/interns.html。
-- ⚠️ 门户导航里「校园招聘」是隐藏的（只露出 社会招聘 / 博士后招聘），但 school.html 直接打开正常、岗位能投。
-- ⚠️ 旧版列表接口换个主机还活着（www.hotjob.cn/wt/xyzq/…，94 岗，详情页是微信版，电脑上点「立即申请」
--    只弹「您还未登录」）。没有走那条路：对方官网已不再链到它。
-- ⚠️ 顺序：先跑 migrate-wt-rows-to-wecruit 工作流把存量 71 行的 jd_url 换成新门户链接，再合本迁移——
--    反过来新 adapter 第一轮抓取会插 71 个新行（同一个岗两张卡）。
-- ⚠️ 不写 board 列（generated）；segment / industry / ownership 沿用原行的值，同一家公司两条源保持一致。

-- 原行改指社招渠道（保留 id：存量岗位的 source_id、crawl_runs 历史都挂在它上面）。
update public.sources
   set adapter_name = 'hotjob',
       source_url   = 'https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/social.html',
       notes        = '2026-10-10 由旧版 wt（xyzq.hotjob.cn/wt/xyzq/web/index）换到新版门户社招渠道：对方 10-08 把域名改绑成新门户，旧接口回壳页。租户自报 companyName=兴业证券股份有限公司。live：29/29，fetch_complete=True；浏览器验证列表页 + 详情页。'
 where source_url = 'https://xyzq.hotjob.cn/wt/xyzq/web/index'
   and adapter_name = 'wt';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '兴业证券', 'https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/school.html', 'official', 'hotjob', 'http',
       true, '{CN}', 'private', '证券', '金融', 'private',
       '2026-10-10 接入：兴业证券校招渠道（同租户 school.html；门户导航里这一项是隐藏的，页面直接打开正常）。live：42/42（含博士后 1），fetch_complete=True；浏览器验证列表页 + 详情页。实习渠道 interns.html 未发布（页面停在「内部处理中」），没有入库。'
where not exists (select 1 from public.sources
                   where source_url = 'https://xyzq.hotjob.cn/SU68fb2499b7da1347a9dd852c/pb/school.html');
