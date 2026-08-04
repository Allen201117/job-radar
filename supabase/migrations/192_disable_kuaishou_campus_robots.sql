-- 192 — 停用快手校招源：robots.txt 全站禁止抓取
--
-- 迁移 190 加了 `https://campus.kuaishou.cn/`（kuaishou_campus adapter）。技术上完全打通——
-- 公开接口零鉴权、live 抓到 510 岗全带 JD 正文、逐岗详情页可验证。
-- **但 2026-08-04 首轮生产运行暴露：该域 robots.txt 是 `User-agent: * / Disallow: /`**，
-- 明确禁止任何抓取。crawler/run.py 的 check_robots 正确地把它记为 skipped、一条都没写库
-- （库内 `jd_url like 'https://campus.kuaishou.cn/%'` 实测 0 行，没有脏数据要清）。
--
-- 对比：社招域 zhaopin.kuaishou.cn 的 /robots.txt 返 404（无 robots = 允许），
-- 所以既有 `kuaishou` 社招源不受影响，照常抓。
--
-- ⚠️ 这是**合规边界，不是技术问题**，不要试图绕过（改 UA / 忽略 robots / 换代理都不行）。
-- 项目合规红线见 CLAUDE.md「开发规范：外部请求…遵守合规边界」。
-- 只 disable 不删行：万一快手日后放开 robots，把 enabled 改回 true 即可复用（adapter 代码保留且有单测）。

update sources set enabled = false
where adapter_name = 'kuaishou_campus';
