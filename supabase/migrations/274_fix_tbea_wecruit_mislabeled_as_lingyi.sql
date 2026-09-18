-- 274 — 纠正张冠李戴：wecruit 租户 SU612f55eebef57c0616450aa2 是「特变电工」不是「领益智造」（2026-09-18 查实）
--
-- 现象：香港库里「领益智造 Lingyi」「领益智造 Lingyi 校招」「领益智造 Lingyi 实习」名下 1,903 个 active 岗
--   （社招 1,216 / 校招 392 / 实习 295），标题「装配工（合容电气生产部）」「国际业务部部长（云高）」
--   「南京公司监控系统开发工程师」… 与 company='新疆特变电工集团'（tbea.hotjob.cn，wt 老版）逐字相同：
--   1,905 个 active 里 1,903 个标题、1,706 个「标题+城市」在特变电工名下都能找到；合容电气 / 自控 / 云高 /
--   南京公司都是特变电工子公司。
-- 根因：086/088/089（2026-06-09）按 probe 探活结果 seed 时，把这个 suiteKey 记成了领益智造（同 248 精雕/京东那次：
--   只看探活出岗、没核租户自报的公司名）。live 核验：
--   POST https://wecruit.hotjob.cn/wecruit/suite/config/SU612f55eebef57c0616450aa2 返回
--   companyName = 特变电工股份有限公司，keywords = 特变电工股份有限公司社会招聘/校园招聘/招聘官网…，
--   suitOrgInfoPOs = 特变总部 / 沈变公司 / 衡变公司 / 特变电工电气装备集团 / 新变厂 —— 与领益智造无任何关系。
-- 后果：按「领益智造」筛出来的是特变电工的变压器/煤化工岗（归属准确性红线）。
-- 处置：三条源保留、改公司名（岗位真实、jd_url 稳定，只是挂错了名）。基名与 wt 那条源一致（新疆特变电工集团），
--   校招/实习后缀沿用 088/089 的写法。jobs 热表在香港库：`company` 在 jobs_db._UPDATE_COLS 里，下一轮列表重抓会按
--   新 sources.company 自愈；存量立即纠正走 `rename-job-company.yml`（crawler/rename_job_company.py，按 jd_url 前缀点名）。
-- ⚠️ 两个门户（tbea wt 2,271 岗 / wecruit 1,905 岗）同时在招、逐岗详情都活，canonical 不同、唯一索引拦不住重复：
--   1,720 个 wt 岗在 wecruit 里有同「标题+城市」行。哪个门户是官方主入口未定（tbea.com/zpxx 对本项目 UA 返 403），
--   本迁移不停用任何一条；合并策略另议。
-- Idempotent：where 带旧公司名，重复执行无副作用。

update sources
   set company = case
                   when company = '领益智造 Lingyi'      then '新疆特变电工集团'
                   when company = '领益智造 Lingyi 校招' then '新疆特变电工集团 校招'
                   when company = '领益智造 Lingyi 实习' then '新疆特变电工集团 实习'
                 end,
       industry = '电气',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-18 公司名由「领益智造 Lingyi」纠正为「新疆特变电工集团」：suite/config 接口自报 companyName=特变电工股份有限公司（keywords 特变电工招聘官网、组织树 特变总部/沈变/衡变），与领益智造无关；岗位标题与 tbea.hotjob.cn（wt）源逐字相同。$md$
 where source_url like 'https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/%'
   and company in ('领益智造 Lingyi', '领益智造 Lingyi 校招', '领益智造 Lingyi 实习');
