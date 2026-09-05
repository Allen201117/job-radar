-- 232 — seed：四家国有大行里的三家 + 浦发银行 + 中国移动的自建招聘门户（2026-09-05 逐家 live 核实）
--
-- ⚠️ 这批公司此前被判成「国有大行 = 公告制、没有逐岗详情页、建议放弃」——**那个结论是错的**。
-- 误判来源：只在浏览器里点了几下工行首页（首页确实只挂公告），没读列表页 onClick 的路由。
-- 工行/交行的详情是 window.open 打开的，页面上点一下**像没反应**，正是这个假象把人带偏了。
--
-- 每家的验收都按项目红线走过：列表接口 → 逐岗详情接口 → **在真实浏览器里冷加载详情 URL、
-- 确认页面上真有这个岗位的标题和正文**。「列表接口能返数」不算通过。
-- 加源前已核对 sources 表：这 5 家一行都没有，不存在影子源（portal_identity 无冲突）。
--
-- live 数字（2026-09-05，跑仓库里真实 adapter）：
--   浦发 633（社招 343 + 校招 290）/ 工行 2,615（校招 2,567 + 社招 48，已剔 15 个报名截止的）
--   建行 3,799（校招 3,784 + 社招 15，已剔 19 个报名结束的）/ 交行 16（社招；校招官网自报「暂无职位数据」）
--   中国移动 2,205（校招 2,110 + 社招 89 + 实习 6，列表直出全文）
--
-- 农业银行不在本批：接口返回 SM4 密文（响应体加密），需另案处理。
--
-- ⚠️ crawl_method 只接受 'http' / 'playwright' / 'manual'（迁移 211 因写 'browser' 整批回滚过）。
-- ⚠️ 不要写 board 列：它是 GENERATED ALWAYS AS 派生列（迁移 187），显式赋值会让整批回滚。
insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled, notes)
values
  ('浦发银行', 'https://job.spdb.com.cn/socialJob', 'spdb', 'http', '{CN}', 'soe', '银行', true,
   'socialJobJsonList 必须带 Referer（否则 500 Referer error）；pageSize 参数无效恒 10 条/页；'
   '社招校招同一接口靠 recuitType 分（11/12），逐岗 /jobDetail?jobId=&type= 有全文正文。'),
  ('工商银行', 'https://job.icbc.com.cn/pc/index.html', 'icbc', 'http', '{CN}', 'soe', '银行', true,
   'qryPostList / qryPostById 公开接口（body 形如 {"public":{"call_app":"F-TRM"},"private":{…}}）；'
   'postDepict 是 base64→urlencode→HTML 三层包着；列表会夹带报名已截止的岗，adapter 按 enterEndTime 剔除。'),
  ('建设银行', 'https://job3.ccb.com/cn/job/job_list.html', 'ccb', 'http', '{CN}', 'soe', '银行', true,
   'NHR104 列表 / NHR107 详情；**必须先请求 TXCODE=100119 热身会话**否则详情返回「请重新登录」；'
   '本项目 Bot UA 会拿到 HTTP 200 + 空 body（HEAD 又是 200，should_skip 拦不住）故 adapter 覆写了 UA；'
   'jd_url 必须五参数全（planId/planPost/planType/orgId/secondOrgId），少一个前端就 alert 并回退。'),
  ('交通银行', 'https://job.bankcomm.com/#/social', 'bankcomm', 'http', '{CN}', 'soe', '银行', true,
   'querySocietyRecruitInfo / queryPositionDetail；form-urlencoded 单字段 REQ_MESSAGE，'
   '业务参数必须再包一层 params（少了返 200 + JUMPTESTBP9001「系统异常」，极易误读成要登录）。'
   'engageType 3=社招 / 1=校招；2026-09-05 校招 0 条与官网校招页自报「暂无职位数据」一致。'),
  ('中国移动', 'https://job.10086.cn/personal/job/', 'cmcc', 'http', '{CN}', 'soe', '通信', true,
   'searchJobs 公开接口，但 header.digest 要自算：base64(md5(ts+secret)) + ";" + RSA_PKCS1v15(secret, 站点公钥)；'
   '签名错返回 HTTP 200 + code=9999，必须按 code 判成败。列表直出 description/dutyCondition 全文，无需逐岗抓详情。')
on conflict (source_url) do nothing;
