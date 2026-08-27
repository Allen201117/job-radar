-- 198 — seed：中芯国际（北森老版 CMS 三个板块）+ DHL（Phenom widgets 分支）
--
-- 两条都是「必投清单缺口逐家核实」查出来的，2026-08-27 live 实测：
--
-- 【中芯国际 563 岗】之前抓不到的真因**不是技术**，是**租户 slug 猜错了**：
--   台账里记的是 smic / zhongxin，真实租户是 **smics**（与官网 smics.com 一致）。
--   官网「招贤纳士」页直接外链到 smics.zhiye.com 的三个板块，不是猜的。
--   它是北森的**老版 SSR CMS 门户**（theme2），抽不到 PortalId、没有 GetJobAdPageList 接口，
--   所以旧 adapter 会掉进浏览器慢车道且社招/海外抽不出 jd_url（SSR 详情路由表里只有 campusxq）。
--   本次已扩 BeisenAdapter 支持该形态（纯 httpx 零浏览器）。
--   live：社招 293 + 校招 248 + 海外 22 = 563，全部过质量门、正文覆盖 ~99%，fetch_complete=True。
--   校招板块含大量「2027届校招」，对校招专区是高价值供给。
--   三个板块分开登记：sources.board 是按 source_url 派生的生成列（迁移 187），分开登记才能
--   让校招板块被校招车道正确识别。
--
-- 【DHL 130 岗】平台判定之前是**错的**：台账当它是 SuccessFactors，实际是 **Phenom**（租户 DPDHGLOBAL）。
--   而且该租户没开 Phenom 常规的 /api/jobs（4 种参数组合恒 500，对照组 AMD 同路径 200 正常），
--   只能走 POST /widgets（ddoKey=refineSearch，零 CSRF/cookie/登录）。本次已给 phenom adapter
--   加了这条分支 + 「首个请求就失败才回退」的自动选路（不按域名写死）。
--   regions 用 {CN,HK}：与同 adapter A 分支的既有口径一致（A 分支在 regions={CN} 时本就连带抓香港），
--   且项目本就把港澳算国内范围。live：{CN}=121 岗 / {CN,HK}=130 岗，全部带正文、全部过质量门。
--   逐岗判死信号很干净：伪 id 返 HTTP 410 Gone 且完全没有 <title>。
--
-- 另有两处「零新增源」的覆盖修复同批上线，不在本迁移里（改的是 adapter 的归属派生逻辑）：
--   京东按 positionDeptName 派生 → 京东科技 209 + 京东物流 629
--   网易按 productName 派生     → 网易有道 115 + 网易云音乐 157
--   它们抓的都是**现有源里已有的岗**，新增源会与现有源抢同一行 upsert，故一律不新增源。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('中芯国际', 'https://smics.zhiye.com/social',   'beisen', 'http', '{CN}',    'private', '半导体', true),
  ('中芯国际', 'https://smics.zhiye.com/campus',   'beisen', 'http', '{CN}',    'private', '半导体', true),
  ('中芯国际', 'https://smics.zhiye.com/overseas', 'beisen', 'http', '{CN}',    'private', '半导体', true),
  ('DHL',      'https://careers.dhl.com/widgets',  'phenom', 'http', '{CN,HK}', 'foreign', '物流',   true)
on conflict (source_url) do nothing;   -- 迁移 180 的 sources_unique_source_url，重复应用幂等
