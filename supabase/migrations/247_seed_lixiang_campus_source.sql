-- 247 — 接入理想汽车校招/实习（自建站 www.lixiang.com/employ/campus.html，纯 httpx，零浏览器）
--
-- 存量 sources 里的「理想汽车 Li Auto」只有 li.jobs.feishu.cn（feishu adapter），那是**社招**门户；
-- 校招/实习走的是理想自己的站 + 独立 API 网关 api-web.lixiang.com，与飞书那条完全是两回事，
-- 补这一行才算把理想的校招补齐。
--
-- ── 接入前 live 验过的四件事（2026-09-09）──
-- ① robots.txt 核过：www.lixiang.com/robots.txt 只管该域网页（Disallow: /*?*），
--    本 adapter 只打 api-web.lixiang.com 的 JSON 接口；该域没有真实 robots.txt
--    （请求 /robots.txt 被网关拦截返 `{"code":100012,"msg":"没有接口访问权限"}`，
--    即该路径本身不存在，没有 robots.txt 按惯例视为无限制）。
-- ② 接口零鉴权可达（纯 httpx，不需要 cookie/签名/x-chj-* 头，只保留 Referer 作礼貌性头）：
--    GET .../v1/recruit/school/job/function 返 10 个一级分类，job_count 合计 764；
--    GET .../v1/recruit/school/job-page?job_function_ids=<叶子id> 按分类逐个翻页。
--    ⚠️ hire_mode 参数被服务端忽略（传 1/2/3 结果相同）——校招/实习靠列表自带 job_mode 区分。
-- ③ 逐岗详情页：Playwright 点击列表卡片确认新标签页 URL 为
--    https://www.lixiang.com/employ/detail/{id}.html?jobCode={code}&fromJob=1，
--    冷加载（新 context 直接 goto，不带 referer/session）渲染出标题与正文，过质量门。
-- ④ 端到端跑了一遍 adapter（不是只探接口）：fetch+parse 出 **764 岗，jd_url 764/764 = 100%**，
--    按 10 个一级分类逐渠道核验「实抓 == 自报 job_count」全部为真，fetch_complete=True；
--    全局按 job_id 去重后仍是 764（叶子 id 分区不重叠，无跨类重复）。
--
-- board 由 source_url 里的 "campus" 令牌自动派生（classify_source_board 规则④），
-- 校招+实习混装、按 job_mode 字段区分，与 bytedance_campus 同类写法——不要写 board 列
-- （generated 列，显式赋值会让整个迁移文件回滚，见迁移 241 的教训）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
values (
  '理想汽车 Li Auto',
  'https://www.lixiang.com/employ/campus.html?fromJob=1',
  'official',
  'lixiang_campus',
  'http',
  true,
  'private',
  '汽车',
  '{CN}',
  $md$2026-09-09 接入：理想自建校招/实习站（api-web.lixiang.com 公开接口），与既有的
li.jobs.feishu.cn 社招源互不重叠。live 实测端到端 fetch+parse 出 764 岗，jd_url 100% 覆盖，
按 10 个一级职能分类逐渠道核验抓全，fetch_complete=True。$md$
)
on conflict do nothing;
