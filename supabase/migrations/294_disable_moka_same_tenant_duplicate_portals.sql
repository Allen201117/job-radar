-- 294 — 停用 3 条 Moka「同租户同板块」重复源：它们抓回来的在招岗几乎全部已由同公司另一条源抓到（2026-09-23 查实）
--
-- 现象：香港库 moka 在招 46,793 行、只有 46,494 个不同的岗位 id（#/job/<uuid>）——299 个岗各存了两行，
--   用户按公司看会刷到两张一模一样的卡。都 status=success，没有任何失败信号。
-- 为什么看门狗规则 H 没报：它的门户身份是「租户/门户 id」，只认同一个 id 的两种写法；这 3 组是
--   **同一租户的两个不同门户**（或不带 id 的别名 campus_apply/{租户}），岗位池却大面积重合。
-- 核实方式（全集，不是抽样）：
--   ① sources 里 419 条 moka 源逐条带 cookie 跟随跳转，读页面自报的 siteId / type / siteName；
--   ② 对「同租户同板块 ≥2 条 enabled」的 7 组，按岗位 id 在香港库逐组对拍在招集合（crawl_runs 两边近 4 晚都是
--      reported_total = 抓到数、coverage_complete = true，集合可信）。
--
--   停用                                                 保留                                              停用那条的在招岗
--   知乎    campus_apply/zhihu/3818  「系统默认校园招聘门户」   campus_apply/zhihu → 当期门户 68321「新版校园招聘官网」   3/3 在保留门户下有
--   第四范式 apply/4paradigm/5072      「系统默认社会招聘门户」   social-recruitment/4paradigm/102013「第四范式社会招聘门户网站」 3/3
--   作业帮  social-recruitment/zuoyebang/150144「社会招聘」    social-recruitment/zuoyebang/41328「作业帮社招官网」    近 30h 抓到的 198 个里 195 个
--
--   ⚠️ 作业帮这条不是零损失：150144 另有 3 个岗保留门户下没有（实习生 / 郑州小学辅导老师 / 长沙AC辅导主管），
--      按岗位 id 和标题都对不上。取舍同迁移 275（特变电工老门户重合 76% 仍停用）：留着它 = 195 张重复卡片天天在，
--      停掉 = 今后只在它上面发的岗（历史比例 3/198）抓不到。那 3 个岗本身不会消失，见下 ③。
-- 其余 4 组不是重复，一条不动：东方财富 57971（2025届门户，2 岗里 1 个与当期门户重合）、完美世界 140155（2026届门户，1 岗 0 重合）、
--   万科 37550 vs 万物云 147055（同租户两家公司，0 重合）、天合光能 apply/39871（页面自称「旧版招聘门户（已下线，不要选）」但 3 岗 0 重合）。
-- 处置：
--   ① 停用（保留行可回滚），where 带 id + 当前 url + enabled，重复执行无副作用。
--   ② 停用只挡住「以后」，库里已有的 active 行不会自己消失：实证 apply/tesla/46129 早已停用，名下 24 个岗
--      19 天没再被看到仍是 active，其中 5 个与 social-recruitment/tesla/46129 重复。
--   ③ 香港库重复行走 remove-jobs-by-url-prefix.yml 的 only_twins_under：**只标在保留门户下有在招孪生行的**
--      （作业帮 287 / 知乎 3 / 第四范式 3 / 特斯拉 5），只在停用门户出现的岗不动（规则 H 的处置口径）。
--   ④ 堵回流：crawler/auto_discover.py 的 moka_tenant_key 让扩源按「租户 + 板块」去重，不再按 URL 字面。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-23 停用：与 campus_apply/zhihu（当期门户 68321）同租户同板块，本门户 3818 的 3 个在招岗全部在那边也有，重复入库。$md$
 where id = 'aef4afca-aa4d-4c29-a5ab-6088e801f4b3'
   and source_url = 'https://app.mokahr.com/campus_apply/zhihu/3818'
   and enabled;

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-23 停用：旧写法 apply/ 的「系统默认社会招聘门户」5072，3 个在招岗全部在 social-recruitment/4paradigm/102013 下也有，重复入库。$md$
 where id = '5106f4fe-6619-4eba-95d0-459d4bfb5578'
   and source_url = 'https://app.mokahr.com/apply/4paradigm/5072'
   and enabled;

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-23 停用：与 social-recruitment/zuoyebang/41328（作业帮社招官网）同租户同板块，本门户近 30h 的 198 个在招岗里 195 个那边也有，重复入库；另 3 个只在本门户（实习生 / 郑州小学辅导老师 / 长沙AC辅导主管）。$md$
 where id = 'cada1118-e98b-45d9-94e2-0c7a1554ff85'
   and source_url = 'https://app.mokahr.com/social-recruitment/zuoyebang/150144'
   and enabled;
