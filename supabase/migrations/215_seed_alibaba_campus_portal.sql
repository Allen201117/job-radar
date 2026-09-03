-- 215 — 阿里巴巴集团统一校招主站（2027 届秋招）
--
-- 背景：库里已有 13 个阿里 BU 的 `{bu}.com/campus/position-list`（adapter alibaba_campus，
-- 高德 45 / 淘天 34 / 控股 10…，都抓全了）。但那是**各 BU 的零散口子**，集团统一校招主站
-- campus-talent.alibaba.com 一直没接——那里才是 2027 届秋招的主战场。
--
-- 2026-09-03 曾判该站「login_wall（匿名 POST 返回 403）」，**结论是错的**：它要的不是登录，
-- 是 CSRF。先 GET 任意页面拿 `XSRF-TOKEN` cookie，再把该值当 query 参数 `?_csrf=` 带上即可。
-- 不带、或随便塞一个 uuid，都返回 403（三种都实测过）。
--
-- ⚠️ 这是今晚第三次同款误判（B站/华为/阿里）：**403 / total=0 只能证明「这么问拿不到」，
--    不能证明「对方没开或要登录」。** 判断前先看对方页面自己怎么说，再回头找对的问法。
--
-- live 2026-09-04：批次清单接口 listBatch 自报 3 个在招项目——2027届应届生 479 + 日常实习生 347
-- + 研究型实习生 249 = 1,075 岗；parse 出 1,060 条（其余非中国地点），fetch_complete=True，
-- jd_url 1060/1060 零重复，列表直接带 description + requirement 全文。整源 13 秒。
-- ⚠️ 阿里星与应届生**共用 batchId 100000760001**，adapter 按 id 去重，否则整批岗抓两遍。
--
-- jd_url = https://campus-talent.alibaba.com/campus/position/{id}
-- ⚠️ 路由取自站点 JS 路由表并 live 核过（id=199907740040 渲染的正是「AI应用算法工程师」）；
--    列表行里的 positionUrl 恒为 null，别指望它。
--
-- board：source_url 含 campus 且不含 off-campus → classify_source_board 规则④ 判 campus，
-- 无需改函数、无需重建派生列。
--
-- Idempotent: guarded by source_url。crawl_method 只接受 http/playwright/manual。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '阿里巴巴', 'https://campus-talent.alibaba.com/campus/position', 'official',
       'alibaba_campus_portal', 'http', 'private', '互联网',
       '阿里巴巴集团统一校招主站（与各 BU 的 alibaba_campus 源并存，两者都要留）。'
       'live 2026-09-04：3 个在招批次共 1,075 岗，1,060 条入库、全部带正文。'
       '⚠️ 需 CSRF：GET 页面拿 XSRF-TOKEN cookie → POST 带 ?_csrf=；不带返 403（不是登录墙）。'
where not exists (select 1 from sources
                  where source_url = 'https://campus-talent.alibaba.com/campus/position');
