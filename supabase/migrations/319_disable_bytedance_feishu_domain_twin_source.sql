-- 319 — 停用「抖音」这条飞书源：它是字节跳动官网社招门户挂在飞书域名上的另一个入口（2026-10-11 查实，创始人同日同意处置）
--
-- 现象：sources 里 company='抖音'、adapter_name='feishu'、source_url='https://bytedance.jobs.feishu.cn/index/position'
--   的源（2026-09-26 自动扩源浏览器道插入，notes「auto_discover: live探活 20 岗」）一直在出岗，香港库该域名下
--   8,351 个 active 岗全挂「抖音」；同一批岗在「字节跳动」名下（jobs.bytedance.com/experienced）另有一份。
-- live + 真库核验（全部只读，2026-10-11）：
--   · 同一个门户两个域名：bytedance.jobs.feishu.cn/society 与 jobs.bytedance.com/experienced 页面自报同一个
--     website_info.id、path=society、tenant_name=ByteDance、keywords「字节跳动招聘官网、字节跳动招聘、字节跳动社招」。
--     门户自报的是字节跳动，不是抖音。
--   · 按岗位编号（jd_url 里 /position/{编号}/detail）全量对：抖音 active 8,351 行里 7,946 行在字节跳动 active 行里有同编号；
--     这 7,946 对发布日 7,946 相同、正文 7,943 逐字相同、地点 7,944 相同。两边链接域名不同，canonical 去重拦不住。
--   · 飞书域名上的社招链接在浏览器里打不开：前端把 /society/ 改写成 /experienced/，飞书域名没有这个路径 → 「Not Found」
--     （curl 是 200，SSR 壳）。实开 3 条全是；新岗巡检近 14 轮渲染过该域名 1,962 条，1,962 条判死；
--     库里该域名 active 行被巡检过还活着的是 0。同编号在 jobs.bytedance.com 上正常渲染。
--   · 死循环：抓进来 → 新岗巡检判死 → purge 立墓碑 → 列表里还在，下一轮又当新岗插入。两周墓碑 1,226 行、复活计数 6,145；
--     新岗巡检近 14 轮名额的 47% 花在它身上。
--   · 这条源每轮撞 8,000 条上限（门户实有 1 万以上），抓不全，list-absence 从不清它。
--   · 对不上编号的 405 行：约 274 行是两边都已下线、一直挂着的；约 125 行是官网上在招但「字节跳动」那条源取不到的
--     （官网 adapter 取列表不带 website-path 头，另行核实）；6 行是官网那一侧当天刚下架。
-- 根因：候选名「抖音」+ slug bytedance 来自 LLM 喂料；discover_domestic.feishu_probe 的核名门在门户标题对不上时
--   认「岗位标题含公司名」，字节的岗位标题带业务线名（「…-抖音生活服务」）→ 放行。同一提交已改成只认门户自报。
-- 后果：同一个岗在 /jobs 出两张卡，其中「抖音」那张点开是 Not Found；首页岗位库计数多算 8,351（1.9%）；
--   北京社招在招岗里 10.1% 是它。
--
-- 处置：停用这条源（保留行可回滚）。存量 active 行走 remove-jobs-by-url-prefix.yml 标 removed（可逆）：
--   url_prefix=https://bytedance.jobs.feishu.cn/  company=抖音  不限孪生（整批链接都打不开）。
--   「抖音」画像已在迁移 317 并入字节跳动，本迁移不动画像。
-- Idempotent：where 带 enabled，重复执行无副作用。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-11 停用：这是字节跳动官网社招门户挂在飞书域名上的另一个入口，不是「抖音」的门户。与 jobs.bytedance.com/experienced 页面自报同一个 website_info.id、tenant_name=ByteDance、keywords「字节跳动招聘官网」；8,351 个 active 岗里 7,946 个与「字节跳动」名下岗位编号相同（发布日全同、正文 7,943 逐字相同）。飞书域名上的社招详情链接在浏览器里是 Not Found（前端把 /society/ 改写成 /experienced/），新岗巡检渲染过 1,962 条全部判死。字节跳动的岗由 jobs.bytedance.com 两条源提供。别重新启用：要启用得先解决链接打不开和 8,000 条上限。$md$
 where source_url = 'https://bytedance.jobs.feishu.cn/index/position'
   and company = '抖音'
   and enabled;
