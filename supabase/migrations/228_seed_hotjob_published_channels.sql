-- 228 — 补两条「渠道确实发布、页面确实能打开」的 hotjob 源
--
-- 背景：荣耀 Honor 的 society 渠道未发布（列表页「内部处理中」、逐岗永远转圈），
-- 被 hotjob adapter 的渠道发布门按设计跳过 —— 这不是 bug，那 407 个岗用户点开就是死链。
-- 但同租户的 **intern 渠道是发布的**，此前库里没有对应源，等于白白丢掉能用的供给。
--
-- 2026-09-05 对全部 131 条启用中 hotjob 源做了三渠道普查，找出 7 个「已发布但库里没源」
-- 的渠道，逐个走 adapter 真抓 + 浏览器真渲染两道验收，只有下面 2 条同时满足
-- 「有在招岗」+「逐岗详情页真能渲染出完整 JD」：
--   · 荣耀 Honor 实习   intern  15 岗（reported_total=15, fetch_complete=true）
--   · 易方达基金 校招   campus 113 岗（reported_total=113, fetch_complete=true）
-- 被否掉的 5 条及原因（**不要再来加它们**）：
--   · 中信银行信用卡中心 校招 / 中国中化 intern —— 门发布了，但整站已下掉，
--     页面显示「官网不存在，无法继续访问!」（浏览器实测，非瞬时）；
--   · 华润电力 校招 / 赢家时尚 校招 / 郑州银行 校招 —— 渠道发布但 0 个在招岗。
--
-- Idempotent: guarded by source_url。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, board, notes)
select '荣耀 Honor 实习', 'https://career.honor.com/SU61b9b9992f9d24431f5050a5/pb/interns.html', 'official', 'hotjob', 'http', 'private', '手机/智能终端', 'intern', '荣耀 Honor 实习（intern 渠道已发布；2026-09-05 live 15 岗 + 浏览器验证详情页渲染完整 JD。同租户 society/campus 两渠道未发布，故只接 intern）'
where not exists (select 1 from sources where source_url = 'https://career.honor.com/SU61b9b9992f9d24431f5050a5/pb/interns.html');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, board, notes)
select '易方达基金 校招', 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/school.html', 'official', 'hotjob', 'http', 'private', '基金·资管', 'campus', '易方达基金 校招（campus 渠道已发布；2026-09-05 live 113 岗 + 浏览器验证详情页渲染完整 JD。同租户 intern 渠道未发布，那条源按设计一直被跳过）'
where not exists (select 1 from sources where source_url = 'https://wecruit.hotjob.cn/SU67ac68866202cc7916aea66e/pb/school.html');
