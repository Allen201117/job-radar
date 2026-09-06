# crawler adapter 逐条踩坑笔记

> ⚠️ **优先级：本文是「归档细节」，与 `CLAUDE.md` 冲突时一律以 `CLAUDE.md` 为准。**
> 红线看正文，这里只查数字、来由和个案；正文更新后本文可能滞后，别拿它推翻正文。

> 从 `CLAUDE.md` 的「目录结构」拆出来的**个案细节**，原文照搬未改一字。
> **改 / 接某个 adapter 前，先在这里搜它的条目**；跨 adapter 的通用红线仍留在 CLAUDE.md 正文。
> 新增 adapter 请把它的坑写在这里，不要写回 CLAUDE.md（那边只放会改变所有人行为的规则）。

## adapter 清单与逐条坑

```
crawler/                 # adapters/{base,playwright_base,apple,siemens,baidu,jd,haier,tencent,bytedance,feishu,greenhouse,lever,china_ats,
                         #   meituan,kuaishou,bilibili,pinduoduo,vivo,byd,tencent_music,antgroup,mihoyo}.py
                         #   china_ats.py = 本土通用 ATS（moka / beisen / company_spa；host 从 source_url 动态解析，浏览器拦截 SPA）
                         #   tencent_music/antgroup/mihoyo = 必投清单大厂自建 SPA 门户（2026-07-06 live 验证：均有公开 JSON 接口，
                         #     纯 httpx 零浏览器，社招+校招一次抓全；company_spa 吃不掉——接口不返回 per-job URL，须模板拼已验证详情路由）
                         #   avature.py = Avature SearchJobs 通用层（siemens.py 是它的子类）：offset 翻页，
                         #     **页长各租户不同**（西门子 6 / 欧莱雅 20）故按首页卡片数自动推断；详情链接一律取卡片
                         #     href（各租户路径形态不同，禁止正则猜）；source_url 的服务端地区 facet 必须保留。
                         #     ⚠️ 地区后置过滤分两档：facet 源（DROP_UNKNOWN_LOCATION=False）只丢「能确证在境外」的岗，
                         #     Siemens 靠 search=China 全文收窄不可信故保持「地点存疑即丢」——详见 avature._in_regions。
                         #   gllue.py = Gllue Next.js SSR 通用层（龙湖等自有域）：?page= 1-based 10 条/页，
                         #     正文只在详情页（列表页没有），逐岗抓、走 resolve_detail_cap 由快/重档决定抓不抓。
                         #   cnstaff.py = 聘客 cnstaff 通用层：POST /api/{tenant}/joblist.json（form `jt=0`）零鉴权，
                         #     ⚠️「全部」职类被截断到 20 条 → 必须遍历所有分组×职类取并集按 job_id 去重；
                         #     ⚠️ 正文只能取列表的 job_desc（详情页的「职位详情」区块公开态是空的）。
                         #   midea/cmb/cmbc/gree.py = 必投缺口自建门户（2026-08-27 live，纯 httpx 零浏览器）：
                         #     midea 美的 748（POST 后端 position/list，**form-encoded**，列表自带 postDuties/qualification 全文）
                         #     cmb 招商银行 138（POST job/getList，⚠️ body 必须含 jobTypeIdList/orgIdList 两个空数组，
                         #       少了返 EZPREC0005；returnCode!=SUC0000 要当失败抛）
                         #     cmbc 民生银行 100（POST search.view **必须 form-encoded**；⚠️ 该站对本项目 Bot UA 返 507，
                         #       **必须覆写 user_agent 类属性**——否则 BaseAdapter.should_skip 的 HEAD 预检就把整个源跳过、
                         #       永远抓不到岗；jd_url **必须带 `#`**（前端 useHash）；正文走详情接口
                         #       /portal/rest/careerrecruitment/view/{id}.view?view=careerRecruitmentView，伪 id 返空 data）
                         #     gree 格力 64（GET api/apply/jobs，**property=1 校招/博士 + 2 社招两个板块都要抓**；
                         #       ⚠️ 返回带 HR 真人姓名 PubName，一律忽略不入库；错误入口：gie.gree.com 是子公司、
                         #       recruit.gree.com 是内部登录墙）
                         #   spdb/icbc/ccb/bankcomm/cmcc = 国有大行 + 中国移动自建门户（2026-09-05 live，纯 httpx 零浏览器）。
                         #     ⚠️ **推翻旧结论「国有大行=公告制、没有逐岗详情页」**——那是只点了几下首页、
                         #       没读列表页 onClick 就下的判断。工行/农行/交行的详情走 `window.open`，
                         #       在自动化浏览器里点一下**像没反应**，别再据此判它没有详情页。
                         #     spdb 浦发 633（社343/校290；socialJobJsonList 不带 Referer 直接 500；pageSize 无效恒 10 条/页；
                         #       recuitType 11/12 ↔ 详情 type 1/2 必须对应；closeDt=2100-12-31 是「无截止」哨兵值）
                         #     icbc 工行 2,615（校2567/社48；qryPostList/qryPostById；postDepict 是
                         #       **base64→urlencode→HTML** 三层包；列表夹带报名已截止的岗要按 enterEndTime 剔）
                         #     ccb 建行 3,799（校3784/社15；NHR104/NHR107，**必须先 TXCODE=100119 热身会话**否则详情返
                         #       「请重新登录」；响应不是合法 JSON 要复刻前端 repairJSON；jd_url **必须五参数全**
                         #       planId/planPost/planType/orgId/secondOrgId，少一个前端就 alert+history.go(-1)）
                         #     bankcomm 交行 16（社招；校招 0 与官网自报「暂无职位数据」一致。form-urlencoded 单字段
                         #       REQ_MESSAGE，业务参数**必须再包一层 params**，少了返 200+JUMPTESTBP9001「系统异常」）
                         #     cmcc 中国移动 2,205（校2110/社89/实习6；header.digest 自算
                         #       base64(md5(ts+secret))+";"+RSA_PKCS1v15(secret,站点公钥)，RSA 用标准库手写不加依赖；
                         #       签名错返 **HTTP 200 + code=9999** 必须按 code 判成败。⚠️ 它不在必投清单里）
                         #     ⚠️ **两个「静默 0 产出」的坑**：① 建行对本项目 Bot UA 返 **HTTP 200 + 零字节 body**
                         #       （HEAD 又是 200，should_skip 拦不住）→ 覆写 user_agent + 空 body 当失败抛；
                         #       ② 工行/中国移动对 **HEAD 恒返 403**（换浏览器 UA 也一样，GET/POST 全正常）→
                         #       不覆写 should_skip 就整源被跳过。**接新源必须逐个跑一遍 adapter.should_skip(url)**。
                         #   abchina 农业银行 = **唯一走浏览器的一家**（校招 2,603 岗 / 列表 346 秒，46 个机构；2026-09-05 实测）。
                         #     它不是「没有逐岗详情页」，是**接口响应体加密**：new/getInfo 明文发一把 1024 位 RSA
                         #     公钥做密钥交换，之后 org/* 与 orgPosition/* 的响应体是 hex 密文（页面用 SM4-ECB 解），
                         #     明文只存在于浏览器内存 → 只能 Playwright 读页面渲染好的 React state，不拦接口不解密。
                         #     枚举：`#/{recruitType}` 页的 state.batchCardInfo 出机构 → `#/RecruitmentOrgDetails/{rt}/{orgId}`
                         #       页的 state.posCardInfo 出岗位（recruitType 99=校招 / 100=社招）。
                         #     ⚠️ **必须先 goto 一次首页**把会话建起来，否则 hash 路由只渲染 222 字空壳、一条都抓不到。
                         #     ⚠️ hash 路由是**同文档导航**，换机构必须 `page.reload()`——不然上一家的卡片还在 DOM 里，
                         #       会把上一家的岗位当成这一家的（第一版就是这么只抓到 2 个岗、还自称抓全了）。
                         #     ⚠️ 渲染慢且不均：农银人寿 34 个岗要 >8s 才出来，等太短会得到「0 个岗」这种
                         #       看着正常其实是漏抓的结果 → 轮询到 25s 仍为空**也不能**直接认「这家当期没在招」
                         #       （判据见下面 marker 那条）。**这不是罕见情况**：2026-09-05 一轮 45 家里
                         #       9 家没渲染出来，补一轮重试后 6 家拿到真岗位（34/129/91/189/20/16 = 479 个）。
                         #       所以「补一轮重试」不是保险丝而是主路径，别当成可选优化删掉。
                         #     ⚠️ **列表卡里一个字正文都没有**（posCardInfo 只有岗位名/地点/人数/截止）→ 不补正文
                         #       就是 100% 薄卡、进不了 count_valid_active_jobs，这家在必投健康覆盖里恒为 0
                         #       （2026-09-05 实测线上 2,418 个岗**全部** summary 为 NULL）。正文在逐岗详情页的
                         #       state.posDetails：responsibilities / qualifications / requirements 三段。
                         #       ⚠️ 不要收 posDetails.phone（HR 联系方式，同 gree 忽略 PubName）。
                         #       逐岗约 0.7s，受 _DETAIL_CAP + 墙钟预算双闸，起点按天轮转（预算用完就停的话，
                         #       恒从第 0 个开始会让尾部的岗永远补不到；summary 在 upsert 里空值不覆盖，故能累积）。
                         #       ⚠️ 墙钟预算 15min 是**量出来的**：农行在 enrich shard 1（实测 61/57min），
                         #       而 shard 2 已经 172/148min、2026-09-01 那轮 181min 被 GitHub 取消（超时上限 180）。
                         #       想调大它先去 enrich-crawl 台账看**当期**各片耗时，别照着「今天还有余量」拍。
                         #     ⚠️ jd_url 里的冒号是**字面量**：`#/PositionDetails/:{jobPublishId}`（前端拼串时把
                         #       路由占位符一起拼进去了），删掉它详情页打不开。详情走 window.open，点一下像没反应。
                         #     ⚠️ **「页面没渲染出来」会伪装成「这家没在招」**：线上首轮比本机少 162 个岗
                         #       （2,418 vs 2,580）而 fetch_complete 还是 True。判据改成页面固定文案
                         #       （列表页「招聘机构」/ 机构页「在招岗位」，两页不一样别混用）：有 marker+0 岗
                         #       = 真没在招；没 marker = 没等到 = 漏抓。没等到的机构走完一圈后**补一轮重试**，
                         #       还不行才 fetch_complete=False 并日志点名。单机构页抖一下（ERR_EMPTY_RESPONSE）
                         #       各自 try/except，不许炸掉整轮（否则前面几十家已抓的岗一起丢 + 整源记 failed）。
                         #     诚实边界：社招靠「热招事项」卡枚举机构，当前站点自报「暂无热招事项」故为 0；
                         #       哪天社招开了但站点不出热招事项卡，这里会漏——上线后拿 db-report 复核。
                         #   ⚠️ **这五家 httpx 的共性坑（cn_portal_tls.py）**：本机 macOS 是 LibreSSL + 有 IPv6、
                         #     GitHub runner 是 OpenSSL 3 + 无 IPv6 出口 → **本机全绿、上 CI 四个源全 failed**
                         #     （建行/交行/移动 UNSAFE_LEGACY_RENEGOTIATION_DISABLED、工行 Errno 101）。
                         #     修法=强制 IPv4(local_address=0.0.0.0) + OP_LEGACY_SERVER_CONNECT(0x4)，
                         #     **证书校验保持开启不用 verify=False**。这两条本机永远测不出来，靠单测断言看着。
                         #     📌 接完源必须回读线上 crawl_runs 的 status/error_message，别拿本机跑通当交付。
                         #   ⬆ 2026-08-27 四处「扩现有 adapter」（都不是新 adapter，故无需接线）：
                         #     china_ats.BeisenAdapter 加**老版 SSR CMS 门户**分支（theme2，无 PortalId/无
                         #       GetJobAdPageList，列表页 HTML 直出 xq?jobId= 锚点）→ 中芯国际 563 岗（社293/校248/海外22）。
                         #       ⚠️ 租户是 **smics** 不是 smic（台账猜错 slug 才一直抓不到）；⚠️ 列表锚点带筛选态参数
                         #       c/p/ky，**必须归一只留 jobId+jc**否则 canonical_jd_url 重复；⚠️ 末页判定只能靠
                         #       「页内锚点数=0」（超出末页仍返 200+完整骨架）；⚠️ beisen_routes.json 里 {"cms":true}
                         #       登记过时时必须**把该 host 踢出路由缓存**，否则「首见租户」分支被跳过 → 0 岗+自称抓全。
                         #     jd.py 按 `positionDeptName` 派生子公司 company → 京东科技 209 + 京东物流 629；
                         #     netease.py 按 `productName` 派生 → 网易有道 115 + 网易云音乐 157。
                         #       两者**都不新增 source**（那些岗本就在现有源里，新增源会抢同一行 upsert）；靠
                         #       normalizer 的 `raw.company or company` 覆盖 sources.company。前提=母公司在必投清单里
                         #       是 `%子串%` 匹配，派生子公司后母公司仍覆盖（netease 侧已编成运行时守卫，前提不成立就整体关闭）。
                         #       ⚠️ 只映**清单里逐字存在**的子公司：京东「国际事业部/探索研究院」名字不含「京东」，
                         #       派生反而会掉出 `%京东%` 统计；网易「网易元气」子串会撞上清单里的元气森林（故用精确匹配）。
                         #     phenom.py 加 **POST /widgets**（ddoKey=refineSearch）分支 → DHL 130 岗（租户 DPDHGLOBAL
                         #       的 /api/jobs 恒 500）。选路不看域名：只有「首个请求就失败」才回退 widgets；
                         #       ⚠️ 总数在 `refineSearch.totalHits` 不在 data 里；⚠️ country facet 字面量带后缀
                         #       （"Hong Kong" 返 0，要 "Hong Kong, China"）；⚠️ 根路径按 IP 地理跳转，必须显式走 /global/en。
                         #   iguopin.py = 国聘（国资委官方央企招聘平台）：recom-job 列表 + info 详情公开 API，纯 httpx。
                         #     source_url 约定 https://www.iguopin.com/job?company={检索词}&match={核名词}，一源=一集团。
                         #     ⚠️ match 走 company_name_match 严格核名（token 必须在实体名开头或只隔地名前缀），
                         #     朴素子串会把「北京华晋中通电力」当中通快递（2026-07-26 实测），一入库就是张冠李戴。
                         # run.py / db.py / normalizer.py / robots.py / discovery.py
                         # company_name_match.py = 公司名归属核验纯函数（关键词类源防同名子串张冠李戴，见上）
                         # 缺口漏斗（必投清单补供给主链路，见 docs/superpowers/specs/2026-07-26-must-apply-gap-funnel-design.md）：
                         #   gap_census.py(清单×jobs×sources → 台账 must_apply_gap_attempts + 工作队列)
                         #   entry_finder.py(级联搜索找官方招聘入口，每家最多 2 次、首个可信即停，非扇出)
                         #   platform_fingerprint.py(入口页 → ATS 平台指纹 → 路由 adapter / unknown_spa / anti_bot / login_wall)
                         #   gap_funnel.py(编排 + 验收门：插 disabled 源 → 真抓 → 回读香港库健康岗 ≥1 才 enable，
                         #     否则删源+删本次脏岗；失败按原因退避：平台猜错 30d / 无岗 14d / 反爬·登录墙转人工不再跑)
                         # ops_runs.py = 后台任务每日台账旁路写入（写 ops_runs 表，失败不阻断主任务；运营看板②每日战报数据源）
                         # probe.py = 扩源探活器：批量 live 探活候选源，仅把「真返回岗位」的写进迁移（本机跑 python3 probe.py --all --emit 025）
                         # 企业 logo：fetch_company_logos.py + logo_util.py（海外 CI `company-logos.yml` 每周跑）。
                         #   公司范围 = sources.company ∪ 必投清单品牌短名（校招专区/看板按短名展示，不补进来就只能首字母兜底）；
                         #   三源取最清晰者且都过图片内容嗅探：① DuckDuckGo（干净但收录率低，live 实测 65/205）
                         #   ② 公司官网自有图标 apple-touch-icon/icon//favicon.ico（覆盖率主力 166/205，公司自证、常 180px）
                         #   ③ icon.horse 仅兜底。⚠️ icon.horse 的 fallback 是**按域名首字符生成的灰底字母块**，
                         #   指纹必须 a-z0-9 各取一遍（旧实现只取 2 个 → 303/538 张假 logo 入库）；
                         #   `--repair-placeholders` 复检存量（命中占位指纹 或 同图跨多域名出现 = 假 logo）并重抓。
                         #   域名来自 logo_util.COMPANY_DOMAIN_OVERRIDES（每条须 live 核验官网 title 自证，核验不过一律不收）。
                         # 洞察供给：insight_backlog.py(T2 Wikidata+EDGAR+巨潮 / T3 多维查询包 drain：**默认 3 主题** 年终奖/加班文化/晋升发展→各维度（2026-08-27 由 5 砍到 3 控成本：砍掉的「面试难度」其维度 hiring 已由 T1 派生免费供给、「实习体验」与加班文化同属 culture 重复；五个主题都还在 T3_TOPIC_CATALOG 里，env `INSIGHT_T3_TOPICS` 可随时调回）；支持 --company 单公司现查；EDGAR 财报员工数会覆盖 headcount_band) / insight_engine.py(接地→判官→共识) / wikidata.py / official_edgar.py(SEC 美股上市+业绩 XBRL companyfacts) / official_cninfo.py(巨潮 A股,默认关需 INSIGHT_CNINFO_ENABLED；2026-07-02 live 验过 stockList 结构与比亚迪/顺丰匹配，但 repo Variable 仍需有效 GitHub 凭据启用) / insight_sweep.py(过期下架)
                         # geo.py / sponsorship.py = country_code/job_scope/地区过滤 + visa/sponsorship 信号派生
                         # search_router.py = T3 多源搜索路由：search_{bocha,tavily,serper,qianfan} provider + search_budget(每源日顶 search_usage 表)；配哪个 key 用哪个、未配跳过、多源并取喂≥2 publisher 共识门
```

## 必投清单口径（`lib/must-apply-list.ts` / `.json`）

```
                         # must-apply-list（北极星指标口径：必投清单已多行业化——11 行业 × 各 30 家，2026-07-14。
                         #   数据本体在 lib/must-apply-list.json（行业键与 lib/company-industry.js 的 INDUSTRY_CATEGORIES 同名同序），
                         #   TS 与 crawler/must_apply.py 共读同一份，杜绝两端漂移；改清单=改口径。
                         #   用户行业（user_preferences.target_industries 经 canonicalizeUserIndustry 归一）决定看哪份清单：
                         #   resolveMustApplyIndustries 空/归一不出 → 兜底「互联网/科技」。看板北极星只按「活跃行业」
                         #   （有≥1 注册用户的行业 ∪ 互联网/科技）判健康、取最差行业 band；无用户行业 = 储备清单，
                         #   只展示不拖红。爬虫探活倾斜吃全行业并集（must_apply.patterns()）；清单里库内没有的公司由
                         #   crawler/targets_must_apply.json 喂给每日自动扩源（plan_targets 梯队：用户点名 > 必投缺口 > 科技/消费 > 其余））
```

## supabase/migrations 历史脉络

```
supabase/migrations/     # 001_init → 002_rls → … → 007_candidate_profile_summaries
                         # → 008_discovery_run_diagnostics → 009_discovery_async_runs → 010_seed_spa_sources
                         # → 011_seed_foreign_ats_sources → 012_seed_apple_china_source
                         # → 013_career_insights（模块 B 5 表 + RLS）→ 014_seed_career_insights（四维种子草稿）
                         # → 015_verify_experience_sources（experience 真实来源核验）
                         # → 016_rewrite_culture_and_experience_copy（去「避坑」+ 9 条 experience 正文改通俗）
                         # → …（前缀递增，详见目录）→ 158_admin_health_snapshot → 159_admin_ops_dashboard（ops_runs 台账表 + 运营看板聚合函数）→ 165_insight_enrich_now_and_hiring_monthly
                         # → 184_company_logos → 185_must_apply_gap_attempts（必投缺口漏斗台账）
                         # → 166_insight_submissions → 167_overseas_prefs → 168_sources_regions → 169_seed_overseas_regions → 172_user_pref_experience_stage（求职阶段字段）
```
