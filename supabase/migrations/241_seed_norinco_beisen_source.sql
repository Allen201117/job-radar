-- 241 — 接入中国兵器工业集团（北森租户，1,732 岗）
--
-- 来源：2026-09-07 那轮「/programs 补央国企」的副产品。核验 25 家时发现 8 家**其实有逐岗页**，
-- 它们不该进 /programs（那等于告诉用户「这家没有岗位可看」而他其实搜得到 —— 中通那个错，见迁移 238），
-- 该接进岗位库。兵器是其中体量最大的一家，创始人拍板先接它。
--
-- ⚠️ 为什么只有一行、而不是校招/社招各一行：
--   BeisenAdapter._httpx_fetch 发的是 `Category: []` = **不按招聘类别过滤，一次返该租户全部岗**
--   （社招+校招+实习+内部）。再插一行 /social 只会得到同一批数据 → 重复源
--   （迁移 186 已经清过一次这种重复）。board 因此填 mixed。
--
-- ── 接入前 live 验过的四件事（2026-09-07）──
-- ① 列表接口零鉴权可达：POST https://norincogroupzhaopin.zhiye.com/api/Jobad/GetJobAdPageList
--    → Code:200, **Count:1733**，每条带完整 Duty/Require 正文。
-- ② 详情路由是**逐岗**的、不是通用页：真浏览器渲染两个不同 jobAdId，
--    ec181e71-… → 「【技术岗】焊接工艺工程师」（重庆长安望江工业集团）
--    62a612ce-… → 「【技术岗】质量工程师」（同单位，内容完全不同）
--    ——换 id 换内容，才敢写进 beisen_routes.json。第二次导航**强制 reload** 后再读，
--    避免 SPA 同文档导航拿到上一个岗的残留（CLAUDE.md 那条 hash 路由碑的同一个机制）。
-- ③ **端到端跑了一遍 adapter**（不是只探接口）：fetch+parse 出 **1,732 岗，
--    带 jd_url 1,732/1,732 = 100%，其中有正文(≥60字) 1,649 = 95%，fetch_complete=True（抓全）**，
--    jd_url host 全部是 norincogroupzhaopin.zhiye.com（无外链混入）。
-- ④ 不与存量重复：sources 表与香港 jobs 库按 `兵器|norinco` 宽别名查，均零命中。
--
-- 📌 配套改动：crawler/beisen_routes.json 新增
--    "norincogroupzhaopin.zhiye.com": "https://norincogroupzhaopin.zhiye.com/campus/detail"
--    没有这一行，BeisenAdapter 会落进浏览器慢车道（daily-crawl 没装 Playwright → 直接 failed）。
--    路由登记后 beisen_httpx_ready() 返 True，进 httpx 并发快车道，零浏览器。

-- 🚩 本文件第一版在生产上失败过一次，成因值得记：
--    `ERROR: cannot insert a non-DEFAULT value into column "board"`
--    —— board 是 GENERATED ALWAYS AS classify_source_board(adapter_name, source_url) STORED（迁移 187/212/220），
--    显式赋值会让整个迁移文件回滚。迁移 223 / 228 / 232 的抬头都已经写着「不要写 board 列」，
--    我照着 SELECT 出来的**值**去复刻临时表做校验，复刻件里 board 是普通列 → 本地绿、线上红。
--    ✅ 教训：拿临时表验 SQL 时，**必须照 DDL 复刻（生成列 / 约束 / 默认值），不能照查询结果复刻**，
--       否则校验件比被校验的东西还宽松，等于没验。
--    beisen 命中 classify_source_board 规则①（adapter 一次抓全社招+校招+实习）→ 自动得 board='mixed'，
--    正是本源想要的，所以不写这一列就够了。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
values (
  '中国兵器工业',
  'https://norincogroupzhaopin.zhiye.com/jobs',
  'official',
  'beisen',
  'http',
  true,
  'soe',
  '军工·央企',
  '{CN}',
  $md$2026-09-07 接入：集团级北森门户（不是某个下属院所），live 实测 Count=1733、端到端 parse 出 1732 岗，100% 带 jd_url、95% 有正文、fetch_complete=True。
Category:[] 一次返全部板块（社招/校招/实习），故只开这一行、board=mixed，别再加 /social 或 /campus 行（会成重复源）。
详情路由已登记进 beisen_routes.json（/campus/detail?jobAdId={Id}），换 id 换内容已核。$md$
)
on conflict do nothing;
