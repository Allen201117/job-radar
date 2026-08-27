-- 201 — 建发房产：确认**没有独立校招板块**，把「待确认」的挂起改成定论
--
-- 迁移 199 当时把 chinacdc.zhiye.com/campus 保持停用，注释写的是「该租户是否有独立校招板块
-- 未经 live 确认，不猜」。2026-08-28 补做了这次确认，逐个路径实测：
--   /subzw/?PageIndex=1  → 200，10 个岗，详情路径 zwxq   ← 唯一有岗的板块（已在迁移 199 启用）
--   /campus              → 200 但 0 个岗（返回的是站点空壳）
--   /xzzw/  /xyzp/  /subxy/ → 200 但 title="Not Found"（该租户没有这些路由）
-- 结论：这家的老版 CMS 门户只有一个板块，社招校招混在 /subzw/ 里。
-- 把 notes 从「待确认」改成定论，免得以后有人再花一轮去探同一件事。

update sources
   set notes = 'gap_funnel:closed 该租户只有 /subzw/ 一个板块（2026-08-28 live 逐路径确认：'
               '/campus 返空壳 0 岗、/xzzw/ 与 /xyzp/ 是 Not Found）；社招校招混在 /subzw/ 里，'
               '此行永久停用，勿再探'
 where source_url = 'https://chinacdc.zhiye.com/campus';
