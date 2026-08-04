-- 190 — seed：快手校园招聘源（2027 届秋招供给基座）
--
-- 背景：我们此前只接了快手**社招**站 `zhaopin.kuaishou.cn/#/official/social/`（需 Playwright 拦截
-- 页面签名请求），校招是**另一个站** `campus.kuaishou.cn`，从没接过 → 库里快手校招岗 = 1 个。
--
-- 2026-08-04 live 实测：校招站的接口是公开的 `/open/` 路径，**纯 httpx 零鉴权**，比社招那条路还轻：
--   · 项目字典 GET  /recruit/campus/e/api/v1/dictionary/batch?types=recruitSubProject
--       → [{code:"20271779425607", name:"2027应届生"}, {code:"20271772783534", name:"2027实习生"}, …]
--   · 职位列表 POST /recruit/campus/e/api/v1/open/positions/simple
--       body {"recruitSubProjectCodes":[code],"pageSize":100,"pageNum":1}（GET 会返 40014）
--   · 详情页    https://campus.kuaishou.cn/#/campus/job-info/{id}
--       （浏览器打开 id=13012 验证：渲染出岗位名 + 职位描述 + 任职要求全文）
--
-- adapter 端到端 live 实测产出：**510 岗全部带 JD 正文**、fetch_complete=True，
-- 其中 2027 届 305 个（应届 77 + 实习 228）、2026 届 205 个（会被当季届别过滤挡在专区之外）。
--
-- ⚠️ 项目码动态发现、不硬编码：`20271779425607` 每届都变，写死等于明年自动失效——
-- 而校招 adapter 恰恰是换届那一刻最需要它工作。见 crawler/adapters/kuaishou_campus.py。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('快手 Kuaishou', 'https://campus.kuaishou.cn/', 'kuaishou_campus', 'http', '{CN}', 'private', '互联网', true)
on conflict (source_url) do nothing;   -- 迁移 180 的 sources_unique_source_url，重复应用幂等
