-- 250 — 接入联想（Lenovo）校园招聘，库里此前零源零岗
--
-- 必投清单里联想的 pattern 是 `%联想%`（lib/must-apply-list.json 第 117-118 行），
-- 此前库里没有任何一行公司名含「联想」——按 CLAUDE.md「必投某家零岗」的排查顺序，
-- 先查了 sources 表确认真的零源，不是 regions/别名问题，属纯新增源。
--
-- ── 接入前 live 验过的事实（2026-09-09，真 Chrome 打开 https://talent.lenovo.com.cn/position）──
-- ① 列表接口零鉴权可达：GET /gateway/jobBase/list?pageNum=1&pageSize=50
--    → code:0, result.total=90，pageSize 参数真实生效（试过 10/50/100 均如实返回）。
-- ② 字典接口 GET /gateway/sysDict/all（页面加载时自拉，用于把 workPlace/educationRequired/
--    projectType 字典码翻中文）；projectType 当前只出现 1（应届生招聘）/3（人才项目），
--    2（实习生招聘）目前无在招岗，与页面文案「实习生项目已结束」一致。
-- ③ 详情页 https://talent.lenovo.com.cn/position/detail?id={id} 冷加载渲染出标题
--    （live 验过 id=2339 →「数据开发工程师」）。
-- ④ /robots.txt 返回 200 text/html（SPA 的 HTML 兜底页，不是真 robots 文件）→ 视为无限制；
--    对列表接口与 /position 页面的 HEAD 预检均实测 200，should_skip 不会跳过。
-- ⑤ 端到端跑了一遍 crawler/adapters/lenovo.py（不是只探接口）：fetch+parse 出 90/90 岗，
--    jd_url 90/90=100%、有正文(≥60字) 90/90=100%，fetch_complete=True（抓全）。
--
-- 详细接口笔记见 crawler/adapters/lenovo.py 顶部 docstring。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
values (
  '联想 Lenovo',
  'https://talent.lenovo.com.cn/campus',
  'official',
  'lenovo',
  'http',
  true,
  'private',
  '消费电子/PC',
  '{CN}',
  $md$2026-09-09 接入：talent.lenovo.com.cn 校招门户，纯 httpx 零鉴权。live 实测 total=90，
端到端 parse 出 90 岗，100% 带 jd_url、100% 有正文，fetch_complete=True。
projectType 字典码 1=应届生招聘/3=人才项目/2=实习生招聘（当前无在招），列表接口一次返全部在招项目类型，
故只开这一行，不再拆 /campus /intern 多行。$md$
)
on conflict do nothing;
-- 📌 source_url 用站内真实存在的 /campus 路由（SPA 路由表里有 path:"/campus"），而不是 /position：
--   sources.board 是按 URL 令牌生成的（classify_source_board），/position 会被判成 social，
--   campus-crawl 高频车道就不会按 board 选中它；adapter 本身不看 source_url 的路径。
