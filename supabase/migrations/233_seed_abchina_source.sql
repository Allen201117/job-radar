-- 233 — seed：中国农业银行自建招聘门户（2026-09-05 live 核实，浏览器档）
--
-- 补上 232 那一批里唯一没接通的一家。它和另外五家不是同一类问题：
-- **不是「没有逐岗详情页」，是「接口响应体加密」**。career.abchina.com 的
-- new/getInfo 明文发一把 1024 位 RSA 公钥做密钥交换，之后 org/* 与 orgPosition/* 的响应体
-- 是一长串 hex，页面用 SM4-ECB 解开 —— 明文只存在于浏览器内存里，所以只能走 Playwright，
-- 读页面已经渲染好的 React state（不拦接口、不解密）。
--
-- live 2026-09-05（跑仓库里真实 adapter）：校招 2,580 个岗、耗时 93 秒、46 个招聘机构走遍。
-- 社招当期 0 —— 与官网自己写的「暂无最新招聘公告 / 暂无热招事项」一致，且机构单选框全 disabled。
--
-- 逐岗 jd_url 实测冷加载能打开、正文完整（岗位职责/基本条件/具体要求）：
--   https://career.abchina.com/build/index.html#/PositionDetails/:155541420
--   ⚠️ URL 里那个冒号是**字面量**（前端拼串时把路由占位符一起拼进去了），不是要替换的东西。
--   ⚠️ 详情是 window.open 打开的，在页面上点一下「像没反应」—— 当初正是被这个假象误判成公告制。
--
-- ⚠️ crawl_method 必须是 playwright（这条要起无头浏览器，落串行浏览器档，不能进 httpx 并发档）。
insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled, notes)
values
  ('农业银行', 'https://career.abchina.com/build/index.html', 'abchina', 'playwright', '{CN}', 'soe', '银行', true,
   '响应体 SM4 加密 → Playwright 读 React state（batchCardInfo 枚举机构 / posCardInfo 取岗位）。'
   '必须先 goto 首页把会话建起来，否则 hash 路由只渲染空壳；hash 是同文档导航，换机构必须 reload，'
   '否则会把上一家的岗位当成这一家的。正文只在逐岗详情页，列表侧不带，靠 enrich 另补。')
on conflict (source_url) do nothing;
