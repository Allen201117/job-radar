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
                         #   bytedance.py = 字节跳动三条源：社招官网 `bytedance` / 校招官网 `bytedance_campus` / 全球站 `bytedance_global`
                         #   （joinbytedance.com）。同一个招聘租户的三个公开门户，同一个 posts 接口，靠请求头 `website-path` 区分
                         #   （society / campus / en；另有 jp，以及 robots 明写 Disallow 的 referral——**内推门户不许碰**）。
                         #   ⚠️ 列表必须带头按门户取（2026-10-12 改）。不带头取到的不是任何一个公开门户的列表：全集对拍，
                         #     官网在招而我们从没抓到 368 个；我们挂着在招、中文站链接打开是「该职位已下线」2,148 个（其中 1,302 个
                         #     只挂全球站）。巡检见「已下线」判死 → 清除 → 列表又插回来，墓碑复活 437 行里 346 行是这个循环。
                         #   ⚠️ 判一个岗在不在招：详情接口带**链接所在门户**的头读 `channel_online_status`（按门户算，不带头读出来的不算数）。
                         #   ⚠️ 海外岗的官方页面是 `joinbytedance.com/search/{编号}`，不是中文站。全球站地点用接口的英文名
                         #     （中文名「圣地亚哥」会判成智利，实为 San Diego），并按 sources.regions 逐岗过滤。
                         #   ⚠️ 社招根列表 count 封顶 10,000 → 按一级职类切；职类清单取 `/api/v1/config/job/filters/2` 的 job_type_list
                         #     （只靠前 2,000 条采样，漏掉小职类发现不了）。同一返回体的 job_type_count_map 和列表对不上，别当总数。
                         #   ⚠️ 每轮先带一个不存在的门户名问一次：必须回 site not exist；照样回了岗位（头被无视）或两次都没问到
                         #     → 整轮抛错不写。叶子实取少于自报 / 封顶却没拿到职类清单 / 采样到清单外的职类 → 照常收，
                         #     但不标抓全（不触发缺席撤岗）。
                         #   china_ats.py = 本土通用 ATS（moka / beisen / company_spa；host 从 source_url 动态解析，浏览器拦截 SPA）
                         #   ⚠️ moka 岗位卡的地点与标题（`_parse_moka_card`，2026-10-11 重写；判据是拿 397 个在招门户、38,789 张卡片
                         #     innerText 原文量出来的）：列表接口是密文，地点只能从卡片文字里认。卡片字段区是
                         #     「[薪资] | 部门 | 职位性质 | 职能类别 | 地点」，出现哪几项各租户不同、DOM 上没有类型标记 → 只能按内容认：
                         #     **整段是地名**才算（geo.is_place_name）。旧判据「标题后第一条 ≤12 字、含 省/市/区 的短行」把部门名 /
                         #     职能类别 / 正文句子写进了 location（同日香港库 896 行 / 117 种取值：广东大区、发行市场类、进行市场调查和分析；）。
                         #     · 新版卡片：带省略提示的字段渲染两遍（连着两行相同）、字段间单独一行「|」、最后一个字段后面直接是正文。
                         #       地点是字段区最后一段（23,884 张），或单独在字段区下面一行（福瑞泰克 / 阳光电源校招等 5 个门户 301 张，
                         #       别的门户那一行是正文）；前面几段整段是地名的只有 4 张，全是以城市命名的部门。
                         #       老版卡片：标题后面只有「标签行（几个标签粘成一串，如 全职市场类）+ 地点行」、发布时间在最后、没有正文。
                         #     · 31% 的卡片（12,188 张）上本来就没有地点字段（租户没配置展示；速腾聚创连详情页都不写），另有 1,212 张只写「中国」。
                         #       卡片没写就是空，**不去正文里找**；只写「中国」/ 只写省名也不入库（读侧地点对不上是硬拒，而它说不到城市）。
                         #     · 多地并列（「北京市 广东·深圳市 上海市」）只在入库清洗不丢城市时才写。清洗 2026-10-11 起逐个城市折成
                         #       「北京/深圳/上海」（此前整行折成其中一个城市），所以国内城市并列的行都写了：同日 1,469 张列全了的多地卡里
                         #       1,422 张每个地点清洗都认得；38 张是「国内城市 + 中国 / 境外国家」（location 只给国内城市用，城市照写）。
                         #       📌 纠错：此处原写「这两条共卡住 1,015 张卡（另有 668 张 12 字以内的…一直被折成一个城市，这次没动）；治本要改清洗」，
                         #       清洗已改，12 字例外（_MOKA_LEGACY_MULTI_PLACE_CHARS）已删。
                         #       仍然不写的：超过 3 个地点时页面只列前 3 个（「…等5个地点」，同日 274 张），没列出来的城市不知道是哪几个。
                         #     · 右栏「最新职位」与列表里是同一个链接、只有标题：`_collect_all_pages` 里完整卡片要顶替它
                         #       （改前 65 个多页门户里有 35 个、共 206 张卡因此只剩标题；改后 121 个多页门户 0 张）。
                         #     · 角标（急 / 热 / HOT / Hot / 热招，文字租户自己定）新版单独成行、老版粘在标题前面且只见过「急」。
                         #       🚫 标题开头的「新 / 热」不是角标：改前一律剥掉，「热管理工程师」入库成「管理工程师」（424 张卡）。
                         #     · 英文渲染的门户（富途）：发布日期写 Posted on，地点写「Shenzhen, Guangdong」。
                         #   ⚠️ moka 翻页与抓全率（2026-10-12 修；数字来自 417 条在用的源逐条「旧代码 → 新代码」背靠背真跑，本机系统 Chrome）：
                         #     · 翻页器有两套，选择器都是在真页面上读的。新版门户（页面内嵌数据 websiteVersion=2）是 sd-Pagination：
                         #       30 行/页，末页的下一页按钮带 disabled 属性。老版门户（websiteVersion=1，79 条源）是 .theme-pagination
                         #       下的 span.pagination-item：下一页 class 带 next-page-<hash>，末页多一个 disabled-<hash> 的 class
                         #       （没有 disabled 属性），15 行/页。改前只认新版：43 条老版源每晚只入库首屏 15 个岗却记抓全
                         #       （祖龙 15/86、万科 15/1,312、移远 15/730）；改后这 43 条全部翻到末页、抓到数 = 门户自报（万科差 5，见下）。
                         #     · 分母用门户自报总数：主文档里 <input id="init-data" value="HTML 转义的 JSON"> 的 jobStats.total。
                         #       页面脚本一执行就把这个 input 删掉（渲染后的 DOM 里没有），只能从 goto 的响应体读；只换 hash 的跳转
                         #       goto 返回 None，沿用第一次读到的值。同一次抓取里 404 条翻到末页的源有 398 条与翻到的条数逐个相等，
                         #       最大出入是万科（门户 1,312、列表 87 整页 + 末页 2 张 = 1,307，逐页核过不是漏读）。
                         #       「页面上没有下一页按钮」不再等于抓全：抓到的比门户自报少 2 个以上且超过 1% → 记没抓全，停因
                         #       paginator_not_found（有卡片却从头没见过翻页器）/ short_of_portal_total（没有更多可翻的页仍然少，
                         #       含一张卡都没渲染出来）。翻页被打断的（点击失败 / 刹车 / 撞上限 / 下一页没渲染）停因照实写，不被这两个盖掉。
                         #     · 点「下一页」后列表和翻页器会先从页面上整个消失、再一起渲染回来（本机实测 0.8~2.6s）。改前固定等 1.8s 就读：
                         #       没等到的那一拍读到「没有下一页按钮」，当成单页收工、停因为空。吉利校招 / 百济神州 / 58同城 / 太古地产
                         #       在 CI 上的抓不全记录都是「停在半路、停因为空」，旧代码里这个形状只有这一条路走得出来。现在等
                         #       「翻页器回来了 + 卡片换了一批 + 当前页码变了」，等满 20s 仍没有才记 page_render_timeout。
                         #       首屏同理：页面上先出现一小块推荐岗（老版右栏 5 张 / 新版 8 张），列表后到。对拍里旧代码在滴滴只读到
                         #       这 8 张就翻页（第 1 页漏 22 个、还记抓全）、在温氏读到 8 张就当单页收工（8 对 69）。开读前先等
                         #       「下一页按钮出现，或页面上的岗已够门户自报的数」。⚠️ 这两例出在本机内存吃紧的时候（同时开着 5 个
                         #       无头 Chrome，另一个会话也在跑同样的对拍，可用内存只剩十几 MB），线上没见过滴滴少抓——
                         #       机制是真的，线上多常见没量过。
                         #     · 重复度刹车（base.RepetitionBrake）接进了 moka：麦当劳社招门户自报 58,187（门户自己的职能分组里
                         #       98.5% 是门店类），在第 75 页停、收 1,125 条 / 80 种标题，记没抓全、停因 repetition_brake。
                         #       其余源没有一条被刹（重复率第二高的华润置地校招 90.5%，但只有 441 条，够不到连续 400 条无新角色）。
                         #     · 没解决：整页没渲染出来的偶发仍会发生（对拍里幻方量化 1 次读到 0 张、紧接着重跑 3 次都是 38 张）——
                         #       现在会被门户总数照出来记成没抓全，不再是「0 岗成功、没有分母」，但那一轮确实没抓到。
                         #       moka 没开「列表缺席即撤岗」（MokaAdapter 没有 supports_absence_liveness），抓不全不会连带下架。
                         #     · 线上回读（2026-10-11 UTC 17:53 手动触发的浏览器档，run 38161492728，6 片 29 分钟）：417 条源都有记录；
                         #       43 条老版源全部抓全且抓到数 = 门户自报（万科 1,307 / 1,312）；吉利校招 570→2,285、百济神州 30→481、
                         #       58同城 150→469、太古地产 31→107 都翻全了；麦当劳 1,125 / 58,187、停因 repetition_brake；没有别的源带停因。
                         #       比前一晚少的 9 条源合计少 15 个岗，逐条都是「抓到数 = 门户当时自报」（宝洁另有 5 行台湾岗被拒收）。
                         #       这一轮新入库 5,324 个岗（香港库 moka 在招 53,008 → 58,332）：万科 1,283、麦当劳 1,096、移远 663、锐捷 305。
                         #     · ⚠️ 新入库的不都是新发布的：按卡片上的发布日期分，2024 年及以前 1,698 个（约三成，最早 2019 年；
                         #       万科 882、移远 120、麦当劳 107、云从 94、科兴 91），2025 年 778，2026 年 2,547，卡片上没写日期的 221。
                         #       moka 不写 posted_at，这些岗在库里的首见时间都是上线当晚。门户仍把它们列为在招
                         #       （上线前没量这一维，上线后才补量的）。
                         #     · 发布年限口径（2026-10-12；设口径是创始人同意的，730 这个数是按下面的数据取的、没经他逐字确认，可否决）：
                         #       卡片上的发布日期早于 730 天前的岗不收（`MokaAdapter._MAX_AGE_DAYS`），
                         #       库里已有的由 run.py 按链接下架成 removed（`jobs_db.retire_out_of_policy`；可逆，岗被重新发布后会被收回来）。
                         #       卡片日期 = 门户内嵌数据的 publishedAt（20 个门户首屏 300 个岗逐个对过，全部同一天）。没有日期的卡片照收
                         #       （76 条源整个门户都不显示日期）。为什么不照搬百胜那条的 365 天：全量 43,400 张带日期的卡片里超过 365 天的
                         #       7,402 张、超过 730 天的 3,737 张；安踏、岚图这类有人维护的门户各有四百多个 1~2 年的岗、没有一个超过 2 年，
                         #       超过 2 年的集中在猿辅导（740 里 606）、万科（1,307 里 864）、科兴、云从、知道创宇这类多年没动的门户。
                         #       预演（同一批卡片）：不收 3,737 个 / 115 条源，两个方向判错都是 0；这 3,737 个在库里全是在招，
                         #       其中 1,591 个是近 7 天才入库的、1,643 个 7 月中旬以前就在。29 条源整个门户都超龄、口径后一个岗都不出
                         #       （云从 97、知道创宇 60、卡宾 37…），其中 16 条是社招源，连续 7 天零产出后会被假绿体检点名——
                         #       它们该不该停用要人定。必投清单公司里果麦文化（29→0）、微众银行（3→0）、天合光能（3→0）的 moka 源会清空。
                         #       这次不写 posted_at：另有会话在做，写不写等它量完报给创始人定。
                         #       线上核对（2026-10-12 UTC 01:18 手动触发的浏览器档，run 38191354572）：年限口径这一步在 114 条源上
                         #       下架 3,705 行、失败 0（CI 日志里逐源的 `[policy] out_of_policy=… removed=…` 合计）；预演点名的 3,737 个
                         #       链接在库里全部是 removed——差的 32 个属于同一时段被迁移 322 停用的大陆汽车电子（芜湖）那条源，
                         #       由那边的清理下架。moka 源名下 removed 的行里名单外有 235 行，全在同一时段被停用的关停门户源下
                         #       （Meshy / 仙工智能 / 人福医药 / 观远数据 / 游卡…），是 remove-jobs-by-url-prefix 下的，不是口径下的。
                         #       这一轮 407 条源 jobs_found 合计 46,362（预演 46,366）；28 条源报成功、门户自报有岗、收到 0 个。
                         #       逐门户的对拍表、上线后对库的回读、已停止招聘却仍在招的 60 行：docs/reviews/2026-10-11-moka-old-paginator.md
                         #       （📌 纠错：此处原写「另有一份逐门户的报告在未合入的分支」，报告已于 2026-10-12 进 main，只合了文档、没合那一版代码）。
                         #   tencent_music/antgroup/mihoyo = 必投清单大厂自建 SPA 门户（2026-07-06 live 验证：均有公开 JSON 接口，
                         #     纯 httpx 零浏览器，社招+校招一次抓全；company_spa 吃不掉——接口不返回 per-job URL，须模板拼已验证详情路由）
                         #   avature.py = Avature SearchJobs 通用层（siemens.py 是它的子类）：offset 翻页，
                         #     **页长各租户不同**（西门子 6 / 欧莱雅 20）故按首页卡片数自动推断；详情链接一律取卡片
                         #     href（各租户路径形态不同，禁止正则猜）；source_url 的服务端地区 facet 必须保留。
                         #     ⚠️ 地区后置过滤分两档：facet 源（DROP_UNKNOWN_LOCATION=False）只丢「能确证在境外」的岗，
                         #     Siemens 靠 search=China 全文收窄不可信故保持「地点存疑即丢」——详见 avature._in_regions。
                         #   radancy.py = Radancy/TalentBrew（欧莱雅 2026-10-05 从 Avature 迁来）：sitemap.xml → 按链接城市/
                         #     中文标题粗筛 → 逐岗详情页 ld+json。🚫 **TalentBrew 的 robots 一律禁 /search-jobs**：第一版抓搜索页，
                         #     本机试跑全绿、上线首轮被 robots 门挡成 skipped——接外企门户先读对方 robots.txt，再选入口。
                         #   wt.py / hotjob.py 的截止日（2026-10-10）：🚫 **列表里的 endDate 大多不是截止日**。只有「长期发布」标记
                         #     （wt `isLongTermRelease` / hotjob `longTermRelease`）== 1 才是官网显示的「下线时间」；== 0 时官网写「长期发布」，
                         #     endDate 是系统填的数（wt 回请求当天、hotjob 每晚续成 +7 天、3000-01-01、发布日+12 个月、早已过去的日期）。
                         #     wt 的 == 1 里还有一类「请求当天 + N 个月」的滚动值，同样不写。依据与计数在两个 adapter 的 `_deadline` 注释里。
                         #     ⚠️ deadline 在 `_PRESERVE_IF_EMPTY` 里：adapter 不写 ≠ 库里清掉。所以标记 == 0 的岗另带
                         #     `RawJob.deadline_absent=True`，抓完由 run.py 5d → `jobs_db.clear_deadlines` 清掉库里的旧值；
                         #     标记缺失、wt 的滚动值是「判不出」，不带（带了会在撞日期的那两天把真截止日清掉再写回）。
                         #   正文兜底抽截止日（normalizer.extract_deadline，前端 lib/job-fields.extractDeadline 同口径，2026-10-10 收紧）：
                         #     🚫 「截至 + 日期」多是年龄 / 工龄的计算基准日或统计时点；英文 JD 的 long-term / rolling 不是「长期有效」
                         #     （全库 30,507 行这个标记里库内正文真写着的只有 43 行）。现在要带报名类前缀或紧跟「日期 / 时间」才认，
                         #     两端共读 tests/fixtures/deadline-text-cases.json。
                         #     📌 同日补：中文「长期有效 / 长期招聘」同样要看前后文——正文含这两个词的在招岗 55 行里是招聘声明的只有 3 行，
                         #     其余是「建立长期有效合作关系」一类；rolling basis 同一句要有招聘类词。「截止」后紧跟报名类词也认
                         #     （「本岗位截止投递时间为…」，五矿 13 个岗正文这么写，与平台给的下线时间 13/13 相同）。⚠️ 库里的正文截到 400 字，兜底当时看的是全文：
                         #     29,336 行「长期有效」里库内正文能重现的只有 2,480 行，量这类规则要重拉全文（greenhouse / ashby / lever
                         #     一次请求返回全部正文，95 个源 12,451 岗：旧规则标 2,939 行，是招聘声明的 81 行）。
                         #   hotjob.py 的列表翻页（2026-10-10）：🚫 **第 1 页不听我们传的 pageSize**——回多少条一页、自报的 totalPage
                         #     按哪种页长算都由对方定，同一租户不同时刻还会变（当天实测 1 / 10 / 12 / 15 / 20 / 50）。旧写法每页按 20 要、
                         #     又认第 1 页的 totalPage：页长 <20 时第 1、2 页之间断档（财通证券校招 72 → 64），页长 50 时翻到四成就停
                         #     （广西柳工社招 489 → 200），都记抓全。现行：第 1 页的 totalPage 不认；断档按第 1 页自报页长补一页；
                         #     分母读 dataCount，去重后不够就不记抓全。147 个启用源改前改后对拍：62 个源 +887 个岗、0 个源少拿。
                         #     没治的一种（第 1 页连口径都不同，迪卡侬校招）与「别让后面各页跟着第 1 页的页长翻」的反例在
                         #     `fetch` / `_fill_first_page_gap` 注释里。
                         #   wt 租户换新版门户（2026-10-10 兴业证券）：对方把 `{brand}.hotjob.cn` 改绑成新门户壳页后，旧接口回 HTML、
                         #     库里的旧链接打开落在门户首页。报错现在会写出新门户地址（`wt._non_json_reason`）。处置顺序：先跑
                         #     migrate-wt-rows-to-wecruit 把存量 jd_url 按「wt postId = wecruit externalKey」逐岗换成新门户链接，
                         #     再合 sources 迁移——反过来同一个岗会存出两行。新门户没发布的渠道（页面停在「内部处理中」）不换、不入库。
                         #     ⚠️ 「这个域名回壳页」≠「旧接口没了」：同一天 `www.hotjob.cn/wt/xyzq/` 下列表接口照常回 94 岗
                         #     （详情页是微信版，电脑上点「立即申请」只弹「您还未登录」）；41 个启用的 wt 源里另有 12 个
                         #     首页已跳到新门户、旧接口仍通。
                         #   hotjob 一个租户可以开多个套件、每个套件只发布一个渠道（2026-10-10 中国电信国际，迁移 313）：
                         #     同一个 companyId 下 6 个套件——社招发布在「招聘官网」套件、校招发布在「校招职位列表」套件，另有
                         #     只放介绍页的套件和两个手机版套件（suite/config 的 templateNum=mc，拼 /pb/ 页面必然「官网不存在」；
                         #     seed 时登记的正是手机版，两条源因此被门 1 拦了一个多月）。listPosition 对每个套件都回同一份全量岗位，
                         #     所以「渠道被门拦下」只说明**这个套件**没发布它，不说明这家公司没开。被门 1 / 门 2 拦住的源先找兄弟套件：
                         #     门户导航逐项点一遍 + 读各套件 suite/config 的 config 里出现的其它 `SU…` 链接，逐个跑 should_skip，
                         #     过门的再真抓 + 真渲染。recruitType=13（「公开招聘」，页面 key 叫 overseas）adapter 不认，没有接。
                         #     续（2026-10-11，另外 19 条被门拦住的源逐家查完，迁移 314）：12 家公司里 7 家是登记错了套件（中信卡中心 /
                         #     凌志 / 和睦家 / 赢家登记成手机版，ATL / 歌尔 / 荣耀的社招登记在校招站或实习站上），新城整站关闭换去 Moka，
                         #     光启的电脑版在老版 wt 门户，其余是对方确实没在电脑版发布实习渠道。
                         #     · 找兄弟套件的线索：电脑版套件的 relationMobileSuiteKey 指向它的手机版（单向，值不带 SU 前缀）；
                         #       从手机版反查电脑版只能靠官网入口——和睦家 / 赢家 / 荣耀的社招套件都是从官网页面里的链接找到的。
                         #       平台没有「列出一家公司全部套件」的公开接口，找到的套件不保证是全集。
                         #     · 📌 纠错：上面「listPosition 对每个套件都回同一份全量岗位」不总成立——荣耀社招套件回 379、别的套件回 396；
                         #       ATL 实习各套件回 1 或 10；和睦家校招电脑版套件回 34、手机版回 11。数量以要登记的那个套件自己回的为准。
                         #     · 🚫 列表行自报的 currentSuiteKey 不是本套件的不入库（hotjob._is_foreign_row）：和睦家校招 34 行里 23 行是
                         #       母集团新风天域另一个租户的套件发布的，按和睦家套件拼的详情页 23/23「该职位招聘已经关闭」，门户自己点开的是
                         #       /{currentSuiteKey}/pb/posDetail.html；其中 7 行还是别家公司的岗。两道门和质量门都拦不住，逐条真渲染才看得见。
                         #       全部 150 个启用源只抓列表普查：过门的 129 个源 19,725 行里没有这种行（当天只有和睦家这一处）。
                         #     · 对方主动关闭套件时 suite/config 回 state=500「该官网已关闭」、页面「系统正在维护中」（新城）；门 1 照样拦得住。
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
                         #       📌 2026-10-12 复核：getInfo 是应用外壳每次文档加载自己发的，当天冷启动直接开 `#/99` 也渲染出了
                         #       46 个机构；那次「222 字空壳」更像页面被对方清空（见下）。这一步留着无害，别当必要条件推结论。
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
                         #       （2,418 vs 2,580）而 fetch_complete 还是 True。判据是**对方自己写的空态文案**：
                         #       列表页「暂无热招事项」/ 机构页「该机构暂无在招岗位」（两页不一样别混用）。有卡片 = 答了；
                         #       写着这句 = 答了「没有」；两样都没有 = 没等到 = 漏抓。没等到的机构走完一圈后**补一轮重试**，
                         #       还不行才 fetch_complete=False 并日志点名。单机构页抖一下各自 try/except，
                         #       不许炸掉整轮（否则前面几十家已抓的岗一起丢 + 整源记 failed）。
                         #       📌 纠错（2026-10-12）：此处原写判据是固定标题「招聘机构」/「在招岗位」。读站点 bundle 的
                         #       render 分支：标题在数据回来之前就在；接口被限流（回「请求过于频繁」）时组件不更新 →
                         #       标题在、卡片没有、「暂无」也没有，旧判据会把它记成「这家没在招」。
                         #     🚫 **页面会被对方自己清空（2026-10-12 查实，09-05~10-11 这条源 39 轮 35 轮 failed 的真因）**：
                         #       ❌ `Page.goto: Navigation to "…#/100" is interrupted by another navigation to "…/99/262"`，
                         #          每个机构页「打开失败」，偶尔 `net::ERR_EMPTY_RESPONSE` / `chrome-error://chromewebdata`。
                         #       ✅ 根因：入口页引的 `sm3/core.js`（名字是加密库）里夹着一段检测调试工具的代码，**每次文档加载**
                         #          比 `console.table(大数组)` 与 `console.log(大数组)` 的耗时；有调试协议接着（DevTools / Playwright
                         #          走的 CDP）时前者慢一个数量级，命中就 `for (k in window) window[k]=0` —— `location=0` 让主文档
                         #          自己跳 `…/build/0`，对方网关回空响应。脚本文件 Last-Modified 2026-09-07，首次失败 09-05 20:15 UTC。
                         #          证据：CDP `Network.requestWillBeSent` 的 initiator 栈落在 sm3/core.js 的 eval 代码里；
                         #          不挂自动化的 headless Chrome 连开 6 次全正常；CI 与本机报错逐字相同（不是 CI 环境问题）。
                         #          概率性的（console.log 那一下计到 ≥1ms 才判），且随机器快慢波动很大，没有一个稳定的命中率：
                         #          诊断时多挂了 CDP 网络监听，4 次新加载 3 次命中；adapter 自己的流程本机跑了 14 次
                         #          （多数只加载 1 次文档），3 次命中；CI 上对方还在招的 09-05~10-08 共 35 轮（每轮约 47 次加载）
                         #          = 3 轮成功、1 轮部分成功、31 轮失败；10-09 起的 4 轮是对方已没在招、被记成了失败。
                         #       🔎 **性质判定**：它查的是「有没有调试协议接管」，不查 webdriver / UA / 行为；入口页内联脚本同时
                         #          禁了 F12 / 右键、埋了 debugger 陷阱、把 console 方法换成空函数。是对方明确设的防调试措施，
                         #          不是普通接口参数（对照下面 cib 那条）。
                         #          → **不重试、不绕**：不重新加载碰运气，不屏蔽 / 改写它的脚本；要不要绕由创始人定。
                         #       ✅ 现行处理：`_note_navigation` 记「主文档被带去了应用之外」，一发现就停（`_PageLeft`）：已读到的岗
                         #          照常返回、不算抓全；一个都没读到就带真实原因 failed。列表页之间不 reload、改走「退回首页再进」
                         #          （同路由组件不重挂，直接跳会读到上一个板块留下的内容；reload 则多给它一次判的机会）。
                         #          所有「等页面」的轮询都走 `_poll`（每轮先查页面还在不在）；哪一页没答、为什么，经 `_note`
                         #          拼进报错 → 进 crawl_runs.error_message（CI 日志只记过「打开失败：Error」，线索全丢）。
                         #          「0 岗 + success」要三样都成立：两个板块都新鲜渲染、都写「暂无热招事项」、且同页「招聘机构」
                         #          清单里没有机构标着在招（页面按 `disabled: '1' != flag` 画按钮）。10-12 本机实测 8~12 秒给出结论。
                         #       ⚠️ 没解决的：机构页、详情页仍是每个一次 reload（逐岗正文每晚最多几百次）——有岗的季节里
                         #          一轮几乎必然撞上，撞上即停 = 靠后的机构和大部分正文抓不到（库里 2,671 岗只有 55 个有正文）。
                         #          改成整轮只加载一次文档（机构 / 详情全走 hash）能把暴露面降到 1 次，但当期没岗、验不了读法。
                         #     诚实边界：靠「热招事项」卡枚举机构。2026-10-12 校招 / 社招两个板块都自报「暂无热招事项」
                         #       （校招 46 个机构全部置灰，库里 2,671 岗截止日全是 10-08）→ adapter 返回 0 岗、记 success。
                         #       哪天开了但站点不出热招事项卡，这里会漏——上线后拿 db-report 复核。
                         #       「专项招聘」是 `#/102`（点站点顶栏得到的，当天同样空），未接；bundle 的路由清单里还有
                         #       103 / 498~501 五个同类列表页，顶栏没有入口，不猜。
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
                         #   ⬆ 2026-09-24 老版门户（/zpdetail/{数字}，25 个租户同一套模板）正文两处修：
                         #     ① 抓取时 _beisen_ssr_fill_summaries 每轮只补列表**前 60 条**、且每轮都是同样那 60 条；
                         #       巡检 enrich._detail_beisen 对没有 jobAdId 的链接一律抛 unknown → enrich_row 记「没抓到正文」
                         #       失败 +1、盖戳，满 3 次永久出队。百胜中国 557 岗因此只有 63 条正文。现在薄卡在巡检里取详情页
                         #       补（已有正文的行仍 unknown，死活不判）；两边共用 `beisen_ssr_detail_body`。补后 538/557。
                         #     ② 正文正则取到页尾，页脚「现在申请 返回职位列表 收藏 [热招职位 更多>> 别的岗名…] ©2026 … 京ICP备…」
                         #       整段进了 summary（22 租户 482 条）。现截在页脚前（`_BEISEN_SSR_FOOTER_RE`），存量逐条从原页重取：
                         #       424 条新正文逐条是旧正文的前缀（只去页脚、0 条丢真内容），15 条真实 JD 不足 60 字（靠页脚凑够的）如实变薄。
                         #     ③ 死活只靠浏览器巡检（httpx 巡检对这类链接只补正文、不判死）。巡检一直覆盖得到
                         #       （2,306 个在招岗 2,090 个近 7 天巡过），但撤岗页仍渲染岗位名、只多一句「对不起，此职位已停用。」，
                         #       这句不在强信号表里 → 标题在场判 alive，85 个停用岗一直挂着（5 个绿城的还在官网列表里）。
                         #       已把整句加进 `DEAD_MARKERS_STRONG`：全集 httpx 2,306 岗 + 真渲染 584 岗对拍，停用 85/85 判死、在招误判 0。
                         #       📌 纠错：本段上一版写「这类链接没有任何死活判定」，不对——覆盖在，缺的是这句文案。
                         #     ④ 京博 / 华夏基金的 /zpdetail/{id} 是**跳转壳**：隐藏框 #v 写招聘类别，脚本按类别跳到自有模板
                         #       （/xiangqing?jobId= / /szzwxq?jobId= 等），正文在那一页、页脚是「返回列表 / 立即申请 / 版权所有」。
                         #       `beisen_ssr_fetch_detail_body` 照壳自己的分支跟一跳（jobId 必须与原链接相同才采信）。
                         #       全集 2,222 岗新旧提取对拍：新得 88、丢 0、变短 26（全是方太，截掉的是导航）。
                         #       至此老版在招 2,222 岗有正文 2,155，余下 51 条官网页面本身职责为空 / 写「无」「1」。
                         #     ⑤ `_SSR_TENANT_POLICY.max_age_days`（百胜 365 天）同时约束库里已有的岗：run.py 收抓后把发布日
                         #       早于截止日的置 removed（`jobs_db.retire_posted_before`，可逆、不进 purge），边界与抓取端逐日对拍。
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
                         #   byd.py = 比亚迪 job.byd.com：社招（`byd`）+ **校招**（`byd_campus`，2026-10-11 接入）两个类，都要起浏览器。
                         #     ⚠️ 校招是官网的另一套接口，不是社招接口换渠道码。社招页调 position/queryList（zpType=00251）；
                         #       校招页调 postEntryConfig/list（投递入口）→ schoolPortal/queryPositionList → schoolPortal/queryPosition。
                         #       position/queryList 换成 zpType=00252 也有返回、自报 15,582 条，但官网没有任何页面这样调它
                         #       （app.js + 65 个懒加载分块全扫过，传给它的只有 00251 社招 / 00254 技工）：11,972 条 planYear=2024、
                         #       全部建于 2024-06；3,606 条是 2027 届的内部需求条目（relatedCode X 开头，正文是带「工作经验：3年以上…」
                         #       一栏的岗位族模板）。校招页当天自报「在招职位 (384)」。
                         #     接口怎么读出来的：路由表在 static/js/app.<hash>.js（/school/schoolPositionList、schoolPositionDetail），
                         #       各页面是懒加载分块（分块名 → hash 的两张表内联在 portal/pc/ 的 HTML 里，前一张是 css、后一张才是 js）。
                         #     一行 = 校招列表里的一个岗（一个详情页）。详情接口回 positionInfoList：这个岗下面的「岗位方向 × 部门意向」，
                         #       各有各的工作职责 / 职位要求 / 学历码（最多见过 72 组），页面要先选方向和部门才显示正文。
                         #       → summary 把方向、部门、地点、学历排最前，正文按出现顺序接在后面；同一段正文只写一遍。
                         #     入口：应届生 384 + 实习生 2（2026-10-11）。「博士生」65、「外派专项」26 是应届生按学历 / 是否外派筛出的
                         #       子集（逐 id 对过全在 384 里）→ adapter 按「届别 + 招聘性质」去重，abroad / degree 留空取全集。
                         #       招聘性质码（字典 0085）：008501 应届生 / 008502 实习生；008503 校园大使 / 008504 储干当天没有入口，不认识的不抓。
                         #     job_type 按渠道填：应届生「{届别}届校招」（详情页给这类岗挂「应届生」「2027届」标签）、实习生「实习」（页面不挂届别）、
                         #       社招「社招」。社招原先填部门名：normalizer 见它不是招聘类型就用正文重推（有「应届」→ 校招），
                         #       不带正文的抓取又写回部门名，同一行来回变。
                         #     ⚠️ 详情 URL 的查询串是前端加密的（密钥 12 字节，不是标准 AES 长度，标准库算不出）→ 让页面自己的 Vue Router 生成。
                         #       **取 route.fullPath，不取 href**：href 过 vue-router 的 cleanPath，把密文里的 `//` 压成 `/`，那条链接打开是空白页
                         #       （页面解不出 id，连详情接口都不调）。出现概率约 1.5%：校招 386 条里 6 条；社招一直在写这种坏链接，
                         #       2026-10-11 库里在招 7,481 条有 96 条（密文长度 43 / 42，正常是 44）。生成后再用页面自己的 parseQuery
                         #       解一遍，解回同一个 id 才给 URL。那 96 行 2026-10-12 已标 removed（创始人同意；没有用户操作指向它们；
                         #       其中 32 个还在招的岗，上线当晚已经以正确链接重新入库）。
                         #     🚫 **社招撤岗后的详情页是空壳，没有任何文案**（2026-10-11，库里 7,481 个在招行逐个核过）：不渲染岗位名、
                         #       不渲染正文，也没有「已下线 / 停止招聘」，正文恒 208 字（导航 + 页脚）。浏览器巡检的 classify() 对它只能判
                         #       suspect（375 个真渲染样本里 300 个已撤岗全判 suspect、0 个判 dead）→ 每天巡、从不下架，攒了 5,429 个已撤岗
                         #       （最早 6 月）。既不是「文案没收进 DEAD_MARKERS」，也不是浦发那种「撤了照样渲染正文」，是第三种。
                         #     社招 position/queryDetail 对「已撤岗」与「从没有过的 id」回的是同一个东西：200 + code=0 + 字段全空的骨架
                         #       （只有 collectionStatus 有值；没有任何状态字段）。在招岗回带同一个 id + 岗位名，有值字段 10~13 个。
                         #       全集对拍：不在列表 5,429 → 空骨架 5,429；在列表 2,052 → 在招 2,052；两个方向反例 0；
                         #       300 个伪 id（含真 id 的相邻值）全是空骨架。非数字 / 超 int64 的 id 回 code=4005，不判死。
                         #     社招列表是全集：`pageNum` 是行偏移不是页码；去重后凑不齐自报 total 就抛错。列表里省市皆空的行
                         #       （当天 26 条）在 parse 被地点门挡掉，从不入库。
                         #     社招撤岗核验 = `crawler/byd_liveness.py`（+ `byd-liveness.yml`，每日定时真跑、手动触发默认 dry-run）：库里的链接让官方
                         #       路由解回岗位 id（老的坏链接唯一解才修），「不在本轮全量列表」且「详情两轮都回空骨架」才下架；逐岗探之前、
                         #       每探 500 个之后都过阳性 / 阴性对照；另有四道整轮作废的闸（链接解不出 id / 上一轮的岗大面积缺席 /
                         #       不在列表却读到在招的太多 / 判死占比）。社招不开 list-absence：它认的是「这轮没被写库」，列表里有、
                         #       却被后面清洗挡掉的行同样没被写库；存量 73% 缺席也会被 50% 安全闸永远跳过。
                         #     live（2026-10-11，本机 Chrome）：386 岗，质量门 386/386，详情页 386/386 真渲染标题一致；
                         #       真实 normalize + JS 分类器：校招 384 / 实习 2 / 社招 0，届别 2027 = 384。1,625 组方向正文里写「N 年以上经验」的只有 1 组。
                         #     下架：`supports_absence_liveness=True`（列表 = 页面「在招职位」全集，逐入口核对 totalCount；列表里有一个岗写不进库就不算抓全），
                         #       但只打印 dry-run 数字：这条源只在带浏览器的重档跑，那里没开 LIVENESS_ABSENCE_APPLY，`run.ABSENCE_OBSERVE_DEFAULT` 里也有它。
                         #       还没见过「从列表里消失的岗在官网上是什么样」。开落库前先想清：某个入口被关掉时它的岗整批算缺席（实习生入口只有 2 个岗，
                         #       50% 安全闸拦不住）；入口全关（校招季结束）时 adapter 回 0 岗记 empty，走不到按缺席下架，存量行不会自动下架。
                         #     宁可报错不记空：入口接口业务码非 0 / 开关值不认识、列表自报有岗却一行都认不出、列表有行却一行都映射不出岗位、
                         #       重档要补正文却一个详情都没取到 —— 都抛错记 failed。只有「入口全关 / 入口下 0 个岗」才是 0 岗 empty。
                         #     没填的：posted_at（页面上那个日期叫「更新于」）；多地岗的 location 只取第一个城市（114 个岗是多地）。
                         #     `/school/schoolInternRecruitment` 不是岗位列表：是一份 Word 实习生招聘简章渲染出来的静态页 + 登录后投递按钮。
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
                         #     ⚠️ 列表接口的三条硬边界（2026-10-12，全部 101 个启用源 293 个翻页查询逐个真翻）：
                         #       · 单页最多 20 条（limit=50 / 100 回 400）；
                         #       · 一个查询最多给 2000 条，首页自报的 `total` 封顶在 2000（小于 2000 时是准的：280 个正常收尾的查询 0 个对不上）；
                         #       · **翻过末尾不回空页，回的是第一页**（offset >= total 或 >= 2000 都是）。
                         #     ❌ 第三条让「条数恰好是 20 的整数倍」的查询永远等不到短页 / 空页：旧实现一路翻满 100 页、记「命中安全翻页上限
                         #       got=2000」和 coverage_complete=false。同一轮 11 个源 12 个查询中招（Boeing / 丹纳赫 / 安波福 / 摩根士丹利 …），
                         #       白翻 964 页 = 全部列表请求的两成，而这 12 个查询一个岗都没少。哪个源中招每轮都在变（看当时条数能不能被 20 整除），
                         #       所以日志里辉瑞 / 通用汽车那种「got=2000、最终只有几百条」不是漏抓。
                         #       ✅ 收尾判据改成「这一页没有带来这个查询里的新岗」（`_page_through`；判重用查询自己的集合，不用跨查询的 seen）。
                         #     ❌ 真撞 2000 的只有 Target：国家级 facet 自报美国岗 14,072，每轮只见 2,008；库里 4,132 个在招行里 2,124 个这一轮没看到，
                         #       其中 2,107 个仍在对方列表里（抽 60 个实开详情 60 个在招），最久的超过 14 天没刷新过 last_seen_at。
                         #       ✅ `_collect_capped`：首页 total 封顶 = 装不下 → 按响应里 facet 的计数切块，每块计数和 ≤1800、id 数 ≤150。
                         #       facet 计数受其它已选维度的过滤影响、不受本维度影响，而且是准的（51 个州逐个翻完，条数都等于计数）。
                         #       多个取值的并集 → 按计数重新分组；单个取值（国家）→ 换一个维度叠一层，这个维度的计数和必须 ≥ 对方自报的岗数
                         #       （🚫 Target 带国家过滤时 `locations` 只露出 55 个叶子 766 个岗，拿它切会静默丢九成五）。
                         #       Target 按州切、加州（2,155）再按用工类型切，独立对照组逐块翻完 = 14,071 条。
                         #     ⚠️ 切块受全站既有的两道闸管，不是 workday 另立的：重复度刹车（`base.RepetitionBrake`）+ 单源条数上限（`resolve_list_cap`）。
                         #       Target 是门店批量发布：14,071 条归一后只有 694 种标题、前 20 种占 91.8%，职类 Stores 一项 13,646，
                         #       其中 11,961 条是同一天发的。刹车在切出来的第一块（加州）翻到第 780 条时停。被刹车叫停的源只收两样：
                         #       原查询自己的前 2000 条（改前就拿得到的，保证不比改前少）+ 各维度里「有压倒性大取值、剩下那些取值合起来装得进
                         #       一个查询」的小众取值（`_collect_minor_values`：非门店职类 425、全职 977、实习 128 …）。刹车前试翻到的那几百条不留。
                         #       背靠背真抓（旧 → 新 → 旧，各隔几分钟）：两次旧实现拿到的 2,007 / 2,002 条改后全在；非门店职类 213 / 426 → 425 / 426；
                         #       Target 一轮列表请求 103 → 240，0 次 429。
                         #       停因记 `repetition_brake`，`reported_total` 记对方 facet 自报的岗数（改前记的是「看见多少报多少」，台账上看不出少了）。
                         #     📊 全部 101 个源新旧各真抓一轮（只跑列表阶段）：列表请求 4,706 → 3,888（13 个源降、3 个源升，其中 Target +137）；
                         #       记「抓全」的源 89 → 100（剩 Target，带停因）；旧有新无 73 行，拿旧实现当场重抓其中 72 行对方已撤、
                         #       1 行是 Target 窗口边缘的岗（两次抓取隔了 10 分钟；上一行的背靠背对拍里为 0）。
                         #     ⚠️ 没治的：Target 库里窗口之外的门店岗（约 1,500 行）仍然刷不到；现成的折叠工具按「角色 × 城市」折，
                         #       Target 的地点是门店街道地址，4,132 行只折得掉 74 行。要不要整包拉 / 只留非门店岗，等创始人定。
                         #     ⚠️ 文本兜底（searchText）超过 2000 条时不切块（逐岗还要再过 regions，且当天没有一个源的文本查询真撞上限）。
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
