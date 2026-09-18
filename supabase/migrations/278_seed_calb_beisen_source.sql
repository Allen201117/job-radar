-- 278 — 接入 中创新航（北森租户 calbjs，社招+校招+蓝领全量 188 岗）
--
-- 来源：2026-09-18 复核必投清单 82 家零岗公司时，用 crawler/probe.py 逐家 live 探活发现的。
-- 台账此前记 state=no_stable_jd / fail_reason=「浏览器拦截未拿到真实逐岗 URL」，attempts=1，
-- 退避到 2026-10-14 —— 试一次就锁两个月，而对方租户一直是活的。
--
-- ⚠️ 这批复核同时推翻了一个**我们自己写下的结论**：漏斗的 fail_reason 文案「很可能站错了页」
-- 被当成了事实。逐家渲染后发现，同批公司里分众传媒的 /join 页有岗位表但停在 2017-11-10 且无逐岗
-- 链接、华策影视的「人才中心」页是空的 —— 那两家是**对方官网真的没有逐岗详情页**，不是我们站错页。
-- 所以「零岗 = 我们的技术缺口」这个推断只对一部分公司成立，逐家 live 探才能分清，别按文案批量下结论。
--
-- ── 接入前 live 验过的事实（2026-09-18，crawler/probe.py + 端到端脚本）──
-- ① should_skip('https://calbjs.zhiye.com/social') 实测返回 None（不跳过）。
-- ② 端到端 fetch → parse → validate_job_quality：parse 188 / valid 188 / jd_url 唯一 188 /
--    fetch_complete=True；正文 ≥60 字 187/188。
-- ③ 逐岗详情真开 3 条：全 HTTP 200、各 33kB（形如 …/campus/detail?jobAdId=<uuid>）。
-- ④ job_type 分布：社会招聘 168 / 校园招聘 14 / 蓝领招聘 6 —— adapter **不按板块分流**，
--    /social 与 /campus 两个入口实测返回**逐条相同**的 188 条，故只插一条（插两条 = 重复抓同一批）。
-- ⑤ 归属：浏览器渲染页脚自报「©2026 中创新航科技集团股份有限公司 … Powered by Beisen」，
--    校招列表里 14 个 2026 届岗（设备/工艺/质量工程师，常州·江门·枣庄·信阳·成都）。
--    ⚠️ adapter 解析出的 raw.company 是**空**（188/188 全空），归属完全由本行的 company 列决定 ——
--    这也是为什么上面那条页脚自报必须亲眼核过再插。
-- ⑥ 必投清单匹配：清单名「中创新航」⊂ 本行 company「中创新航」，resolve_owner 能认（单向子串）。
--
-- ⚠️ crawl_method 填 playwright 而不是 http：BeisenAdapter 是 PlaywrightAdapter 子类，
--    calbjs.zhiye.com 未登记进 crawler/beisen_routes.json → beisen_httpx_ready() 实测为 False，
--    run.py 的 per-source 分档会把它留在浏览器车道。登记 routes 走 httpx 快车道属于后续优化，
--    需要先确认它的 SSR 列表页有没有 jobId/adId 锚点（新版 SPA 租户常常没有，京东方就栽在这上面），
--    没验之前不填 http。
-- ⚠️ 只写 sources 允许直填的列：board 是 generated 列（迁移 187/269/276），显式赋值整批迁移会回滚。
-- ⚠️ ownership 留 unknown：中创新航第一大股东是常州金坛的国资投资平台，但公司按港股上市民营主体运作，
--    没有确凿依据前不猜（迁移 265 定的口径：名称/背景启发式一律不用于回填这个会被当筛选条件的列）。
--    industry_group 取 '制造/工业'，与库里同行一致（宁德时代 / 欣旺达 / 蜂巢能源 / 国轩高科 同组）。

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, industry, industry_group, ownership, notes)
select '中创新航', 'https://calbjs.zhiye.com/social', 'official', 'beisen', 'playwright',
       true, '{CN}', '动力电池', '制造/工业', 'unknown',
       '2026-09-18 接入：中创新航北森租户 calbjs（社招入口，adapter 实测抓全量）。live：parse 188 / valid 188 / jd_url 唯一 188 / fetch_complete=True；正文≥60字 187/188；job_type 社招 168 · 校招 14 · 蓝领 6；逐岗详情真开 3 条全 HTTP 200。归属据页脚自报「中创新航科技集团股份有限公司 Powered by Beisen」。必投缺口台账此前 no_stable_jd（attempts=1，退避至 10-14）。'
where not exists (select 1 from public.sources where source_url = 'https://calbjs.zhiye.com/social');
