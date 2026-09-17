-- 270 — 接入顺丰 / 美的两家的**校园招聘**门户（两家的社招源早就有，校招一直是零源）
--
-- 两条源都是「同一家公司的校招在另一个 host、另一套后端」，不是现有源换个路径：
--   顺丰：社招 hr.sf-express.com（SearchJob.do）  ↔  校招 crs-pub.sf-express.com（web/position/query）
--   美的：社招 recruit.midea.com（form-encoded）  ↔  校招 careers.midea.com（JSON，先取招聘项目再取岗位）
-- 岗位 id 空间互不相干，jd_url 模板也不同 → 必须各自一行源、各自一个 adapter。
-- 接口细节与踩坑见 crawler/adapters/{sf_express_campus,midea_campus}.py 的 docstring
-- 与 docs/crawler-adapter-notes.md。
--
-- ── 接入前 live 验过的事实（2026-09-18，纯 httpx 零鉴权零浏览器）──
-- ① should_skip(source_url) 两家都实测跑过 → None（不跳过）；裸 HEAD 也都是 200。
--    robots：crs-pub.sf-express.com/robots.txt 返 404，careers.midea.com/robots.txt 返 200 但
--    是 SPA 的 HTML 兜底页（不是真 robots，同联想那条）→ crawler/robots.check_robots 对两家的
--    列表页与接口路径实测均 allowed=True，无合规红线（对比快手校招 campus.kuaishou.cn 的 Disallow: /）。
-- ①b 详情页**不随撤岗消失**（Playwright 真渲染实测，见 adapters docstring）：已撤岗照样渲染完整
--    正文 +「申请职位 / 立即投递」按钮 → 判死只能读接口字段，dead-link-audit 的 DEAD_MARKERS
--    对这两个源一条都匹配不上，必须靠 liveness-sweep。
-- ② 端到端跑了 fetch → parse → normalize（不是只探接口），数字见下面各自的 notes。
-- ③ 逐岗详情按 CRAWL_DETAIL_CAP=3 真实打开过，全部 HTTP 200 且探活判定 alive。
-- ④ 判死信号真伪 id live 对拍，双条件；已进 ENRICH_REGISTRY + liveness-sweep matrix
--    （契约断言 crawler/test_state_bank_liveness.py：注册表 ⊆ matrix）。
--
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187/269），显式赋值整批迁移会回滚。
-- ⚠️ crawl_method 只认 http / playwright / manual —— 这两条都是纯 httpx，填 http。
-- ⚠️ industry_group / ownership 的取值受 CHECK 约束（迁移 265），这里沿用两家社招源的同款取值。

insert into sources (company, source_url, source_type, adapter_name, crawl_method,
                     enabled, segment, industry, industry_group, ownership, regions, notes)
values
  (
    '顺丰',
    'https://crs-pub.sf-express.com/#/positionList',
    'official',
    'sf_express_campus',
    'http',
    true,
    'private',
    '物流/供应链',
    '物流/供应链',
    'private',
    '{CN}',
    $md$2026-09-18 接入：顺丰校招门户 crs-pub.sf-express.com，GET /api/web/position/query
（PageHelper 风格，pageNum + pageSize 均实测真实生效：page1∩page2=0 条、三页并集=total）。
live 自报总数 total=120；端到端 parse 出 120 个岗，jd_url 120/120、正文≥60 字 120/120、
jd_url 唯一 120/120 且全在官方 host，fetch_complete=True。
job_type 分布：校园招聘 120（seasonType=2 秋季校招；岗位级 internTypeName 当前全空）。
届别：grad_class 120/120 抽到 2027（硬信号「2027届本科及以上学历毕业生」在 jobRequirement 首句，
故 summary 刻意把【任职要求】排在【岗位职责】前面——职责在前只有 118/120 能抽到）。
归属：单租户官方门户，company 固定「顺丰」（必投清单 pattern %顺丰%），
列表里的 orgSourceName（顺丰本部/航空/科技/分公司）只进 summary、不写 company。
核验样本：逐岗详情按 CRAWL_DETAIL_CAP=3 真开 3 条（id 2260/2247/2246）全 HTTP 200 + 判定 alive；
判死信号另做过**全集**对拍——列表内 120/120 个 id 详情 status=1 零反例，
列表外 84 个 id 全是 status=2(73)/status=0(9)/HTTP500「找不到职位信息」(2)，无一 status=1。
诚实边界：实习通道（staffGroup=C）与 positionType=consulting / specialCategory=1 当日实测均 total=0，
「现在返 0」不等于「顺丰没有实习」——真要下这个结论得看它的实习生招聘页自己怎么说。$md$
  ),
  (
    '美的集团',
    'https://careers.midea.com/schoolOut/post',
    'official',
    'midea_campus',
    'http',
    true,
    'private',
    '家电',
    '制造/工业',
    'private',
    '{CN}',
    $md$2026-09-18 接入：美的校招门户 careers.midea.com（自建 iHR），
GET /backend/school/position/common/project/list?status=1 取在跑招聘项目
→ POST …/position/list 逐项目翻页。**项目是动态的，不许硬编码 projectRuleId**。
live 自报总数 535（日常实习生招聘通道 152 / 校企合作实习招聘通道 169 /
2027届美的星校园招聘 148 / 2027应届博士校园招聘 66，四个项目 positionId 互不重叠）；
端到端 parse 出 535 个岗，jd_url 535/535、正文≥60 字 535/535（列表行自带全文，零薄卡）、
jd_url 唯一 535/535 且全在官方 host，fetch_complete=True（**逐项目判抓全**，不拿各项目 total 之和当分母）。
job_type 分布：校园招聘 214 / 实习 169 / 日常实习 152。
届别：grad_class 2027 共 214（来自项目名「2027届…」「2027应届…」），
两个实习通道刻意留白 321 —— 它们的 numberOfSessions=2026 但毕业时间窗是 2026-01-01~2028-12-31，
写进去就是把 26/27/28 届通吃的实习岗全标成 2026 届。
🚩 翻页参数是 pageIndex，**pageNum 会被静默忽略**（HTTP 200、total 正确、每页回同一批 20 条：
按 pageNum 翻 8 页拿回 160 行、去重后只有 20 个 id）；pageSize 被服务端硬顶 20。
故末页判据用「这一页有没有带来新 positionId」，不用「本页条数 < pageSize」。
归属：单租户官方门户，company 固定「美的集团」（必投清单 pattern %美的%）；
orgUnitList 里的事业部名只进 summary、不写 company。
核验样本：逐岗详情按 CRAWL_DETAIL_CAP=3 真开 3 条全 HTTP 200 + 判定 alive；
判死信号对拍——在招 535/535 全集返 code=0 + publishStatus=1 零反例，变异 id 120 个里 89 个返 data=null。
诚实边界：「已下架仍返记录但 publishStatus=2」这条反向证据只有 1 例（美的没有公开的历史岗位列表），
故真实撤岗若走别的形态，这里会**漏判**（安全方向），待库里的岗自然过期后用 job_closures 复核。$md$
  )
on conflict (source_url) do nothing;
