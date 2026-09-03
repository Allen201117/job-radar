-- 213 — 哔哩哔哩校招板块补齐（2027 届秋招）
--
-- 背景：B站在库里只有社招源（jobs.bilibili.com/social，499 岗）。2026-09-03 曾用社招接口传
-- recruitType=1/2 探过，返回 total=0，据此判「对方没开校招」——**结论是错的**：
-- 当天 jobs.bilibili.com 首页就挂着「哔哩哔哩2027届秋季校园招聘正式启动！」。
-- 真相是校招走**另一条 API**（/api/campus/position/positionList），社招那条接口的行
-- recruitType 恒为 0，传别的值只会返回空——空结果 ≠ 对方没开。
--
-- ⚠️ 通用教训：**「接口返 0」只能证明「这么问拿不到」，不能证明「对方没开」。**
--    判「开没开」要看对方**页面上自己怎么说**（招聘公告 / 网申起止日期），再回头找对的入口。
--
-- live 2026-09-04 实测：校招 91 + 实习 281 = 372 岗，parse 出 366 条（其余为非中国地点），
-- fetch_complete=True，列表直接带 positionDescription 全文正文。
-- jd_url = https://jobs.bilibili.com/campus/positions/{id}，用 id=29738 核过页面渲染的正是该岗。
--
-- board 判定：source_url 含 `campus` 令牌 → classify_source_board 规则④ 已判成 campus，
-- 无需改函数、无需重建派生列。
--
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'（sources_crawl_method_check）；
--    写 'browser' 会让整个迁移事务回滚——连前面合法的 insert 一起没了（迁移 211 踩过）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '哔哩哔哩', 'https://jobs.bilibili.com/campus/positions', 'official', 'bilibili_campus', 'http',
       'private', '互联网·内容社区',
       '哔哩哔哩校园招聘（/api/campus/position/positionList，与社招 /api/srs/… 是两条独立 API）。'
       'live 2026-09-04：校招 91 + 实习 281 = 372 岗，列表自带正文。'
       '⚠️ 校招/实习两个桶（positionTypeList Freshmen=3 / Intern=0）必须分别翻——'
       '不传该字段拿到的不是并集（live: 不传只有 100 条）。'
where not exists (select 1 from sources where source_url = 'https://jobs.bilibili.com/campus/positions');
