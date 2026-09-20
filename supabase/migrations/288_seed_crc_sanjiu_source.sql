-- 华润三九：接华润集团自建招聘平台（runjob.crc.com.cn），2026-09-20 live 逐条核实。
--
-- 为什么要加这条源：我们原本盯的是华润三九在第三方 ATS（wecruit.hotjob.cn）上的旧租户，
-- 而 999.com.cn 官网的「招聘」早已改指华润集团自建的这个平台。旧租户只剩 1 个岗，
-- 结构性审计连续 7 天报「success + 0 岗」——抓取没报错、两道预检也都放行，
-- **没有任何信号提示「我们盯的入口已经被公司边缘化了」**。这类问题只能靠人去对方官网核。
--
-- live 实测（2026-09-20，adapter 端到端真跑，不是估算）：
--   · 三个渠道各自抓全：社招 127/127、校招 56/56、实习 25/25
--   · 按逐岗 id 去重后 **186 个在招岗**（与平台自报的「186 个热招职位」对得上；
--     208 是三个渠道之和，渠道之间重叠 22 条，别拿它当条数）
--   · 186 条全部带逐岗详情页，**随机抽 15 条（三渠道各 5、覆盖 6 家法人）真浏览器渲染**：
--     15 条全部打开且标题对得上，0 条死链、0 条张冠李戴
--   · 183/186 带 JD 正文 ≥60 字 → 直接算「有效在招」，不需要逐岗富化
--
-- 归属：每条岗位用平台自报的法人名（华润三九医药股份有限公司 / 深圳华润三九医药贸易有限公司 /
--       昆药集团股份有限公司 / 天士力医药集团股份有限公司 …），不统一贴成 sources.company。
--       理由同「hotjob 只认租户自报的 companyName」——把昆药的岗贴成「华润三九」是张冠李戴。
--
-- ⚠️ 原有 3 条 hotjob 旧租户源**不动**（仍 enabled）：它还挂着 1 个岗，属「陈旧」不属「结构性空壳」，
--    要不要停用是单独的决定，不在本次范围内。
--
-- 📌 同一个 adapter 加别的华润品牌 = 只加一行 source、零代码改动：
--    source_url 写 `https://runjob.crc.com.cn/#/homepage?id=<该品牌招聘站 id>` 即可
--    （23 个品牌各自的站 id 来自平台的 searchEmployerBrandList 接口）。
--    平台自报华润置地 1720 个热招职位（我们现在只有 446 个在招），是笔下一步该算的账。
insert into sources (company, source_url, source_type, adapter_name, crawl_method,
                     enabled, segment, industry, industry_group, ownership, regions, notes)
select '华润三九',
       'https://runjob.crc.com.cn/#/homepage?id=2092202183442501634',
       'official', 'crc', 'http', true, 'soe', '医药', '医疗/医药', 'soe', '{CN}',
       '2026-09-20 接华润集团自建平台（官网 999.com.cn 的招聘已改指这里）。adapter 端到端 live：三渠道各自抓全，去重后 186 个在招岗，抽检 15 条详情页全部可打开且标题对得上。旧 hotjob 租户只剩 1 个岗，保留不动。'
where not exists (
  select 1 from sources
   where source_url = 'https://runjob.crc.com.cn/#/homepage?id=2092202183442501634');
