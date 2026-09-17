-- 272 — 接入方太集团（fotile.zhiye.com）社招 / 校招 / 实习三个板块
--
-- 这是北森的**卡片式 CMS 门户**：同一套 *.zhiye.com CMS（同 cmsportal/<租户数字 id> 体系、
-- 同 `?PageIndex=` 翻页、同 `?jobId=` 详情身份、同 `X-RateLimit-*-second: 50` 按 IP 限流），
-- 只是列表卡模板换成了「标题在 <dd>、<a> 体内还塞着整段 JD」。
-- 后果是既有两个解析器**都判它没有岗位、而且都不报错**：theme2 解析器退回「整个 <a> 文本当标题」
-- 被 3~120 字门丢光；浏览器 SSR 锚点抽取的 name.length<=60 门同理 → raise「无 jobId/adId 锚点」。
-- 新分支 BeisenAdapter._httpx_fetch_cards 按结构特征（<a> 里有 <dd>）自动认出来，纯 httpx 零浏览器。
-- 接口形态、选路顺序与踩坑见 crawler/adapters/china_ats.py 的「卡片式 CMS 门户」一节
-- 与 docs/crawler-adapter-notes.md。
--
-- ── 接入前 live 验过的事实（2026-09-18，纯 httpx 零鉴权零浏览器）──
-- ① should_skip(source_url) 三个板块都**实测跑过** → None（不跳过）；
--    robots：fotile.zhiye.com/robots.txt 返 HTTP 200 但**零字节**，
--    crawler/robots.check_robots 对三个列表页与 /job_show 详情页实测均 allowed=True。
-- ② 端到端跑了 fetch → parse → normalize（不是只探接口），数字见下面各自的 notes。
-- ③ 逐岗详情按 CRAWL_DETAIL_CAP=3 真实打开过，全部 HTTP 200 且渲染出该岗自己的正文。
-- ④ 抓全率两道正面证明：列表条数与站点分页条自报的末页号一致，且越界页（PageIndex=末页+1）
--    实测返 HTTP 200 + 完整骨架 + 0 个岗位锚点 —— 故终止判据只能是「本页 0 行」，不能靠状态码。
-- ⑤ 全集回归：库里 358 个 enabled beisen 源在新旧两版代码下**逐源对拍**——
--    岗位合计都是 89,653，分支归属 0 变化、报错源 0 变化、reported_total 0 变化、
--    fetch_complete=True 的源都是 326。既有源一个都没少抓。
--
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187/269），显式赋值整批迁移会回滚。
--    诚实边界：classify_source_board 规则①把 adapter='beisen' 一律判成 'mixed'，
--    而这三行其实各是一个板块。'mixed' ∈ CAMPUS_BOARDS（campus_lane.py）是**超集**，
--    校招车道照样会选中它们，不构成缺陷；为一家租户去改那个共享函数要重建全列、
--    影响全部 358 个 beisen 源，不划算，故不动。
-- ⚠️ crawl_method 只认 http / playwright / manual —— 这条链纯 httpx，填 http。
-- ⚠️ industry_group / ownership / segment 的取值受 CHECK 约束（迁移 265），
--    这里沿用库里同类家电民企（老板电器 / 美的集团）的同款取值。

insert into sources (company, source_url, source_type, adapter_name, crawl_method,
                     enabled, segment, industry, industry_group, ownership, regions, notes)
values
  (
    '方太集团',
    'https://fotile.zhiye.com/social',
    'official',
    'beisen',
    'http',
    true,
    'private',
    '家电',
    '制造/工业',
    'private',
    '{CN}',
    $md$2026-09-18 接入：方太社招板块，北森卡片式 CMS 门户（纯 httpx，零浏览器）。
live：分页条自报末页 20，逐页翻到 20 页共 197 个岗，PageIndex=21 返 200 + 0 锚点（正面证明到底）；
端到端 parse 出 197 个岗，jd_url 197/197 唯一且全在官方 host，fetch_complete=True、reported_total=197。
job_type 全部「社会招聘」（取自板块路径 /social——jd_url 是 /job_show?jobId= 不带任何板块标记，
不带这个声明 recruitmentCategory 只能兜底；实测 197/197 落到「社招」）。
地点：197/197 有值；其中 30 行被服务端按宽度截断（`浙江省-宁波市-...` / `内蒙古自治区,...` /
`广西壮族自治区...`），解析时剥掉截断尾巴 —— 剥完与详情页的完整地点经 clean_location 归一到
同一个城市（`浙江省-宁波市` 与 `浙江省-宁波市-慈溪市` 都是「宁波」），两条车道写出的值一致。
发布日：197/197 取自列表卡 <ol> 的日期段。
核验样本：逐岗详情按 CRAWL_DETAIL_CAP=3 真开 3 条全 HTTP 200 + 渲染出该岗自己的正文。
诚实边界：**首抓当天是薄卡**（列表卡里那段 JD 只有职责、没有任职要求，与详情页补的不是同一段内容，
写进去会让快车道天天盖掉夜间富化的完整正文 → 刻意不写，由 enrich 档补，同中芯/科伦/启德的既有形态）。
例外是「列表值本身就残」的行（标题被截断 / 地点认不出），即使 CRAWL_DETAIL_CAP=0 也会补详情，
否则 title / location 不在 _PRESERVE_IF_EMPTY 里、会被两条车道天天互刷。
两档对拍实测：title / location / posted_at / job_type 231 行**逐行相等，0 处不一致**。$md$
  ),
  (
    '方太集团',
    'https://fotile.zhiye.com/campus',
    'official',
    'beisen',
    'http',
    true,
    'private',
    '家电',
    '制造/工业',
    'private',
    '{CN}',
    $md$2026-09-18 接入：方太校招板块（同上门户，板块独立）。
live：分页条自报末页 3，翻满 3 页共 28 个岗，PageIndex=4 返 200 + 0 锚点；
parse 28 个岗，jd_url 28/28 唯一，fetch_complete=True、reported_total=28。
job_type 全部「校园招聘」→ recruitment_category 实测 28/28 判为「校招」。
板块互不重叠：social / campus / intern 三个板块的 jobId 集合两两交集实测均为 0
（所以三行源各自的列表就是各自板块的全集，list-absence 不会跨板块误杀）。
诚实边界：届别抽不出来 —— 28 个校招岗只有 1 个在正文里提到届别相关表述，且不是 grad_class
认的硬信号（2027届/27届/Class of 2027），故 grad_class 留白。留白不隐藏，岗照常展示。$md$
  ),
  (
    '方太集团',
    'https://fotile.zhiye.com/intern',
    'official',
    'beisen',
    'http',
    true,
    'private',
    '家电',
    '制造/工业',
    'private',
    '{CN}',
    $md$2026-09-18 接入：方太实习板块（同上门户，板块独立）。
live：单页租户（不渲染分页条），6 个岗，PageIndex=2 返 200 + 0 锚点 → fetch_complete=True、
reported_total=6。job_type 全部「实习」→ recruitment_category 实测 6/6 判为「实习」。
⚠️ 这个板块是本次**发现老代码在悄悄写垃圾数据**的地方：theme2 解析器对「JD 短」的卡片会越过
3~120 字门，把「标题+地点+部门+日期+整段JD」整体当成标题入库——6 行里正好有 3 行这么进来过
（另外 3 行 JD 长、被长度门丢掉，于是这个源看着像「只有 3 个岗」且状态还是 success）。
已在 _cms_parse_list 里加「行内有 <dd> 就弃权」挡死，回归钉在 crawler/test_beisen_cms_cards.py。$md$
  )
on conflict (source_url) do nothing;
