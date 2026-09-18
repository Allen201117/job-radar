-- 279 — 接入 快看世界（快看漫画运营主体，北森租户 kkworld，26 个岗）
--
-- 与迁移 278（中创新航）同一批：复核必投清单 82 家零岗公司时 crawler/probe.py 逐家 live 探活挖出来的。
-- 台账此前记 state=no_stable_jd / fail_reason=「浏览器拦截未拿到真实逐岗 URL」，退避到 2026-10-11。
--
-- ── 接入前 live 验过的事实（2026-09-18）──
-- ① should_skip('https://kkworld.zhiye.com/social') 实测返回 None。
-- ② 端到端 fetch → parse → validate_job_quality：parse 26 / valid 26 / jd_url 唯一 26 /
--    fetch_complete=True；正文 ≥60 字 26/26（100%）。
-- ③ 逐岗详情真开 3 条：全 HTTP 200、各 21kB（…/social/detail?jobAdId=<uuid>）。
-- ④ job_type：社会招聘 25 / 实习生招聘 1；地点 北京 22 / 广州 4。
-- ⑤ 归属：浏览器渲染页面自报「快看世界 … 快看创办于2014年，是中国年轻人的国漫IP平台和分享社区」
--    + 页脚「©2026 快看世界 … Powered by Beisen」。清单里「快看漫画」是同一主体的品牌名。
--    ⚠️ adapter 解析出的 raw.company 全空（26/26），归属完全由本行 company 列决定 —— 故必须亲眼核过。
--
-- ⚠️ company 填租户自报的「快看世界」而不是品牌名「快看漫画」（CLAUDE.md 红线：ATS 源公司名只认
--    租户自报，不认 slug / 清单名）。必投覆盖不受影响：清单里「快看漫画」的 pattern 是 `%快看%`，
--    ILIKE 直接命中「快看世界」，**不需要加 aliases**（别名会改北极星口径，能不加就不加）。
-- ⚠️ crawl_method=playwright：kkworld.zhiye.com 未登记进 crawler/beisen_routes.json，
--    beisen_httpx_ready() 实测 False，run.py 的 per-source 分档会留它在浏览器车道（同 278）。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列，显式赋值整批迁移会回滚。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, industry_group, ownership, notes)
select '快看世界', 'https://kkworld.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', 'private', '动漫/内容社区', '传媒/文娱', 'private',
       '2026-09-18 接入：快看世界（快看漫画运营主体）北森租户 kkworld。live：parse 26 / valid 26 / jd_url 唯一 26 / fetch_complete=True；正文≥60字 26/26；job_type 社招 25 · 实习 1；地点 北京 22 · 广州 4；逐岗详情真开 3 条全 HTTP 200。归属据页面自报公司简介与页脚。必投清单「快看漫画」pattern=%快看% 直接命中本行 company。台账此前 no_stable_jd，退避至 10-11。'
where not exists (select 1 from public.sources where source_url = 'https://kkworld.zhiye.com/social');
