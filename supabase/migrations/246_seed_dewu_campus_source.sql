-- 246 — 接入得物校招（campus.dewu.com，独立域名的飞书招聘子租户，160 岗）
--
-- 得物社招已有源（company='得物 POIZON'，poizon.jobs.feishu.cn/index/position）。校招不在
-- 同一个飞书子域名下——live 探完 poizon.jobs.feishu.cn/campus、/internship 均 404，真正的校招站点是
-- 独立域名 campus.dewu.com（同一套飞书招聘引擎：页面内嵌 window.gfdatav1 / website_info.tenant_id
-- 与 poizon 租户的 saas-career 前端资产同源，只是把站点挂在自有域名而非 *.jobs.feishu.cn 下）。
--
-- ⚠️ 这是 FeishuGenericAdapter 第一次遇到「路径段既不是 index 也不是常见子门户名，而是租户自己的
-- 数字 portal id」的形态（campus.dewu.com/578078，578078 = website_info.id 的一部分）。**逐项验证
-- 通用层 _bind_host / _bind_website_path 对这种路径的推导，结果是不需要任何代码改动**：
--   · _bind_host 取路径首段 "578078"（≠ "index/position"）→ detail_template =
--     https://campus.dewu.com/578078/position/{id}/detail，list_urls 含 /578078。
--   · _bind_website_path 同样取首段 "578078"（不在 "", "index", "position" 白名单里）→
--     website_path="578078" → httpx 请求头带 website-path: 578078。
-- 与真实前端发出的请求逐项比对一致（Playwright 拦截 /578078/position 页面自己发的
-- POST /api/v1/search/job/posts，header website-path=578078，body 除 portal_type/storefront_id_list
-- 字段名与 adapter 默认 body 略有出入外结构相同）——**live 验证过 adapter 默认 body 换成
-- website-path=578078 头后照样拿到 count=160**，说明字段名差异不影响这个租户。
--
-- ── live 验证（2026-09-09）──
-- ① robots.txt：campus.dewu.com/robots.txt 返 404（未禁止抓取）。
-- ② httpx 直拉 POST https://campus.dewu.com/api/v1/search/job/posts（website-path: 578078 头，
--    无需 _signature）：Code 0，count=160，翻页收满 160/160；recruit_type 全部父级=校招
--    （正式 152 / 实习 8）——与社招源完全独立的池子。
-- ③ 详情页 https://campus.dewu.com/578078/position/{id}/detail Playwright 冷加载渲染出标题
--    （抽验「【27届校招】安全产品/策略开发工程师」，document.title 与正文均正确）。
-- ④ should_skip 实测不跳过（详情页 200，非 404/410，无需 _repair_detail_template 兜底）。
-- ⑤ crawl_method='http'：feishu 在 run.py 的 _HTTPX_SAFE_ADAPTERS 白名单里，daily-crawl 无
--    Playwright 也能跑；本源 httpx 直拉已验证可达，不必占用浏览器慢车道。
-- 详见 crawler/test_feishu_dewu_campus.py 的离线 parse 断言。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, regions, notes)
select '得物 POIZON', 'https://campus.dewu.com/578078', 'official', 'feishu', 'http', 'private', '电商', '{CN}',
  $md$2026-09-09 接入：得物校招独立域名 campus.dewu.com，飞书招聘引擎同款子租户（非 *.jobs.feishu.cn）。
live 实测 count=160（正式 152 + 实习 8），端到端 fetch+parse 通过，详情页 Playwright 冷加载渲染出标题。
与社招源（poizon.jobs.feishu.cn/index/position）是两个独立入口/独立池子，公司名沿用「得物 POIZON」保持归属一致。$md$
where not exists (select 1 from sources where source_url = 'https://campus.dewu.com/578078');
