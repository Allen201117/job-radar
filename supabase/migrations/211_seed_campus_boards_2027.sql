-- 211 — 必投清单大厂「校招板块源」补齐（2027 届秋招）
--
-- 背景：这几家我们**只接了社招板块**，校招岗几乎为零（vivo 0 / 京东 2 / 腾讯本体偏少），
-- 而对方 2027 秋招早已开闸。逐家 live 探测（2026-09-03）确认它们各有独立校招域名与接口。
--
-- ⚠️ 踩坑记录（下次探 SPA 校招门户直接照这个来，别重蹈覆辙）：
--   1) **判「有没有逐岗详情页」不能看「点击后 location.href 变不变」** —— 这些 SPA 一律用
--      `window.open` 开新标签，当前页 URL 纹丝不动。正确做法是**拦截 window.open / pushState**
--      再点一次卡片，真实 URL 会自己打印出来。我按 URL 没变判过京东/海康「无详情页」，是错的。
--   2) 猜 URL 模板必错。京东真实路由是 `#/details?id=`（我猜的 jobDetail/job/positionDetail 全空白）；
--      腾讯是 `post_detail.html?pid=&id=`（JS 里挖到的 jobdesc.html 返回「404 | 腾讯校招」）。
--   3) 读接口先确认字段名：腾讯列表在 `data.positionList`，不是 `data.list` —— 读错会看到
--      `count=869` 却拿到 0 条，极易误判成「限流」。
--
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'（sources_crawl_method_check）。
--    写 'browser' 会让整个迁移事务回滚——连前面几条合法的 insert 一起没了。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select 'vivo', 'https://hr-campus.vivo.com/', 'official', 'beisen', 'http', 'private', '互联网·智能终端',
       'vivo 校园招聘（北森 PortalId=903cbcbf…，与社招 hr.vivo.com 完全不同的系统）。'
       'live 2026-09-03：257 岗全部带 jd_url + 正文（/campus/detail?jobAdId={Id}，路由已登记 beisen_routes.json）。'
where not exists (select 1 from sources where source_url = 'https://hr-campus.vivo.com/');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '腾讯', 'https://join.qq.com/', 'official', 'tencent_campus', 'http', 'private', '互联网',
       '腾讯校园招聘（join.qq.com，与社招 careers.tencent.com 完全不同的系统）。'
       'live 2026-09-03：869 岗、jd_url 零重复、翻页 complete。'
       '⚠️ 分页参数是 pageIndex（pageNum/page/pageNo 会被静默忽略、每页返回同一批）。'
where not exists (select 1 from sources where source_url = 'https://join.qq.com/');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '海康威视', 'https://campushr.hikvision.com/school', 'official', 'hikvision', 'http', 'private', '互联网·智能物联',
       '海康威视校园招聘（campushr.hikvision.com，社招 talent.hikvision.com 被 EdgeOne 拦，两者分离）。'
       'live 2026-09-03：257 岗（校招应届生 171 / 校招实习生 86），257/257 全部带正文，jd_url 零重复。'
       '⚠️ 分页参数走 URL query，放 JSON body 里会被静默忽略、每页恒返首批 10 条。'
where not exists (select 1 from sources where source_url = 'https://campushr.hikvision.com/school');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '京东', 'https://campus.jd.com/', 'official', 'jd_campus', 'playwright', 'private', '互联网',
       '京东校园招聘（campus.jd.com，jd.py 只抓社招 zhaopin.jd.com）。'
       '⚠️ 列表接口有风控：httpx 直调返回 JDOA 拦截页，必须浏览器拦截页面自己发的请求。'
       'jd_url = #/details?id={publishId}（拦截 window.open 抓到的，其余路由全渲染空白）。'
where not exists (select 1 from sources where source_url = 'https://campus.jd.com/');
