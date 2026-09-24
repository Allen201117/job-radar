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
                         #   crc.py = 华润集团自建招聘平台 runjob.crc.com.cn（2026-09-20 live，纯 httpx 零浏览器零签名）。
                         #     一行 source = 一个品牌招聘站：source_url 写 `#/homepage?id=<品牌站 id>`，
                         #     加别的华润品牌零代码（23 个品牌站 id 来自 searchEmployerBrandList）。
                         #     网关 POST ssdp.crc.com.cn/ssdp/sys/rf/?ssdp=<base64 鉴权串>，body 也是 base64 包的 JSON，
                         #     `Sign=NO_SIGN`+`User_Token` 空 = 匿名；列表行自带 rmJobDuty/rmJobRqmt 全文，无需逐岗富化。
                         #     ⚠️ **Time_Stamp 必须是北京时间、误差几分钟内**，否则返 HTTP 200 + **零字节 body**
                         #       （实测：北京时间当下 ✅26001B / 同刻 UTC ❌0B / -5min ✅ / -30min ❌ / -2h ❌）。
                         #       runner 跑 UTC，`datetime.now()` 直接就是错的 —— 完美的「绿灯零产出」配方，
                         #       所以 adapter 显式钉 ZoneInfo("Asia/Shanghai")，单测有源码级断言守着。
                         #     ⚠️ 四个自定义头缺一不可：homepageconfigid / languageindex / rmapplyid / authorization，
                         #       少带同样是 200 + 空 body（同华为新网关那一类）。空 body 一律抛错记 failed，不许安静返 0。
                         #     ⚠️ **逐岗详情页的 id 是 `blockRowId` 不是 `id`**，两者只差 1（…849 vs …850）；
                         #       用 `id` 打开渲染成「职位已下架」→ 用错字段 = 全源死链且会被巡检判撤岗后删库。
                         #     ⚠️ 三个渠道 recruitTypeCode A01 社招 / A02 校招 / A04 实习**会互相重叠**：
                         #       华润三九 127+56+25=208，按 blockRowId 去重后只有 186（= 品牌卡自报的 186）。
                         #       抓全率逐渠道判，绝不拿三者之和当条数（同 huawei/xiaohongshu，本项目栽过两次）。
                         #     归属：每条岗位用平台自报的 companyDescr（昆药/天士力等子公司各归各名），不贴 sources.company。
                         #     ⚠️ sources.board 生成列把它算成 social（URL 无板块线索），而它实际三渠道都抓；
                         #       华润三九不在必投清单故暂无影响，加华润置地（必投，平台自报 1720 岗）前先看这条。
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
                         #   cib 兴业银行（2026-09-23）= 第二家走浏览器的银行，1574 岗（社招/校招/实习同一列表）。
                         #     不是反爬：门户建在兴业的 JUP 前端框架上，**每个请求都带现场签算的两个头**，裸请求一律 500：
                         #       X-VALID-TOKEN = SM3-HMAC(按键排序的请求体, signKey)；
                         #       X-AntiReplay-Token = SM4(访问令牌|时间戳尾数+6位随机数|时间戳, sm4Key)；
                         #       会话密钥来自握手：POST /api/authPrehandler 发 SM2 公钥+salt → POST /api/cfn/sysToken
                         #       用随机串换回 SM4 加密的 tokenKey/signKey。
                         #     🔎 **性质判定（读前端源码 index.*.js / chunk-libs.*.js 逐段核过）**：输入只有请求体、时间戳、
                         #       随机数、服务端下发的会话密钥 → 请求完整性签名 + 防重放；**没有滑块、没有设备指纹**
                         #       （canvas 只用于渲染 PDF；无 toDataURL / webdriver / 插件枚举 / AudioContext）、
                         #       **没有行为校验**；图形验证码只在登录框（手机号/邮箱登录）里，看岗位用不到；
                         #       错误码 915021 needRecheck 是银行系统的「复核」（操作要另一人审批，旁边还有 915501
                         #       「等待复核」），不是人机校验。→ 按「前端公开算法的普通接口参数」处理，可接。
                         #     抓法：不在 Python 里复刻国密（要引新加密依赖），打开门户后调用页面自己的
                         #       `document.querySelector('#app').__vue__.jup__ajax('recruitpositionportalPage', …)`，
                         #       签名由页面代码完成；一次可取 200 条，行内自带职责+任职要求全文，不用逐岗补正文。
                         #     ⚠️ 等 `jup__ajax` 就绪（wait_for_function），**不等 networkidle**；接管 dialog。
                         #     ⚠️ 详情是 hash 路由 `…?recruitType={SR|CR|TR}#/positionDetails/{positionId}`，真 id 匿名可看、
                         #       假 id 只剩页头页脚空壳；日后接浏览器巡检**必须 reload**（同文档导航留上一个岗）。
                         #     ⚠️ 截止时间「长期」站点写 3000-01-01 哨兵值，当成无截止；约 20% 岗发布于 2023~2024 年、
                         #       站点仍标「发布中 + 长期」，是银行常设岗，按站点口径收。
                         #   citicbank 中信银行（2026-09-23）：job.citicbank.com 自建，POST recruitQuery（零鉴权，15 条/页，
                         #     顶层 pageCount 实为**总条数**不是总页数）+ 静态详情 /static/positionDetail_{ID}_{01|02}.html；
                         #     假 id 返 404「系统错误」。社招/校招两渠道 id 不重叠，拆两条源（校招 URL 带 #/campus 让 board 判 campus）。
                         #     ⚠️ 必投台账曾把它的入口记成 careers.citics.com —— 那是**中信证券**。
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
                         #   ⬆ 2026-09-18 BeisenAdapter 再加**卡片式 CMS 门户**分支（_httpx_fetch_cards，纯 httpx）
                         #     → 方太集团 fotile.zhiye.com 231 岗（社招197/校招28/实习6），登记 {"cards":true}，迁移 272。
                         #     ⚠️ **不是新网关**：同 cmsportal/<租户数字 id> 体系、同 ?PageIndex= 翻页、同 ?jobId= 详情身份、
                         #       同 X-RateLimit-*-second:50 按 IP 限流。差的只有列表卡模板——标题在 <dd>、<a> 体内还塞着
                         #       地点｜部门｜日期 和整段 JD。响应头 X-PAAS-DEBUG-GENERAL-SITE 看着像代际标记但**不能当判据**：
                         #       方太与京东方同为 web-custom-new-zhiye-com，而京东方是新版 SPA；它区分的是托管档位。
                         #     ⚠️ 老代码对它是**两种静默失败**：theme2 解析器退回「整个 <a> 文本当标题」被 3~120 字门丢光（0 行）；
                         #       浏览器 _BEISEN_SSR_ANCHOR_JS 的 name.length<=60 门同理 → raise「SSR 列表页无 jobId/adId 锚点」。
                         #       更坏的是 **JD 短的卡片会越过长度门**，把「标题+地点+部门+日期+整段JD」当标题悄悄入库
                         #       （方太 /intern 6 行里 3 行这么进来过，还是 success）→ 已加「行内有 <dd> 就弃权」挡死。
                         #     ⚠️ jd_url 是 /job_show?jobId= **不带板块标记** → 招聘类别只能靠**板块路径**声明成 job_type
                         #       （/campus→校园招聘 /intern→实习 /social→社会招聘，实习优先于校招），否则 recruitmentCategory
                         #       只能兜底成社招。实测 231/231 落对（校招28/实习6/社招197）。
                         #     ⚠️ 列表值会被服务端按宽度截断：标题 11/231、地点 51/231（`浙江省-宁波市-...`/`内蒙古自治区,...`/
                         #       `广西壮族自治区...`/`新疆维吾尔自治...`）。title/location **不在** _PRESERVE_IF_EMPTY 里，
                         #       所以「残缺行」即使 CRAWL_DETAIL_CAP=0 也要补详情，否则快车道与夜间富化天天互刷。
                         #       反过来列表已给全的 location **不许**被详情覆盖（多地岗详情会列全部地点，又成两个值）。
                         #       两档对拍实测 title/location/posted_at/job_type 231 行逐行相等、0 处不一致。
                         #     ⚠️ summary 刻意**只从详情页写**（同 theme2）：列表卡那段 JD 只有职责、没有任职要求，
                         #       写进去会让快车道用半截正文盖掉富化的完整正文（summary 是空值才受保护）。首抓当天薄卡是设计。
                         #       详情段序换成【任职要求】在前：存库 summary 只有 400 字（clean_summary 默认），职责段动辄几百字。
                         #     📌 全集回归（2026-09-18）：358 个 enabled beisen 源新旧两版逐源对拍，岗位合计都是 89,653，
                         #       分支归属/报错数/reported_total/fetch_complete 全 0 变化。**这一形态在库里只有方太一家**——
                         #       510 条存量 beisen 源 + 300 个 distinct host × /social /campus /intern（900 次探测）零命中。
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
                         #   sf_express_campus.py = 顺丰**校招**门户 crs-pub.sf-express.com（2026-09-18 接入，纯 httpx）。
                         #     ⚠️ 与社招 sf_express.py **两套系统**：社招 hr.sf-express.com/SearchJob.do（id 是
                         #       `id,positionType` 二元组），校招 crs-pub /api/web/position/query（id 是单个自增整数），
                         #       id 空间不相干、jd_url 模板不同，共用 adapter 只会互相污染。
                         #     接口怎么挖出来的：前端是 Vue2 SPA，接口名**不在主包里**——路由表在
                         #       /cr/static/js/app.<hash>.js（`path:"/postDetail/:id"`），API 前缀在 /static/js/config.js
                         #       （`__APP_ENV__API_BASE_URL__:"/api"`），真正的 `web/position/query` / `findById/{id}` /
                         #       `queryDict/{type}` 写在 manifest chunk map 指向的**懒加载分块**里。
                         #     live 数字：total=120（全部 seasonType=2 秋季校招），parse 120/120，正文 120/120，
                         #       jd_url 唯一 120/120，fetch_complete=True。pageNum + pageSize **都真实生效**
                         #       （page1∩page2=0、三页并集=120；pageSize 10/50/100/200 如实回显）。
                         #     jd_url = `https://crs-pub.sf-express.com/#/postDetail/{id}` —— 站点自己拼的
                         #       （列表卡片模板里就是 `href:"#/postDetail/"+a.id`），不是猜的；hash 路由，canonical 原样不碰。
                         #     ⚠️ summary 段序是量出来的：届别硬信号「2027届本科及以上学历毕业生」只写在
                         #       `jobRequirement` 首句，而 grad_class 只看截断后的前 400 字 →【任职要求】必须排在
                         #       【岗位职责】前面（实测职责在前 118/120、要求在前 120/120）。
                         #     判死（ENRICH_REGISTRY）：详情 `findById/{id}` 的 `status`（**列表行里没有这个字段**），
                         #       双条件——「HTTP 500 且 body 含『找不到职位信息』」或「HTTP 200 且 positionName 非空
                         #       且 status ∈ {0,2}」。全集对拍：列表内 120/120 全是 status=1 零反例，
                         #       列表外 84 个 id 全是 status=2(73)/0(9)/500(2)，无一 status=1。
                         #     诚实边界：实习通道 `staffGroup=C` 与 `positionType=consulting` / `specialCategory=1`
                         #       当日实测均 total=0 ——「现在返 0」不等于「顺丰没有实习」（见 CLAUDE.md 那条碑）。
                         #   midea_campus.py = 美的**校招**门户 careers.midea.com 自建 iHR（2026-09-18 接入，纯 httpx）。
                         #     ⚠️ 与社招 midea.py 两套 host：社招 recruit.midea.com（form-encoded），
                         #       校招 careers.midea.com（JSON，**先取在跑招聘项目、再逐项目取岗位**）。
                         #     🚩 **翻页参数是 `pageIndex`，`pageNum` 会被静默忽略**：HTTP 200、total 正确、
                         #       `info.pageIndex` 恒为 1、每页回同一批 20 条 —— 按 pageNum 翻 8 页拿回 160 行、
                         #       去重后只有 20 个 positionId（total=152）。`pageSize` 被服务端**硬顶 20**
                         #       （请求 50/100/200 一律回 20），小于 20 才生效。
                         #       → 末页判据必须是「这一页有没有带来新 positionId」，用「本页条数 < pageSize」会无限翻同一页。
                         #     ⚠️ 项目是**动态**的（同事凌晨看到 3 个、几小时后 4 个），不许硬编码 projectRuleId；
                         #       完整性**逐项目判**，不拿各项目 total 之和当分母（渠道重叠会让和式判据永久为假）。
                         #     live 数字：4 个在跑项目合计 total=535（日常实习 152 / 校企合作实习 169 /
                         #       2027届美的星校招 148 / 2027应届博士校招 66，positionId 互不重叠），parse 535/535，
                         #       正文 535/535（列表行的 projectPositionDto 自带全文，零薄卡），fetch_complete=True。
                         #     jd_url = `…/schoolOut/post/details?positionId={positionId}` —— 站点自己
                         #       `window.open(router.resolve({name:"postDetails",query:{positionId}}).href)`；
                         #       ⚠️ 用 positionId **不是** projectPositionId（后者是岗位模板 id，取错就是坏链）。
                         #     ⚠️ **不许把 `numberOfSessions` 写进 summary**：两个实习通道它是 2026，而项目自报的
                         #       毕业时间窗是 2026-01-01~2028-12-31 → 写进去会把 26/27/28 届通吃的实习岗全标成 2026 届。
                         #       届别只从项目名里的硬信号来（2027届/2027应届 → 214 个岗抽到 2027），实习通道留白 321。
                         #     判死（ENRICH_REGISTRY）：详情 `position/details`，**不能按 code 判**——不存在的 id
                         #       也返 `code="0"`，区别只在 `data` 是不是 null。双条件：「code=0 且 data 键存在且为 null」
                         #       或「code=0 且 data 是对象、projectPositionName 非空、publishStatus=2」。
                         #       对拍：在招 535/535 全是 publishStatus=1 零反例；变异 id 120 个里 89 个返 data=null。
                         #       🚩 诚实边界：「已下架仍返记录但 publishStatus=2」的反向证据**只有 1 例**
                         #       （美的没有公开历史岗位列表），真实撤岗若走别的形态这里会漏判（安全方向），
                         #       等库里的岗自然过期后用 job_closures 复核。
                         #   ⚠️ **这两家的详情页都不随撤岗消失**（2026-09-18 Playwright 真渲染，正反各验）：
                         #     顺丰 status=2 的 2100 与 status=0 的 2267、美的 publishStatus=2 的
                         #     `8a5ea6d6…232160`，全都渲染出完整岗位名 + 正文 +「申请职位 / 立即投递」按钮
                         #     （620 / 846 / 576 字），跟在招岗肉眼无差；只有 id **彻底不存在**时才是空壳
                         #     （顺丰 312 字 / 美的 110 字）。同 CLAUDE.md 里浦发那条边界。两个后果：
                         #     ① 判死只能读接口字段（status / publishStatus），`audit_dead_links` 的
                         #        DEAD_MARKERS 对这两个源一条都匹配不上 → 必须走 httpx 的 ENRICH_REGISTRY
                         #        + liveness-sweep，别指望浏览器巡检兜底；
                         #     ② 库里一旦留着撤岗，用户点进去看到的是个「可以投递」的完整页面、
                         #        察觉不到已经关了 → 这两个源的 sweep 覆盖率比一般源更要紧。
                         #   ⚠️ 这两家的后置地区门刻意用「只丢能确证在范围外的岗」（同 avature._in_regions 的 facet 分支）：
                         #     单租户中国区校招门户，host 即地区保证，`derive_country_code` 返回 None 是「证据不足」
                         #     不是「证据相反」。严格判据实测各误伤 1 个真·在招岗（顺丰 id=2328 demandCity 是空串；
                         #     美的「生产计划专员」在**昆山市**——江苏的县级市，词表按设计只收到地级市）。
                         #     双向核过：放宽后 A→B 各 1、B→A 各 0，两家全集共 655 行里**没有一行**能确证在 CN 之外；
                         #     台湾红线不受影响（台北市识别得出 TW → 仍走严格分支被丢）。
                         #   duoyi.py = 多益网络招聘官网 xz.duoyi.com（校招）/ sz.duoyi.com（社招），自建 Vue SPA，纯 httpx
                         #     （2026-09-18 接入）。两个 host 是**同一套后端**：`recruit` 参数选渠道（10 校招 / 20 社招），
                         #     host 只是皮肤（xz 传 recruit=20 照样返社招全集）→ 渠道**只认 source_url 的 host 前缀**，
                         #     两渠道 id 空间不重叠（live 33 ∩ 57 = 0）。
                         #     🚩 接口前缀是 `/v40/api`（`GET /v40/api/index/positions/jds/page?recruit&pageIndex&pageSize`），
                         #       裸 `/api/...` 是另一个 ASP.NET 站点、一律 500「页面出错」——前端 JS 里写的是相对路径
                         #       `/api/index/...`，真正的前缀要从 `$api` 的其它调用（`/v40/api/deliveries/...`）读，别照 JS 猜。
                         #     列表行自带全文（jobResponsibility + jobRequirements），零薄卡、不烧 detail 预算；
                         #     pageIndex/pageSize 都真实生效（page1∩page2=0、page2=total−20；pageSize=200 如实回显）。
                         #     jd_url = `https://{host}/v40/#/position-detail/{id}`（路由表 `path:"/position-detail/:id"`，
                         #       hash 路由；history 形态 `/v40/position-detail/{id}` 是 404），浏览器真渲染核过：真 id 渲出
                         #       标题 + 职责 + 要求 + 「投递简历」，伪 id 渲出空壳。
                         #     判死（ENRICH_REGISTRY `duoyi` / `duoyi_campus`）：`GET /v40/api/index/positions/{id}/jds`，
                         #       真 id → data 为对象 + name 非空（校招 33/33、社招 57/57 零反例）；不存在 id →
                         #       `{"message":"success","data":null,"code":0}`；格式非法 id → `code=10100`「服务端错误」**不判死**。
                         #       双条件 = message==success **且** data 键存在且为 null。诚实边界：「已下线但记录仍在」的反向
                         #       证据一条都没有（多益没有公开历史岗位），只判得出「id 彻底不存在」。
                         #     ⚠️ 校招那条源的 adapter_name 是 `duoyi_campus`（run.py 里与 `duoyi` 同一个类，同 zto_campus 先例）：
                         #       URL `xz.duoyi.com` 没有任何 campus 令牌，走 URL 规则 board 会判成 social → campus-crawl 车道
                         #       整条漏掉；迁移 276 把它钉进 classify_source_board 规则②。
                         #     summary【任职要求】在【岗位职责】前（届别硬信号在要求段，同 sf_express_campus 量出的结论）。
                         #   ⚠️ platform_fingerprint 三处路由扩展（2026-09-18，起因：漏斗把「入口找到了、却被拦在路由门外」
                         #     归类后发现 `adapter_source_url_unroutable` 绝大多数**不是**「平台认得出但没 adapter」，而是两类）：
                         #     ① hotjob 租户首页 `/{SU…}/pb/index.html`（或裸 `/pb/`）→ 映射到 `pb/social.html`。官网「加入我们」
                         #        常直接 302 到这种不带板块的落地页（财通 www.ctsec.com/careers、宇通 join.yutong.com），
                         #        此前 `_adapter_api_url` 返 None → 财通 208 岗 / 卓越 661 岗被挡在门外。校招板块由
                         #        gap_funnel.campus_source_url 同规则换算成 school.html。
                         #     ② `{brand}.hotjob.cn` 根路径同时托管两代产品：页面只链到 `/wt/{brand}/web/index` 的是老版
                         #        WinTalent 租户（富士康 foxconn.hotjob.cn），按 host 判 hotjob 会拿 wecruit 的 suite/config
                         #        去探一个不存在的租户 → `detect_platform` 对这种形态返 ("wt","wt")。
                         #        ⚠️ 富士康 wt 列表四个 recruitType 当日实测都返 0 行——「返 0 ≠ 没开」，只把路由修对，
                         #        有没有岗交给漏斗的真抓验收门，别因此把它 seed 进库。
                         #     ③ 自建壳的**首屏 JS 包**里写死的 ATS 租户地址：talent.deepseek.com（580 B 的壳）→
                         #        app.mokahr.com/social-recruitment/high-flyer/…；www.zhangyue.com/careers →
                         #        q7w8vltyes.jobs.feishu.cn/…。HTML 扫描对它们全判 unknown_spa。现行：HTML 认不出平台时
                         #        读**自家主域**下最多 5 个 <script src>（≤3 MB/个），抽出带 orgId 的 moka / 飞书租户地址后
                         #        **重新走一遍 fingerprint**（身份门 + 路由门一个不跳，只接受 adapter 认出且 identity_ok 的结果）。
                         #        只收自家域名：第三方 SDK 里的 ATS 域名是别家的；moka 只认 `/(social-recruitment|
                         #        campus-recruitment|campus_apply)/{slug}/{orgId}` 形态，sentry-fe.mokahr.com 之类一律丢。
                         #     ⚠️ 中信证券 careers.citics.com **不能接**：列表接口（global-kong.citics.com，sysNo=CSE001 +
                         #        recruitType=08 等）匿名可调，但逐岗详情页 `/positonDetailHeadquarters?…` 前端路由守卫
                         #        直接跳 `/login`（手机号登录）——jd_url 落在登录页，踩 jd_url 红线，按 login_wall 转人工。
                         #     ⚠️ 浪潮 HCM Cloud（`{tenant}.hcmcloud.cn`，浪潮 / 太保 talent.cpic.com.cn / 泸州老窖 hr.lzlj.com
                         #        私有部署 都是它）**是本轮唯一发现的多租户 SaaS**，但请求参数走 `hcm_transfer_strategy=ha5`
                         #        会话密钥加密（key 来自 get_auth 的 `window.dk`）、响应 `hb5` 字符替换 base64，接口名是
                         #        `/api/hcm.model.list?model=ReleaseJobMgr`。要接得先复刻它的传输层加解密，单独立项。
                         #     ⚠️ 中国华能 zhaopin.chng.com.cn 接口路径本身被哈希（`/app-api/recruit/<128 hex>`），同上单独立项。
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
                         #   workday.py = Workday CXS（`{tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`）。
                         #     ⚠️ 租户会搬数据中心（wdN 变、tenant/site 不变）：旧 host 对列表和每个岗的详情**一律回 422**
                         #     （body `errorCode:"HTTP_422"`），公开页回 500 —— 不是限流、也不是岗位关了。2026-09-23 查实两家：
                         #     武田 wd3→wd502（2026-08-02 起 422）、奥的斯 wd5→wd504（2026-08-09 起），各自连败约一个月后源被停用。
                         #     ⚠️ 停用源不会下架它名下的 active 岗（巡检队列不看 enabled，照样按停用源的旧 source_url 去探），
                         #     这两家 2,675 个 active 岗的 jd_url 一直指向旧 host。新 host 从对方官网某个职位的「Apply」链接里读
                         #     （jobs.takeda.com 是 Radancy 皮，Apply 指向 takeda.wd502…）；同一个 /job/{path} 在新 host 上照样能开。
                         #     修法（2026-09-24，迁移 304）：**先**把存量 jd_url / apply_url 只换 host（canonical 由触发器重算），
                         #     **再**改 source_url 并启用——顺序反了，列表重抓会按新 host 另插一批，同一个岗变两行。
                         #     详情探活 `enrich._detail_workday`：404/410 判死，其余非 2xx 判 unknown 不盖戳（429 是 Workday 按 IP 限流）。
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
