-- 221 — 华为校园招聘接入（2027 届，应届生 69 + 实习生 31 = 100 岗）
--
-- 背景：库里只有华为社招（career.huawei.com/reccampportal/…）。此前判「华为没开校招」——**结论是错的**。
-- 老门户 reccampportal 传 jobType=2 确实返 totalRows=0，但华为校招 2026 年已搬到新站
-- career.huawei.com/cn/campus-recruitment，走另一个网关；官网首页 2026-08-15 就挂着
-- 「华为2027届应届生招聘启动」，招聘对象、宣讲会日程一应俱全。
-- 判「对方开没开」的唯一依据是对方页面自己怎么说，不是我们某个接口的返回值。
--
-- live 2026-09-04：应届生 69 + 实习生 31 = 100 岗，fetch_complete=True，
-- 100/100 带真实正文（走「岗位意向」接口取每个方向的职责/要求），地点 100/100 非空。
--
-- jd_url = https://career.huawei.com/cn/job-details?advertisementId={advertisementId}
-- ⚠️ 该路由是**点击卡片时拦 window.open 抓到的**（点击不改变当前页 URL），不是猜的；
--    用 advertisementId，不是同行里长得很像的 advertisementsIntegrationId / jobId。
--
-- Idempotent: guarded by source_url。
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'；写 'browser' 会整批回滚（迁移 211 踩过）。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华为', 'https://career.huawei.com/cn/campus-recruitment', 'official', 'huawei_campus', 'http',
       'private', '互联网·通信',
       '华为校园招聘（career.huawei.com 新站，与社招 reccampportal 是两套系统、两个网关）。'
       'live 2026-09-04：2027 届应届生 69 + 实习生 31 = 100 岗，全部带正文。'
       '⚠️ 网关必须带 x-hw-id / x-jalor-tenantalias / x-language / x-alb-gray / x-referer 五个头，'
       '缺了返 HTTP 200 但 data 为空，极易被误判成「华为没开校招」。'
where not exists (
  select 1 from sources where source_url = 'https://career.huawei.com/cn/campus-recruitment');
