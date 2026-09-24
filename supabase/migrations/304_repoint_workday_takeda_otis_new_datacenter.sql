-- 304: 武田 / 奥的斯的 Workday 租户搬了数据中心 —— source_url 改到新 host 并重新启用。
--
-- 现象：武田 wd3 自 2026-08-02、奥的斯 wd5 自 2026-08-09 起，列表与每个岗的详情一律回 422
--   （body errorCode "HTTP_422"），公开页回 500；各自连败约一个月后源被停用，名下 2,675 个 active 岗
--   的 jd_url 仍指向旧 host，用户点开是 500，巡检却天天把 422 记成「在招」盖戳。
-- 根因（2026-09-23 live）：租户迁到了 takeda.wd502 / otis.wd504（tenant 与 site 名不变），
--   新 host 列表自报 1,784 / 1,385 岗；对方官网职位页的「Apply」链接指向的就是新 host。
-- 存量已先处理（香港 jobs 库，2026-09-24）：2,675 行 jd_url / apply_url 只换 host、路径不动，
--   逐行对拍 2,675 / 2,675 一致；canonical_jd_url 由触发器重算。必须先改存量再启用本源，
--   否则列表重抓会按新 host 插一批新行，与旧 host 的存量成为同一个岗的两行。
-- 新 host 逐岗对拍这 2,675 行：S22（已撤）1,926 / 200（在招）747 / 连接错误 2 ——
--   启用后巡检按新 source_url 探活，已撤的自动下架。
-- 可逆：改回旧 source_url + enabled=false。幂等：id + 旧 source_url 双重限定，重复执行无副作用。
update sources
   set source_url = 'https://takeda.wd502.myworkdayjobs.com/wday/cxs/takeda/External/jobs',
       enabled = true
 where id = '6b54d956-44bb-4117-a3c2-98a0d17b37df'
   and source_url = 'https://takeda.wd3.myworkdayjobs.com/wday/cxs/takeda/External/jobs';

update sources
   set source_url = 'https://otis.wd504.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs',
       enabled = true
 where id = '110120d9-22c6-4b74-8953-0c6f868d8974'
   and source_url = 'https://otis.wd5.myworkdayjobs.com/wday/cxs/otis/REC_Ext_Gateway/jobs';
