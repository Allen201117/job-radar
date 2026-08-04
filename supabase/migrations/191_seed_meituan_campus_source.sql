-- 191 — seed：美团校园招聘源（2027 届秋招供给基座）
--
-- 背景：我们此前只接了美团社招门户 `zhaopin.meituan.com/web/position`，库里美团校招岗 = 58。
-- 校招在**同一个域、同一个 getJobList 接口**，只是多带一层板块过滤。
--
-- ⚠️ 这个过滤的形状**猜不出来**，2026-08-04 探证记录（「猜 ≠ 验」的又一个样本）：
--   · 猜 jobShareType 1/2/3 是板块开关 → 三个值返回**同一批岗**（首条都是「HRBP（外派巴西）」），
--     只有 totalCount 不同，纯属误导；
--   · 猜 typeCode:["4"] / specialCode:["4"] → total=0；猜 jobType:["1"]（字符串）→ total=None；
--   · 最后在校招页装 XHR 拦截器截获真实请求，才看到 **jobType 是对象数组**：
--     {"jobType":[{"code":"4","subCode":["2"]}],"typeCode":["2"]}
--   传字符串时服务端静默忽略并返回 None，表现得和「校招没岗」一模一样——这正是只靠猜会
--   得出「美团校招抓不到」这个错误结论的原因。
--
-- 校招枚举（GET api/official/job/search/enum?enumType=CAMPUS_HIRING）：父 code=4，
-- 子码 1=应届生 / 2=转正实习 / 6=日常实习。live 实测 68 + 104 + 249 = 合并查 total 421（一致）。
-- adapter 端到端：416 岗（过完中国城市门）全部带 JD 正文、fetch_complete=True，
-- 招聘类型分桶正确（应届生 68 → 校招桶 / 实习 348 → 实习桶）。
-- 详情页 ?jobUnionId={id}&highlightType=campus 已 live 浏览器打开验证。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('美团 Meituan', 'https://zhaopin.meituan.com/web/campus', 'meituan_campus', 'http', '{CN}', 'private', '互联网', true)
on conflict (source_url) do nothing;
