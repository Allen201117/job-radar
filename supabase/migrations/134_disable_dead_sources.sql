-- 134 — 下架「已入源质量验证」(crawler/verify_sources.py) 确认的死源/错源
-- 依据：全库质量审计(2026-06-11，868 源逐个 fetch→parse→质量门) + 多次复验，确认以下 4 个**持续 0 岗**
--       且非沙箱网络/非季节性原因。机制：enabled=false 即排除出 daily-crawl（db.get_sources 只取
--       enabled=true）。可逆：改回 true 即恢复。Idempotent：重复 set false 为 no-op；schema_migrations 防重跑。
--
--   · 百度 campus-list / intern-list：source_url 指向 SPA 网页(HTML, content-type=text/html)而非 JSON
--     接口，adapter 取 0 岗；主源 talent.baidu.com/jobs/list 已覆盖百度（含校招/2027 应届岗）。
--   · 海尔 maker.haier.net：仅解析到入口/导航页，无逐岗 jd_url（CLAUDE.md 早标「暂不可用」）。
--   · 地平线 horizon.jobs.feishu.cn：飞书端点 3 次复验均返回近空(219B；同族 nio/xpeng/xiaomi 各 600 岗)，
--     疑公司已迁出该飞书租户。如需恢复覆盖，另寻地平线当前官方招聘页重新加源。
--
-- 保留**不**下架（可达、仅当前空，会自动回填，下架反丢覆盖）：
--   赣锋锂业(beisen 社招暂空,可达)/华润电力校招(hotjob 校招季关闭)/Diageo(workday 暂无在华岗)。
-- 另：6 个 feishu 源(小马智行/XREAL/Momenta/拓竹/欢乐互娱/极致游戏)在本地沙箱被 anti-bot，
--     但同沙箱 46 个其它 feishu 源正常 → 须线上 CI 复验，**不在本次下架之列**。

update sources set enabled = false
where source_url in (
  'https://talent.baidu.com/jobs/campus-list',
  'https://talent.baidu.com/jobs/intern-list',
  'https://maker.haier.net/client/job/index',
  'https://horizon.jobs.feishu.cn/index/position'
);
