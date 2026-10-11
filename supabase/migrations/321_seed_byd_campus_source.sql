-- 321 — 比亚迪校招门户：job.byd.com「校园招聘」（应届生 + 实习生），adapter = byd_campus
--
-- 为什么：比亚迪在库里只有社招那一条源（#/social/socialMainPageSocial）和国聘一条，必投缺口台账
-- campus_channel = missing、campus_jobs_recent = 0。官网校招首页自己写着「比亚迪2027届全球校园招聘正式启动！」
-- （2026-08-19）、应届生入口「毕业时间 境内：2026.09.01-2027.08.31」，列表页自报「在招职位 (384)」。
--
-- ── 接的是哪套接口（都是从官网前端代码和页面自己发的请求里读出来的，见 crawler/adapters/byd.py）──
--   postEntryConfig/list（投递入口）→ schoolPortal/queryPositionList → schoolPortal/queryPosition。
--   🚫 不是社招的 position/queryList 换 zpType=00252：那个接口换码后自报 15,582 条，但官网没有任何页面
--      这样调它（app.js + 65 个懒加载分块全扫过）；其中 11,972 条 planYear=2024、全部建于 2024-06，
--      另 3,606 条是 2027 届的内部需求条目。校招页上学生能看到、能投的是 384 个岗。
--
-- ── 接入前 live 验过的事实（2026-10-11，BydCampusAdapter 端到端 should_skip → fetch → parse →
--    validate_job_quality → normalize → 分类，不写库）──
--   · robots.txt 404（无限制）；should_skip = None。
--   · 应届生 384（= 页面「在招职位 (384)」「共 384 条」）+ 实习生 2，共 386；fetch_complete = True。
--     「博士生」65、「外派专项」26 两个入口逐 id 对过，全部在应届生的 384 个里，不另抓。
--   · 质量门 386/386；jd_url 386 个互不相同；地点全部在华。
--   · 详情页 386 个逐个真渲染：标题与接口一致 386/386；应届生岗页面挂「应届生」「2027届」两个标签。
--     其中 6 个链接的密文带 `//`，按旧写法（取 route.href）会被压掉一个斜杠、打开是空白页，已改取
--     route.fullPath 并用官网自己的解码器回验（社招源同病，同一处修了）。
--   · 分类（真实 normalize + JS 分类器）：校招 384 / 实习 2 / 社招 0；届别 2027 = 384。
--     正文里写明「N 年以上经验」的只有 1 组（高级仿真工程师的「世界模型仿真」方向），该岗仍判校招。
--   · 正文 ≥60 字 386/386（重档带详情时；快档 CRAWL_DETAIL_CAP=0 只写标题 / 地点 / 类型）。
--   ⚠️ 试抓在本机跑：Playwright 驱动系统已装的 Chrome。CI 上是自带 chromium + 境外出口，
--      上线后以线上 crawl_runs 为准（同主机的社招源在 CI 上每晚成功）。
--
-- ── 归属 ──
--   同一个官网（job.byd.com，页脚「比亚迪集团」）、同一个站的另一个栏目；源名沿用社招那条的「比亚迪 BYD」
--   （不加「校招」后缀：source_url 含 /school，board 派生列自动归 campus）。岗位行的公司名由 adapter 写「比亚迪」。
--
-- ⚠️ 已知不足：
--   · 一行 = 官网一个岗（一个详情页）。一个岗下面最多 72 组「岗位方向 × 部门意向」各有各的职责 / 要求，
--     库里只留前 400 字（方向、部门、地点、学历排在最前）。
--   · 多地岗的地点取官网列出的第一个城市（114 个岗是多地），全部城市在正文里。
--   · 下架：列表缺席的岗目前只打印 dry-run 数字（这条源只在带浏览器的重档跑，那里没开落库；
--     run.ABSENCE_OBSERVE_DEFAULT 里也有 byd_campus）。入口全关（校招季结束）时存量行不会自动下架。
--   · 发布日不填：页面上唯一的日期叫「更新于」。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值会让整批迁移回滚。
--    crawl_method 只认 http / playwright / manual；industry_group / ownership 沿用社招那条的取值。
-- 回滚：update sources set enabled = false
--        where source_url = 'https://job.byd.com/portal/pc/#/school/schoolPositionList';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '比亚迪 BYD', 'https://job.byd.com/portal/pc/#/school/schoolPositionList', 'official',
       'byd_campus', 'playwright', true, '{CN}', 'private', '新能源汽车/制造', '汽车/出行', 'private',
       '2026-10-11 接入：官网校招页（应届生 + 实习生入口），接口 postEntryConfig/list → schoolPortal/queryPositionList / queryPosition。live 386 岗（应届生 384 = 页面自报 384，实习生 2），详情页 386/386 真渲染。⚠️ 别改成社招接口换 zpType=00252：那是 15,582 条内部需求（11,972 条是 2024 届的）。'
where not exists (
  select 1 from public.sources
  where source_url = 'https://job.byd.com/portal/pc/#/school/schoolPositionList'
);
