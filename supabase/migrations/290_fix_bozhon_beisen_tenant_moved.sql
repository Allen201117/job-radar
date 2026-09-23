-- 博众精工 Bozhon（beisen）连续多天 29 轮全部 failed（GitHub issue #35，watchdog 规则 F）。
--
-- 现象：错误恒为 "beisen: httpx fetch failed for cached route
--       (bozhon.zhiye.com → 'https://bozhon.zhiye.com/social/detail')"。
-- 根因：不是 adapter bug、也不是对方关了招聘——是**租户搬家**。
--       `https://bozhon.zhiye.com/*` 现在任何路径（首页/社招/校招/详情）都返 200，但页面自带
--       `BSGlobal.Message = "企业已暂停招聘"`（北森平台自己给这个租户挂的状态，不是我们猜的）。
--       而官方主页 www.bozhon.com 的「加入我们」页（/about/join）「简历投递入口」按钮真实指向
--       **另一个北森租户** `https://bozhon3.zhiye.com/`——这是对方自己的官方页面在说话，
--       不是我们猜的 slug（遵守「接口返 0/403 不能证明对方没开，要看对方页面自己怎么说」）。
-- 验证：BeisenAdapter 走完整首见租户流程（httpx 抓列表 + 浏览器 render-verify 探测详情路由，
--       零手工干预、零猜参数）对 bozhon3.zhiye.com/social/jobs 真跑一次：
--         reported_total=81, fetch_complete=True, parsed=81, 81/81 行带 jd_url
--         （detail 路由探测结果 https://bozhon3.zhiye.com/social/detail?jobAdId={uuid}）。
--       抽取第一条 jd_url 用无头浏览器真渲染，页面确实是该岗「项目经理（深圳）(J12296)」的
--       完整详情（工作职责/任职资格/立即投递按钮），不是首页或错配页。
update sources
   set source_url = 'https://bozhon3.zhiye.com/social/jobs'
 where source_url = 'https://bozhon.zhiye.com/social/jobs'
   and adapter_name = 'beisen';
