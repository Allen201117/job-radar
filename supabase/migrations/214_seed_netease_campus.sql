-- 214 — 网易校招板块补齐（2027 届秋招，含互娱 / 雷火 / 互联网三条线）
--
-- 背景：库里只有网易社招（hr.163.com）。2026-09-03 判「网易校招接口未解」——其实接口完全公开，
-- 难点不在鉴权，在**判「哪个招聘项目还开着」**：campus.163.com 后台把 2019 年至今的 93 个项目
-- 全留着，对早已结束的项目照样返回岗位（projectId=1 还能返 2019 届的岗），而 `projectStatus`
-- 恒为 1、毫无区分度。照单全收 = 把七年前的死岗当在招入库。
--
-- 解法：唯一可靠信号是**项目名里的届次**（"2027届雷火秋季校园招聘"）。adapter 按
--   ① 名字含「测试/勿动」→ 丢（后台真有 4 个这种项目，其中一个还挂着 3 个岗）
--   ② 能解析出届次 → 届次 ≥ 本轮目标届才要
--   ③ 没有届次（如《蛋仔派对》AI实习专项）→ 只有导航接口列出来的才要
-- 三条规则筛选，projectId 按时间递增（1=2019届…104=2027届，93 个逐一核对过）故只在导航最大 id
-- 附近开窗扫描，明年不用改代码。
--
-- live 2026-09-04：选出 2027/2028 届 8 个项目，自报 255 岗、parse 出 245 条（其余非中国地点），
-- fetch_complete=True，jd_url 245/245 零重复，列表直接带 positionDescription + positionRequirement。
-- 被规则挡掉的包括「2026届互联网校招-秋招」「2025届互联网秋季校园招聘」等 5 个仍能返回岗位的过期项目。
--
-- jd_url = https://campus.163.com/app/detail/index?id={id}
-- ⚠️ 该路由是**点击卡片后拦截 window.open/pushState 抓到的**，不是猜的；互娱(102)/雷火(77)/
--    互联网(103) 各取一岗 live 核过，都在 campus.163.com 这一个域名下正常渲染
--    （导航里互娱指向 campus.game.163.com，但那只是入口页，详情页两边通用）。
--
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'；写 'browser' 会整批回滚（迁移 211 踩过）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '网易', 'https://campus.163.com/app/job', 'official', 'netease_campus', 'http',
       'private', '互联网·游戏',
       '网易校园招聘（campus.163.com，与社招 hr.163.com 是两套系统）。'
       'live 2026-09-04：2027/2028 届 8 个项目共 255 岗，245 条入库、全部带正文。'
       '⚠️ 该后台保留全部历史项目且 projectStatus 恒为 1，必须按项目名里的届次筛选，'
       '否则会把 2019 起的过期项目当在招。'
where not exists (select 1 from sources where source_url = 'https://campus.163.com/app/job');
