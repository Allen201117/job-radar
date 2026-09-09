-- 251 — 理想校招源 URL 去掉查询串：www.lixiang.com 的 robots 是 `Disallow: /*?*`（2026-09-09 CI 实测）
--
-- 现象：迁移 247 插的源第一轮 campus-crawl 就被记 skipped：`robots.txt: robots.txt disallows /*?*`。
-- 根因：run.py 的 robots 门只对 **source_url** 做检查，247 填的是页面地址 `campus.html?fromJob=1`，
--   带 `?` 正好撞上 lixiang.com 对「任何带查询串的页面」的禁抓规则；adapter 本身根本不看 source_url
--   的路径（数据全走 api-web.lixiang.com 的公开接口，该域没有 robots）。
-- 修法：source_url 改成不带查询串的同一页面（robots 允许），adapter 行为不变。
-- ⚠️ 逐岗 jd_url 仍带 `?jobCode=`：那是给用户点开的链接，不是我们抓取的对象；本仓库不对
--   www.lixiang.com 的页面发请求，不违反其 robots。
update sources
   set source_url = 'https://www.lixiang.com/employ/campus.html',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-09 source_url 去掉 ?fromJob=1：lixiang.com robots `Disallow: /*?*` 让第一轮抓取直接 skipped；adapter 不看 source_url 路径。$md$
 where adapter_name = 'lixiang_campus'
   and source_url = 'https://www.lixiang.com/employ/campus.html?fromJob=1';
