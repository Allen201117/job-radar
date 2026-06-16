-- 修复 Workday 公开站清一色 404「岗位不存在/页面打不开」。
--
-- 根因：commit a6ab8e5 把 Workday jd_url 从 {host}/{site}{externalPath} 误改为
--   {host}/en-US/{site}/details/{slug}（slug 只取 externalPath 末段，丢掉 /job/{location}/ 段）。
--   该 /details/{slug} 路由在 Workday 公开站点不存在 → 每个岗位链接都 404。2026-06-15 销毁式重建 +
--   httpx 回填把全部 Workday 岗位以这个坏格式重新入库，于是「清一色打不开」。
-- 适配器已修回 {host}/en-US/{site}{externalPath}（保留 /job/ 全路径，仅补 locale 前缀）。
--
-- 存量这批坏链 URL 已丢失 location 段，无法用纯 SQL 原地重建出正确的 /job/{location}/... 链接，
-- 故置为 expired（不删除，保 job_actions 外键；与撤岗治理同口径）。这些坏链岗立即离开 active 看板，
-- 杜绝继续给用户 404；下一轮 workday 抓取会以正确 URL 重新入库（canonical 不同 → 插新 active 行，
-- expired 坏行留在库里无害、不进 active 唯一索引）。
--
-- 过滤精确到 Workday 自身的坏格式：仅 *.myworkdayjobs.com 且路径含 /details/。
-- Apple（jobs.apple.com/.../details/…）等其它源的合法 /details/ 链接不受影响。
begin;
set local statement_timeout = '1800s';

update jobs
   set status = 'expired'
 where status = 'active'
   and jd_url like '%myworkdayjobs.com/%/details/%';

commit;
