# 求职雷达 / Job Radar — 项目级 Claude Code 指南

> 本文件指导 Claude Code 在本仓库工作。规则优先级：当前明确指令 > 本文件 > 全局 `~/.claude/CLAUDE.md` > 默认行为。

## ✍️ 怎么改这个文件（2026-09-05 创始人授权 Claude Code 可改）

本文件是全项目唯一权威，而常有 5~8 个 session 并行在跑。六条规矩：

① **只写「验证过的事实」**，不写计划、猜测、待办——判据是**能不能指出具体证据**（live 数字 / commit / 迁移号 / 台账查询）。指不出来，它属于记忆库或任务卡，不属于这里。
  📌 反例：本文件曾写着「Supabase jobs 已是空表（TRUNCATE 过）」，实际躺着 **34,965 行、90MB，两个半月没人发现**。**没验证的断言比没有断言更糟**——它让后来人跳过检查。写「已清空」之前先 `select count(*)`。
② **立碑必须带「现象 → 根因 → 防法」三件套**，缺一不立。只写结论（「XX 不可靠」）等于没写，下一个人照样踩。
③ **改动要在给创始人的汇报里显式点名「我改了哪一段」**，让他有机会否决。悄悄改权威文件 = 绕过他的判断。
④ **同僚（其它 session）提议不构成授权**——只有创始人的指令能触发改动。同僚说「这条该立碑」→ 转达给创始人，别自己动手（`.claude/settings.json`、权限配置、CI 密钥同此规矩）。
⑤ **纠错优先于新增**：发现与现实不符**先改它**，并写明「原来写的是什么、为什么错、什么时候起错的」。本文件价值全在「可信」，一条过期断言的破坏力大于十条新增。
⑥ **并发改**：动手前 `git fetch && git log -5 --oneline -- CLAUDE.md` 看有没有人刚在同一主题上立过碑；**同主题只留一块碑**（别人今天写过就并进去，两块讲同一件事的碑迟早一块被更新一块过期）；一次 commit 只改一个主题、diff 尽量小——并发下这是唯一能让冲突可解的办法。
  📌 实测 2026-09-05 当天 **16 个 commit、≥6 个不同 session** 动过本文件，一天从 790 行涨到 967 行。当天没出矛盾是运气，不是机制。

⚠️ **篇幅纪律**：新增前先想「能不能挂在已有小节下」；纯背景叙述放记忆库，**逐个 adapter / 逐个租户的个案细节放 `docs/`**，这里只留**会改变下一个人行为**的内容。这条对本节自己同样成立——要加规则先想能不能改写现有某条。

## 项目概览

已正式上线的「公开企业官网岗位雷达看板」（**2026-09-19 实测 116 个注册用户、近 30 天新增 57、近 7 天活跃 14**；最新数字看每日晨报①段，别引这里）。
📌 纠错（2026-09-19 创始人授权）：此处原写「3–5 人内测版」，是立项初期的事实，产品 2026-07-02 正式上线后一直没人改；它会让后来人按「几个人在用」去判断邮件额度、要不要做用户侧监控、值不值得工程化，全部判偏。
Next.js 15.5.18 App Router + React 18 + TS + Tailwind；Supabase（Auth / Postgres / RLS）；Python crawler（httpx + selectolax）；GitHub Actions 定时抓取。npm（前端）/ pip（`crawler/requirements.txt`）。Node ≥18.18，Python 3.11+。前端部署 Vercel，crawler 跑 GitHub Actions。

**线上地址 = https://www.myjobradar.top**（创始人 2026-09-08 授权写入，别再问）。实测要点：
① 页面（/today /jobs /campus…）**要登录**，匿名一律 307 跳 /login —— 只能用创始人已登录的 Chrome 看，
   Vercel 的 `*.vercel.app` 预览域被部署保护挡着（302 到 Vercel 登录页），不是产品的问题。
② `/api/jobs/search`、`/api/jobs/stats` **允许匿名**（`app/api/jobs/search/route.ts` 有显式注释说明这是
   有意为之），所以 curl 就能测这两条，做性能对拍不必开浏览器。
③ 响应头 `x-vercel-id` 前缀即实际执行区域，正常应看到 `hkg1`（见上文函数区域锁定那条）。

- **⚠️ 函数区域锁定香港 `hkg1`（`vercel.json` 的 `regions`，2026-07-30 加，别删）**：jobs 热表在香港自建 PG，函数默认区是美东 `iad1`，跨太平洋让「建库连接」这一步就要 800~1400ms（内测低流量下 `lib/jobs-store/client.ts` 的 `idleTimeoutMillis:10s` 使几乎每请求都重新握手），实测 `/api/jobs/stats` 曾要 6.6s 甚至超时。诊断方法：`curl -D -` 看响应头 `x-vercel-id`，前缀即实际执行区域。
- Vercel Hobby 也可选区域（限单区）；**但 Routing Middleware 不跟随该设置、固定全球边缘跑**——middleware 里的跨洋开销只能靠「不联网」消除（见「认证」段的本地 JWT 验签）。

## 核心闭环（产品第一目标）

`公开企业官网岗位 → 抓取/刷新/发现 → jd_url 质量门 → 标准化入库 jobs → 偏好规则打分排序（lib/scoring.ts）→ Today / Jobs 看板 → 点击跳官网详情 → saved / ignored / applied 反馈`

先跑通这个最小闭环，再加 LLM / 邮件 / 推送 / 商业化。

## 核心产品原则（最高优先级，违反即残次品）

筛选准确性 = 本产品核心指标。下面三条是产品命脉，任何抓取/筛选改动都必须遵守：

1. **精准路由，按用户筛选项爬取，禁止乱爬**
   爬虫必须严格参照用户在页面配置的筛选项（城市 / 岗位类型 / 关键词 / 公司）去定向抓取，不得自以为是地一律爬社招或乱爬无关方向。
   - 板块路由：能按筛选项选板块的源就选对板块（如字节 实习/校招→`/campus`，社招→`/experienced`）。
   - 后置过滤是所有源通用的「正确性兜底」：无论抓到什么，只放行同时满足 城市 + 类型 + 关键词（+ 偏好）的岗位；三桶分类与前端 `recruitmentCategory` 同口径。
   - 不允许猜测未验证的板块 URL（猜错=乱爬）；无可验证板块的源，靠后置过滤保证准确。

2. **联网抓取的底层逻辑 = 以用户已保存的求职偏好为默认精准范围**
   抓取/筛选默认依据用户 `candidate_profiles`（target_roles / skills / industries / experience_stage / target_locations）+ `user_preferences`（target_keywords / exclude_keywords）来收窄，不抓与用户背景无关的岗位。
   - 覆盖规则（逐字段）：用户在筛选器里**手动配置了某项**，该项按用户配置来；**未配置的项**默认用其个人偏好。
   - `exclude_keywords` 命中的岗位一律不入选。

3. **精准 / 可靠 / 稳定 > 规模，但正式上线后「保精度逐步扩量」（2026-07-02 更新，覆盖旧「停止扩源」表述）**
   ⚠️ **2026-07-02 方向更新**：产品已正式上线，`~800` 源不够用了 → 转入**「在保精度基础上逐步扩量」**（用户 2026-07-02 定调，优先于下面 2026-06-15 的「停止铺量」旧调）。落地 = **每日自动定向扩源已启用并真入库**：`auto-discover-browser.yml`（每日 UTC 21：北森/Moka 浏览器确认 + 同批目标顺手探飞书/hotjob）跑 `crawler/auto_discover_browser.py`；`auto-discover.yml`（httpx 道）**2026-09-23 起停掉每日定时、只留手动**——静态清单 844 家缺口全量探飞书/hotjob 得 0 个新候选，并入浏览器道（创始人拍板；📌 纠错：此处原写两道都每日跑），从精选目标公司清单里取库里没有的公司 → live 探活 → **只入「探活通过 + 真有在招岗 + 标题核验防张冠李戴」的源**（精度红线不变，猜错/无岗自动丢）。三管齐下提产出：① `crawler/targets_tech_consumer.json`（149 家科技/互联网/新经济/消费/游戏/AI/智能硬件/SaaS 目标公司，每家多 slug 变体，`_priority` 优先探，纠正旧清单 76% 传统制造与目标用户错配）；② 提转化（多 slug + 优先探对方向）；③ 提每日配额（httpx target 30→80/insert 20→40，browser tenant 60→120/confirm 10→15）。**扩量 = 定向补目标用户要的科技/消费公司，不是无脑铺量**；仍禁止猜 slug 直接入库（靠探活门兜底）。管理员看板「自动扩源」卡可看每日产出。
   **④ 持续喂清单（LLM 生成器，`crawler/generate_targets.py`，2026-07-02 加）**：静态清单会烧完（2026-09-23 实测已烧完）→ 每日在浏览器道 CI 里用 SiliconFlow（复用 `insight_engine.chat_json`，env `AUTO_DISCOVER_LLM=true` + `SILICONFLOW_API_KEY`，按行业主题按日轮转）生成一批「库里没有的」真实公司候选，喂给**同一条探活验证门**（编造/猜错 slug 探活不过自动丢，绝不入库）。`AUTO_DISCOVER_LLM` 一关即回退纯静态清单。⚠️ **它一关本链就等于停**：8/1~15 自动扩源入库 73% 来自新料；8/27 欠费关掉、9/19 恢复时漏改浏览器道，三道连续 0 近一个月没人看出原因（台账当时只有 checked/produced）。防：台账 `llm_candidates`（开着却为 0 → CI 打 `::warning::`）+ 各步淘汰计数，查「为什么 0」先读它们。诚实边界：LLM 的真实公司宇宙有限（几千家量级），能把库从 ~900 持续喂到几千、撑很久，但不是无限高速。
   **⑤ 缺口漏斗（2026-07-27 加，专治必投清单覆盖）**：上面①-④是「按公司清单猜 slug 探 4 个平台（feishu/hotjob/beisen/moka）」，对**非互联网行业结构性够不着**——银行/央企/外企/自建门户不在这 4 个平台上，实测 151 家必投缺口里 150 家在 sources 表连一行都没有，且 120 家天天被猜天天 0。补上的是 `crawler/gap_funnel.py` 这条**搜索找入口 → 平台指纹 → 已有 adapter 路由 / company_spa → 真抓回读健康岗才入库**的漏斗（`gap-funnel.yml`，默认 dry-run，失败按原因退避不空烧）。
   **国聘（iguopin.com，国资委官方央企招聘平台）是「第三方平台禁令」的唯一例外**（创始人 2026-07-26 拍板）：央企大多没有逐岗官方详情页，国聘是唯一能拿到稳定 jd_url 的官方渠道；智联/BOSS/前程无忧/猎聘 红线不变。
   **精度约束（源自 2026-06-15「停止铺量」旧调，已降级为约束但仍生效）**：指标看「目标相关的**有效产出**」而不是源数量——多少源在稳产 *目标相关 + 带 jd_url + 有 JD 正文* 的岗；0 产出 / adapter 已坏 / 与目标用户无关的源优先 `disable`（保留行可回滚，**别删**）；只留能过质量门、稳定逐岗 `jd_url`、且现有链路**可持续抓到**的源（浏览器源串行单个 2–5min，daily CI 预算有限 → 头部 daily 抓、长尾降频按需）；加源必须 live 探活确认真出岗才留，**禁止猜 slug 入库**。「中国本土 > 外企」「私企500强 > 国企央企」的相对偏好仍成立（用于排序与定向补源的取舍），但服从「精 > 量」。
   - **列表夹带已关闭岗：只能靠 sweep，list 端过滤技术上做不到（2026-06-15 查实）**：wt / hotjob 的列表接口会返回**已关闭的岗**（wt 52% / hotjob 71% 抓进来即被 sweep 判死）。已 live 验证 list 端没有可靠的「关闭」字段：hotjob `canDelivery=false` 在**在招**岗上也为 false（华夏银行 live 岗 15/15 都是 false）；wt 夹带的已关闭岗与在招岗**除身份字段（postId/postName/workPlace）外无任何区别**（endDate 仍是未来日期）。唯一可靠的关闭信号是逐岗 detail（hotjob `state=1017` / wt `req_state=9501`）→ **保持 sweep、不要去做 list 端过滤**；减少 churn 只能靠 detail 探活，成本 = sweep 本身。⚠️ 但**不许假设 sweep 自动有效**——它曾因队列查询撞 statement_timeout 长期没真跑成（见 §4），以 db-report 的真实数字为准。

4. **指标诚实，不拿低质量/失活岗滥竽充数（2026-06-16 定为方针，最高优先级）**
   首页「岗位库」计数必须用 `count_valid_active_jobs()`（= active + 有 JD 正文 ≥60 字，迁移 151），**禁止用裸 `count(status='active')`**——后者含 25% 薄卡（moka 2.6 万张几乎全无正文）+ 大量未探活的假 active，会把数字虚高到「十万多」。计数 = 真实可投的高质量岗，不是行数。
   - **搜索结果的「匹配岗位数」撞取数上限时不许给确定数字（2026-09-03 立）**：检索是「先取候选、再 JS 精筛」，候选有上限（`FTS_CAP=8000` / `SCAN_BUDGET=28000`）。撞上限时 `total` 只是「取到这么多」——线上「深圳+社招」因此长期写「8000 个匹配岗位」，而库里有 15,290 个。现行口径：`lib/match-total.formatMatchTotal` 统一决定给不给数字（计数行 / 筛选弹窗「查看 N 个岗位」/「加载更多（还有 N 个）」三处共用）；`lib/jobs-store/search.ts` 的 `exactTotalWhenCapped` 只在**能证明数字正确**时回填 `exactTotal`，否则 null → 前端显示「8000+」。
     - 能证明的支点：**计数用的就是取候选那条 where**（同一份 conds/params），所以只需「where 成立 ⇒ `jobFilterMatch` 放行」这一个方向。四道门：结构门（`filtersFullyPushedToSql`，JS-only 条件生效即弃权）/ 偏好门（`exclude_keywords` 非空即弃权）/ **运行时自检**（候选里除 SQL 一并排除的 ignored·applied 外一条都不该被 JS 淘汰，不成立即弃权——这道门不依赖任何人记得改代码）/ 未分类门（`recruitment_category is null` 走信号超集兜底，不是充分条件）。
     - ⚠️ **`total` 的语义不许改**（= 可翻页条数）：真实总数塞进 `total` 会让 `hasMore` 判断失真，「加载更多」永远点不完。真实总数只走 `exactTotal`、只用于展示。
     - ⚠️ 新增筛选项**必须**在 `lib/job-filter.ts` 的 `SQL_PUSHED_FILTER_KEYS` / `JS_ONLY_FILTER_KEYS` / `NON_FILTERING_FILTER_KEYS` 三张表里显式归类，否则 `tests/ux-hardening-contract.test.js` 直接红（fail-safe：漏归类只会退回「N+」，不会给错数字）。
   - **失活治理靠探活、且必须确认真的在跑**：active 一度膨胀到 ~13 万 → enrich/sweep 取工作队列的 `status='active' ORDER BY …` 查询撞 service_role ~8s statement_timeout **静默失败**（db-report 实测 87% 岗 `enrich_checked_at=NULL` 从未探活、死岗下架不掉 = 恶性循环）。已加 source 前导部分索引（150 summary-drain / 151 liveness-sweep）让队列查询走索引脱离超时。`liveness-sweep.yml`（只探活不抓列表、不回潮假 active；**2026-06-20 起每日 08:00 UTC 定时跑**，max-parallel:4 护住 HK `max_connections=100`）+ `dead-link-audit.yml`（浏览器 SPA 源：beisen/moka/feishu **及 nio/xiaomi/xpeng_feishu 变体 + 自建大厂 SPA byd/kuaishou/bytedance/google**，每日定时）真跑，并以 `db-report.yml` 复核 `never_liveness_checked` 持续下降。**⚠️ 死岗反复回潮的更深真因（2026-06-20 修，commit 01728ee）= list 重抓的 upsert 把 sweep 判死的 `expired` 刷回 active、并抹掉 `enrich_checked_at`（巡检按 nulls first 轮转 → 被抹的岗反复插队、sweep 永远追不上，89% never-checked 真因）→ status 走 `CASE` 黏住 expired、`_UPDATE_COLS` 移除 enrich 簿记（jobs_db.py + write.ts 同口径）。改 upsert 务必保住此不变量。**
   - **失活校验全部放在「不挡用户」的层，绝不放点击路径（2026-06-21 定，踩坑后修正）**：⚠️ 曾把实时探活放进点击门（`/api/jobs/go` 服务端探完再 302）——云函数冷启动 + 跨区连香港库 + 跨区探外网叠加，**实测点击要 5-8s，体验很差，已废弃并删除**。教训：**质量校验是后台/异步的事，不能卡在用户点击这一下**。现行设计 = **点击直跳官网（瞬开，JobCard/applied 直接 `window.open(jd_url)`）** + 两层离线/异步校验把死岗挤掉：
     - **② 展示时校验（非阻塞）**：看板（Today/Jobs）加载后**异步**批量探活当下可见岗（`POST /api/jobs/liveness-check` → `lib/liveness-client.js`，复刻 enrich.py 的 wt `req_state=9501`/hotjob `state=1017`/workday 404，封顶 2.5s、并发 6、跳过 24h 内刚探过的、`hasSessionCookie` 廉价判登录态不走 getUser）；死的标 expired + 当场从看板隐藏（deadIds 过滤渲染），活的盖 `enrich_checked_at`。看板先渲染、不被它阻塞；它只让死岗随后悄悄消失。
     - **③ 后台 sweep / 浏览器审计**：大盘卫生主力（见上）。
     - 残留：岗在「加载后→点击前」那几秒死掉、或 SPA 源死岗 ② 没覆盖 → 偶发一次快速 404（可接受，远好过每次点击等数秒）。`lib/liveness-client.js` + 写助手 `markJobExpiredById`/`touchJobCheckedById` 仍由 ② 复用。
   - **🚫 主动挑岗给用户看时，「能点开」的判据是 `last_seen_at` 新，不是 `enrich_checked_at`（2026-09-06 立）**：
     ❌ 现象：按「`enrich_checked_at` ≤14 天 = 已探活」挑出来的岗，点开是「该职位已停止招聘」。
     ✅ 根因：`enrich_checked_at` 只说明**我们那天补过正文/探过一次**，之后关掉没人知道；
     `last_seen_at` 新 = **官网列表昨天还挂着它**，是第一手在招证据。
     📊 Playwright 真渲染对拍（两池各随机抽 120 条、跨公司铺开、同一套 `DEAD_MARKERS`）：
     `last_seen_at ≤30h` → **死岗 0**；`enrich_checked_at ≤14d` → **死岗 5（4.2%）**
     （人保 / 恒力石化 / 泡泡玛特 / 阅文 / 零跑，文案「停止招聘」「职位不存在」）。
     📄 防：`lib/jobs-store/popular.ts` 的 `LAST_SEEN_WINDOW`（30h 不是 24h，给日更 CI 抖动留余量）。
     ⚠️ 它**不能单独用**：wt/hotjob 的列表本身夹带已关闭岗（52%/71%，见上文），对这两类源 last_seen_at 最弱
     —— 正好 `lib/liveness-client.js` 覆盖它们；反过来 moka 系 SPA 列表可信但探活覆盖不到，靠 dead-link-audit。
     两层互补，别只留一层。
     ⚠️ **curl 判不了死活**：中国 ATS 详情页 76% 是 JS 渲染（实测 124 条「普通页」只有 38 条把标题渲进 HTML），
     moka 系还会对裸 curl 无限 302 → 判死活必须真渲染，Workday / 慢 SPA 要等到 12s 否则假报 unknown。
   - **🚫 hash 路由的岗位页在浏览器巡检里必须 reload()，否则会删掉在招岗（2026-09-06 立）**：
     浏览器对「只有 `#` 后面不同」的 `goto` 是**同文档导航、不重新渲染**，屏幕上留着的还是上一个岗。
     实测（复刻 `audit_dead_links` 的 goto+2500ms）：先探一个已下线的快手岗、再探**在招**的
     `job-info/31711`，第二个读到的是第一个的「该职位已下线」→ 判 dead → `--apply` 置 expired
     → 次日被 `purge-expired` **永久删除**。加 reload 后 31711 正常渲染出自己的正文，判回 alive。
     影响面：byd 6,362 + kuaishou 2,830 个 active 岗的 jd_url 都是「同一个 base + 不同 hash」，
     两者都在 `_BROWSER_ADAPTERS` 里、每天带 `--apply` 跑。
     ✅ 防：`audit_dead_links.is_same_document_nav(prev, url)` —— 只在真的同文档跳转上多花一次
     reload；浏览器重建 / 上一跳失败时清空 prev。回归钉在 `crawler/test_audit_hash_route_nav.py`。
     📌 同一个机制在农行 adapter 里也咬过一次（「换机构必须 page.reload()」，见目录结构里 abchina
     那条）——**凡是自己拼 hash 路由做连续导航的地方都要想到它**，不只是这两处。
     ⚠️ **农行（abchina）刻意没加进浏览器巡检**：它的死岗文案是「该岗位已过期」，`DEAD_MARKERS`
     一条都不匹配 → 光加 adapter 只会白烧浏览器预算；而「先加文案、后修导航」的顺序会当场误杀
     （2026-09-06 实测：不 reload 时 3 个在招岗全部读到上一个岗的过期页）。
   - **国有大行 + 中国移动已有逐岗探活（2026-09-06 接入，此前这五家 9,292 个 active 岗只进不出，实测同日）**：
     spdb/icbc/ccb/bankcomm/cmcc 进 `ENRICH_REGISTRY` + liveness-sweep matrix；判死信号真伪 id
     live 对拍、**一律双条件**（见 `crawler/enrich.py` 各 `_detail_xxx` 注释）。三条诚实边界：
     · **浦发的详情页不随撤岗消失**——刚掉出列表、截止日已过的岗仍渲染完整 JD，2020 年的老岗也在
       → spdb 只抓得到「id 彻底不存在」，抓不到「岗位已关闭」，别指望它下架多少岗。
     · **交行不许拿详情接口的错误码判死**：不存在的 id 返 `JUMPTESTBP9001`「系统异常」，而那是它的
       **通用**异常码（业务参数少包一层 params 也返它）→ 判死改走「按 positionId 精确查列表、
       社招校招两个板块都查不到」两跳确认。别把它「简化」回一跳。
     · ⚠️ 同批补上 `chnenergy`：它 2026-09-05 就进了 ENRICH_REGISTRY 却漏加 sweep matrix，
       只被补正文、一次没探活过。`crawler/test_state_bank_liveness.py` 现在断言「注册表 ⊆ matrix」。
   - **北森（beisen，库里最大一族 11.7 万 active）已有逐岗探活：详情接口 `Data.Status==2` = 已停止招聘（2026-09-23 接入）**：
     ❌ 此前只有浏览器巡检一条撤岗路径、list-absence 还在 observe → 实测 16,366 个已停招的岗挂着（中国人寿 616 条最早 6 月就掉出列表）。
     ✅ 依据三方印证、不是猜：① 北森标准门户前端代码 `if (2 === Data.Status) location.replace("/job/empty")`；
     ② 全集对拍——库里 114,565 个带 jobAdId 的岗逐个问 + 275 个租户列表全量翻完（14.6 万行 Status 全是 1）：
     Status=2 却在列表 0 条（唯一 1 条是拉列表后刚下架的时间差）、Status=1 却不在列表 2 条；
     ③ 176 个租户各抽 1 条真渲染，167 家显示「当前职位已停止招聘」。
     ⚠️ 不存在的 id 返 `Code=500`「参数错误」是**通用**文案，不判死；接口 404 = 这个 host 没这接口，**不许走 `_raise_if_gone`**。
     ⚠️ 中国人寿 / 银河证券 / 通威 / 泰康 / 长安 的页面模板**不读 Status**，在招和已停长得一样——对它们只能靠「Status=2 + 列表已无」。
     ⚠️ 老版 CMS 门户（`/zpdetail/{数字}`，约 3 千岗）无 jobAdId、判不了 → unknown 留给浏览器巡检，**beisen 别从 `audit_dead_links` 撤**。
     巡检靠强信号「此职位已停用」判死（撤岗页仍渲染标题，缺这句就判 alive）：2026-09-24 前没收这句，85 个停用岗一直挂着；
     补上后全集对拍停用 85/85、在招误判 0；定向巡检 85 条全部下架、误杀 0（首轮 3 条 CI 页面超时落 unsure 不下架，重跑补上）。
     📄 `enrich._detail_beisen` + `enrich_backlog.EXPIRE_RATIO_GUARD`（本轮判死 ≥50% 即熔断，全集模拟峰值 15.7%）+ `crawler/test_beisen_liveness.py`。
   - **🚫「列表里没有」≠「已撤岗」——除非先证明该列表是全集（2026-07-29 立碑，差点误删 460 个在招岗）**：
     list-absence 撤岗（`supports_absence_liveness` + `jobs_db.sweep_absent_jobs`）的前提是**该源的列表接口返回岗位全集**（feishu/beisen/bytedance 是验证过确实返全量才开的）。
     ⚠️ **绝不能从「列表条数 ≪ 库里 active 条数」反推「差额都是死岗」**——这个差额有两种成因、处置**完全相反**：① 死岗堆积（该清）；② 列表接口本身只返子集（一清就是删在招岗）。
     踩坑实录：见华为列表接口只返 13 条而库里 460 个 active，就推断其余是死岗并开了 absence（commit 675e459）→ 逐个核验后**460 个全部在招、0 个撤岗**（`getJob/newHr` 返的是筛选过的子集；例 jobId=30153 列表查不到但详情接口返完整岗位名+正文）。已在 `c9a7e73` 撤回并加断言测试钉死。当时唯一挡住的是 97% 缺席越过 `max_expire_fraction=0.5` 安全闸 → sweep 主动跳过，未实际删数据；**但那道闸是兜底不是设计，别指望它**（存量降到列表规模 2 倍以内它就不拦了，而 expired 当天会被 purge 永久删除）。
     ✅ 正确姿势：拿不准列表是否全集，就走**逐岗** detail 判死（`ENRICH_REGISTRY` + liveness-sweep）。华为即用此法：`…/portalpub/getJobDetail/newHr?jobId={id}&dataSource={ds}`（httpx 零鉴权，既判死又补 `mainBusiness` 正文）；判死要求「jobname 空」**且**「有值字段数 ≤8」双条件（在招 ~32 个字段有值，不存在的 id 返 200+109 字段骨架但只 5 个有值），半截数据一律不判死——**宁可漏判不可错杀**。
     📌 通用规矩：**不可逆操作（标 expired / 删行）前，核验样本量必须匹配影响面**——要清 447 行就得核验 447 行，抽查 2 个不算数。
     🔎 **怎么判自己在哪一种：`crawler/audit_stale_active.py`（只读，没有也不会有 --apply）**。
     判据是**源级**的「这个源最近还抓到过东西吗」，分三桶（2026-09-04 全库实测）：
     **A 源近 2 天仍在抓 → 不可判死**，占 92%（1,213 源 / 113,240 行陈旧）——源活着、我们也在抓，
       某个岗没被再看到最可能是**列表没翻完**（Amazon 12,470 行里 7,761 行、Wells Fargo 6,958 里 4,967），
       这是**抓全率**的活（paginate_all / reported_total 契约），不是探活的活，更不是去重的活；
     **B 近 14 天抓过但已停几天**（5 源 / 146 行）→ 观察；
     **C 整源停 ≥14 天 → 源健康问题**（93 源 / 9,729 行：武田制药 2,113 行停 34 天、凯莱英 70 天、
       中国钢研 77 天）→ 去修源。**源坏了 ≠ 对方撤了岗**，仍不能因此判死。
     ⚠️ 三桶只用来**区分成因**，任何一桶都不构成改 status 的依据；要判死只能逐岗 detail。
   - **expired 死岗 = 永久删除回收空间（2026-06-18 定方针）**：expired 是 sweep/dead-link-audit 逐岗探活**确认撤岗**，不保留 → `purge-expired.yml`（每日 UTC 02:30）`DELETE … WHERE status='expired'` + 普通 VACUUM 持续清。`removed`（抓取漏看可复活）不动。db_size 真正缩小（还盘）由 `maintenance-vacuum -f full=true` 删大批后手动跑。**（Phase 1 已于 2026-06-19 切完：jobs 热表已在自建香港 PG，Supabase 只留 Auth/sources/crawl_runs/用户小表；运维见 `docs/jobs-database-runbook.md`。原引用的 plans/2026-06-14-jobs-database-refactor.md 在库里不存在，已改指 runbook。）**
     - **⚠️ Phase 1 已切（2026-06-19）：`jobs` 热表现在在自建香港 Postgres 17 上，不在 Supabase。** 腾讯云轻量 2C2G/40GB，免备案。连接串（含公网 IP / 账号 / 密码）只存 **`JOBS_DATABASE_URL` secret**（GitHub Actions + Vercel）+ 本地 `.env.local`；**仓库公开，host/IP/账号/密码一律不入库、不提交、不写进文档**。Supabase 现只管 Auth / `sources` / `crawl_runs` / `discovery_runs` / 用户小表 / 洞察表。
       - **边界层**：app 读+写都走 `lib/jobs-store/`（`client.ts` pg 连接池 / `search.ts` 复刻 FTS / `read.ts` 读：list/count/companies/byIds/byUrls/byCompanies/recallByPrefs / `write.ts` 写：canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db），爬虫写走 `crawler/jobs_db.py`（psycopg2）。两端都 **gated**：配了 `JOBS_DATABASE_URL` 用香港库，否则回退 Supabase（本地无 env / 回滚安全）；**写入端 HK 报错不回退 Supabase**（避免写空库孤儿数据）。**sources/crawl_runs 永远走 Supabase**（jobs_db 只管 jobs）。
       - **schema 在 `jobs-db/schema.sql`**（从生产 `pg_dump` 忠实重建：表 + canonical 触发器 + bigram FTS(search_doc/search_tokens/GIN) + count_valid_active_jobs/active_companies/active_job_counts_by_company + 全索引 + pg_trgm）。2026-07-02 海外扩展新增 `jobs.country_code`、`jobs.job_scope`（默认 `domestic`）与 `jobs.sponsorship_signal`；`job_scope=domestic` 只覆盖大陆+香港+澳门，`overseas` 覆盖本期放开的 US/SG/Remote，台湾维持不抓、不归入任一范围。改 schema → `gh workflow run jobs-db-migrate`（幂等 apply 到 `JOBS_DATABASE_URL`）。
         ⚠️ **它会拿 jobs 的排他锁，库里有「事务开着没提交」的会话时会冻住线上（2026-09-23 实测）**：❌ schema.sql 开头的 `alter table jobs add column if not exists`
         列已存在也要排他锁，排在一个 idle in transaction 14 分钟的会话后面等锁；**排队中的排他锁挡住之后所有读写 jobs 的查询**，线上卡约 6 分钟，
         runner 断线后服务端那条 alter 还在等，手动 `pg_cancel_backend` 才解开。✅ workflow 已加 `PGOPTIONS=-c lock_timeout=10s`（拿不到锁就红灯重跑）。
         只新增一张独立表时不必跑整份 schema：把那条 `create table if not exists` 原文带 `set lock_timeout` 单独执行即可（不碰 jobs 的锁）。
       - **沙箱直连香港库验证**：见 [[job-radar-live-db-access-from-sandbox]]（dangerouslyDisableSandbox + source .env.local + 用户 Homebrew psql）。
         🚫 **脚本 / 临时对拍里调 psql 一律走 `scripts/lib/psql.js` 的 `runPsql`（Python：`crawler/psql_env.run_psql`），别把连接串当 psql 参数**（2026-09-24 立）：
         ❌ 2026-09-23 一个照抄 `match-eval` 旧写法 `execFileSync("psql", [JOBS_DATABASE_URL, …])` 的对拍脚本连接超时，Node 报错 `Command failed: psql <完整 argv>` 把密码打进了会话记录；运行中 `ps` 同样看得见。
         ✅ 助手把 URL 拆成 PGHOST/PGPASSWORD… 环境变量、报错只带脱敏后的 stderr；`tests/psql-env.test.js` 扫 scripts/ lib/ app/ crawler/ 禁止再直接 spawn psql。workflow 里的 `psql "$JOBS_DATABASE_URL"` 未改（日志有 secret 掩码、runner 用完即焚）。
       - **改 jobs 列/索引/canonical**：三处仍要同步（lib/canonical-url.js / crawler/normalizer.py / **jobs-db/schema.sql 的 SQL 函数**，不再是 supabase migration 144）。
       - **app 端 jobs 读+写已全部落香港库（2026-06-19，commit b742ee6/28ddddb）**：原「discovery/enrich 读仍在 Supabase」遗留已清。新增 app 写层 `lib/jobs-store/write.ts`（canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db）；discovery/search 的 upsert、enrich 写回、refresh 选区、insights Tier1 派生全 gated 走香港库（11 个 `.from("jobs")` 文件全 gated，写入端失败不回退 Supabase 避免孤儿数据）。Supabase `jobs` 已清空（2026-09-05 再次 TRUNCATE：90MB / 34,965 行 → 136kB。⚠️ 上一次「已清空」的记载与现实不符——那批行是 Phase1 切换日 2026-06-19 的快照，一直躺到 2026-09-05 才被发现，期间**文档说空、实际有 3.5 万行**。危害不在占用空间，在于 gated 兜底一旦触发会**静默服务两个半月前的数据且不报错**。复核过再删：无任何外键指向它，642 行 `job_actions` 没有一行引用它）；gated 兜底仅在未配 `JOBS_DATABASE_URL`（本地/回滚）时回退它。**移除 gated 兜底前仍请线上确认稳定**（见 docs runbook）。详见记忆 [[job-radar-phase1-ci-jobs-db-wiring]]。
   - **薄卡（无 JD 正文）= 低质量**：能富化的（httpx 源）靠 `enrich-backlog` 补正文；moka 浏览器源已打通逐岗渲染补正文（`scripts/backfill_moka_summaries.py`，2026-06-18 修好取数超时）；补不到正文的薄卡只算「在库」、不算「有效在招」、不进首页计数。
     - **⚠️ 富化补好的 summary 不许被列表重抓抹掉（2026-06-20 查实=moka 1% 覆盖真因）**：moka 列表 adapter 出 `summary=None`，而 upsert 的 UPDATE 旧实现 `summary=EXCLUDED` 会把每晚 backfill 补好的 ~8800 条全抹回 NULL（次日列表重爬即覆盖，count 永远上不去）。修法=`crawler/jobs_db._PRESERVE_IF_EMPTY`（summary/job_type/experience/education/deadline）UPDATE 时空值用 `COALESCE(NULLIF(%s,''),列)` 保留旧值；`lib/jobs-store/write.ts` 同口径（summary/job_type）。**改 upsert 写法务必保住这条不变量**，否则 moka/byd/外企富化全部前功尽弃。Supabase 兜底 `crawler/db.py` 走 PostgREST 批量 upsert（null-union 语义无法 COALESCE，且 prod 不走它）暂未加此保护。
   - **诊断先跑 `db-report.yml`**（只读 psql：status 分布 / active 有效率 / never_checked / 分 adapter）。任何「岗位变多/变少/质量」的判断先看它的真实数字，别凭感觉。

## 工程化底线：本产品不是 demo（2026-09-03 创始人定调）

创始人原话口径：**「我在 vibe coding，但不是纯 demo 和自嗨，要尽可能工程化、按软件工程的思路打造。」**
判据是**七块基石有没有真的建立**，不是「页面能打开」：
数据结构与 schema / 索引 / 缓存 / 任务队列与调度 / 会话与鉴权 / 传输与密钥安全 / 日志与可观测性。

本仓库对应的落地口径（都有踩坑实录，别退回去）：

| 基石 | 本项目已建立的做法 | 反面（曾经踩过） |
|---|---|---|
| 数据结构 | 岗位/洞察走**类型化列 + 枚举 + 约束**，派生量物化成列（`job_scope`/`grad_class`/`canonical_jd_url`） | 把结论塞进一段 LLM 散文，没法索引、没法筛、没法治理 |
| 索引 | 大表查询先看 EXPLAIN；前导列顺序对齐排序键；分区 GIN（校招/实习） | `ilike any('%x%')` 全表扫 39 万行还以为走了索引 |
| 缓存 | 跨实例用 `unstable_cache` / CDN（一律经 `lib/request-safe-cache.requestSafeCache` 定义，见表下）；进程内缓存只当同实例并发去重 | 进程内 Map 当缓存用，serverless 多实例命中率≈0 |
| 队列与调度 | 重活进 GitHub Actions + `ops_runs` 台账，cron 错峰、分片、限并发护连接 | 长任务塞进请求路径（点击探活 5-8s 已废弃） |
| 会话鉴权 | 本地 JWT 验签 + 模块级 JWKS 缓存，中间件注入用户头 | 每请求跨洋 `getUser()`（566ms→0.7ms） |
| 安全 | 密钥只进 Secrets/env；公开仓 pre-commit 门禁扫敏感信息 | 绝对路径/IP/真名进公开仓（不可撤回） |
| 可观测 | 每条链写 `ops_runs`（含零产出指标）+ ops-watchdog 规则 A~F | 「绿灯零产出」连续 7 天无人知 |

🚫 **`unstable_cache` 在带中文查询串的请求里读写全失败（2026-09-23 立）**：
❌ 线上 `/insights?q=腾讯` 每次都重建索引（6.2s），连一个无关参数 `?zz=腾` 也是；`?zz=1` 21ms 命中、4 个实例拿到同一份。
✅ 根因：Next 15 在请求里调用 `unstable_cache` 时，把「路径 + **解码后**的查询串」拼进缓存条目名，Vercel 数据缓存拿它读写，
带非 ASCII 字符就静默失败，不报错。缓存键本身与 URL 无关，所以只有中文请求一直落空。
✅ 防：定义处一律用 `lib/request-safe-cache.requestSafeCache(fn, keyParts, opts)`（= `unstable_cache` + 每次调用自动经
`lib/cache-outside-request.callOutsideRequestScope` 跳出 request 作用域，缓存键不变）；`tests/request-safe-cache.test.js`
契约禁止 app/ lib/ 直接调 `unstable_cache`，`tests/cache-outside-request.test.js` 用 Next 真实的 `unstable_cache` 截条目名断言，升级 Next 会先红。
这是 Next 官方缺陷（vercel/next.js#76286），修复只进了 16.x，15.5 线到 15.5.26 都没 backport；升到 ≥16.3 后这层可删。
⚠️ 同一个 helper 还绕开另一个坑：条目过期后的后台重建，**接口路由（Route Handler）会等它跑完才结束响应**（Next 15.5
app-route 模板把同一个 promise 既交给 waitUntil 又交给 sendResponse），线上取索引 56ms、响应 6.2s；helper 把它挪给 `after()`。
📌 纠错（同日）：上一行原写「全站 14 处目前只改了洞察索引，其余未改」——已于 2026-09-23 全站统一换成 requestSafeCache（现 15 处）。
搜索的真实总数计数同日 A/B 实测：同一条计数只多挂一个无关的 `&zz=中`，尾段 6~52ms → 678~1,738ms；它还把用户隐藏岗拆出了缓存键
（总数 = 共享计数 − 隐藏岗落在条件内的条数，逐值相等），否则每个有操作记录的登录用户各一个键，缓存照样白搭。

**每次交付前自查（缺一条就别说做完了）**：
① 先量后改，有改前改后真实数字；② 新数据先想「怎么建模成可索引可筛选的字段」，再想怎么展示；
③ 边界/错误/并发/幂等/重跑都想过；④ 后台链路有台账和告警口径；⑤ 四件套 + lint 全绿并**真的跑了**。

⚠️ **①的量必须双向，不允许只报净值**（2026-09-05 立）：同一次改动常同时存在**两个相反方向**的
错误，只验一个方向，另一个方向的新错误会被「净值向好」洗掉——总数看着改善了，其实是两个错误
互相抵消。实例：抬列表上限聚合报「26 源多抓 3.1 万」，**同一轮里 20 个源少抓了 461 个岗**；
补美国地名词典正向修「美国岗被判成国内」12,525 个，反向 `", ca"` 裸子串把 `Montreal, QC, ca`
（加拿大）、`", ma"` 把 `Warsaw…PL`（波兰）**判成美国** 2,079 个。
→ 动手前先写下「这个判据可能往哪两个方向出错」，两个方向各写一个计数查询；
→ 验收报**分项**（A→B 多少条、B→A 多少条），**不许只报净值或总数**；
→ 聚合指标向好时，必须同时确认**没有分项在回归**（逐源/逐类对拍，不是抽样）。

## 结构性审计：没声明「正常长什么样」的东西，本身就是告警（2026-09-19 上线）

**为什么有它**：此前 16 条告警规则里 14 条只看「任务有没有在跑」、0 条看用户体验；9 条定时链路不留任何运行记录；
「在招总量」全库一天历史都没有。更糟的是，因为期望从没被显式写下，**「哪些东西没有期望」也无从枚举**。

| 组件 | 在哪 | 干什么 |
|---|---|---|
| 期望清单 | `crawler/audit_contract.yaml`（87 条：数据 14 / 体验 22 / 链路 35 / 老告警桥接 16；原写 85 条是 09-19 上线时的数，09-23 复核更正） | 每条声明 `normal`；`name/why/action` 是**人话**，晨报直接念 |
| 执行器 | `crawler/audit_runner.py` + `structural-audit.yml`（每日北京 08:50） | 逐条量，写 `audit_results`（Supabase，迁移 281/282）；`unique(check_id, run_date)` 一天一行 = 趋势表。可选 `detail_sql` 列出「具体是哪几处」进 `detail.findings`，晨报 ⑤⑦ 据此点名；它失败不改数值与判定 |
| 覆盖率差集 | `crawler/audit_coverage.py` + `audit_exemptions.yaml` | 左边**自动枚举**（带 cron 的 workflow / 写 ops_runs 的模块 / jobs 表列 / 走查指标），减去有期望的；上线时 68 条 → 现 14 条（全是 jobs 列） |
| 老告警桥接 | `ops_watchdog.py` 的 `publish_audit_bridge` | 16 条规则**判定与阈值一字未动**，只把每条的命中数 + 明细写进同一张表（`detail.findings[].title` 与 issue 标题逐字一致） |
| 晨报 | `crawler/morning_digest.py` + `morning-digest.yml`（北京 09:30） | 每天必发，绿灯也发（绿灯邮件就是心跳）；报「昨天全天」 |
| 外部心跳 | `audit_runner.ping_heartbeat`（Healthchecks.io，只挂执行器 1 个） | start / success / fail 三态；`workflow_dispatch -f force_fail=true` 做故障演练 |

**改这套东西务必保住的不变量**：
- **查询失败 → `verdict='error'` 且 `value` 为 NULL，绝不写 0**（表约束 `(verdict='error') = (value is null)` 钉死）；
  清单里有、当天却没有行的检查 = 「今天没查到」，晨报⑧段逐条点名并参与灯色。ok 也每天落库——那就是历史。
- **新增定时 workflow / 写台账的模块 / jobs 列 / 走查指标，差集会自动多一条**；消音只有两条路：写期望，或在
  `audit_exemptions.yaml` 带**非空理由**豁免。jobs 列的覆盖靠检查项显式 `covers: [列]`（必须真出现在该条 SQL 里、
  真存在于 `jobs-db/schema.sql`），**不靠「列名在 SQL 文本里出现过」**——`status` 出现在几乎每条 where 里，按文本猜会永久假绿。
- **红灯只留给「用户可见损坏 / 供给来源大面积塌」，单个源坏最多黄灯**（创始人定）。老告警里只有 `rule_d`（关键任务超期）
  与 `rule_k`（一整类来源产出骤降）是 critical；`severity=info` 的不染灯。灯色以**清单里的 severity** 为准，不认落库快照。
- **假绿体检（连续 7 天报成功零产出）不数「休眠中的校招/实习入口」**（近一年出过岗、这一批没开，2026-09-23 创始人授权），
  它们单独记在 `exp.fake_green_campus_dormant`（info 不染灯）。❌ 代价：公司换了新校招门户、旧门户留着不关，和休眠长得一模一样
  （09-20 修的知乎等 4 条全是这一类，放新口径下会全被藏掉）。✅ 防：Moka 校招门户 0 岗时问一次平台别名，别名指向另一期**且那一期真有岗**才记 failed 带新地址（只看别名不同会误报：
  一个租户常同时开几个门户，华虹的别名还指向空模板）
  （`MokaAdapter._raise_if_campus_portal_superseded`，由「连续失败」老告警接住）。**两者是一对，删掉后者前者就会藏坏源**；
  其它平台还没有同类识别。回归钉在 `crawler/test_fake_green_sources.py`。
- **`name/why/action` 的读者是非技术创始人**：不许出现表名 / 模块英文名 / SQL 词 / 「GitHub Actions、日志、索引、adapter」；
  `action` 写成他能做的动作（「把这条转给 Claude，让它查…」）。阈值没有历史依据的一律 `calibrated: false`（现 84/87 条），
  攒够 30 天换分位数，**禁止编一个看着合理的数字却不标它**。
- 周任务的链路检查窗口是 8 天；`campus-crawl` 那条按月份条件化（月份集合复用规则 O）。
  ⚠️ `enrich-crawl` / `dead-link-audit-new` 与另一条 workflow 共用台账模块名，**一条停了另一条会掩盖它**——豁免理由里写的是真缺口，不是「不用管」。

**搭的过程中踩的坑（都是「没真跑就看不见」的那一类）**：
- 🚫 **体验层 SQL 里的事件名 / 取值必须能在产生它的源码里 grep 到**。❌ 慢搜索那条曾把耗时桶写成 `'slow','very_slow'`（猜的），
  真实取值是 `3000_9999ms` / `gte_10000ms` → 恒算出 0，一条**永远绿的假检查**（真实值 27.1%）。
  ✅ `test_every_experience_layer_literal_traces_to_source` 逐个字面量回溯源码，抽不到来源就红。
- 🚫 **Resend 必须显式带 `User-Agent`**。❌ 第一封真发连败三次 `error code: 1010`：Resend 前面是 Cloudflare，urllib 默认的
  `Python-urllib/x.y` 被按客户端特征拦掉，请求根本到不了 Resend、与 key 无关。单测注入的是假 opener，永远测不到这层。
  ✅ `morning_digest.RESEND_USER_AGENT` + 源码级断言。
- 🚫 **用 mock 数据排的版不算验证**。❌ `gh issue list --json comments` 返回的是**对象列表**，夹具里写成了数字 → 真跑时整段原始评论
  塞进正文，单行 4 万字符、整封 325KB。✅ 夹具用真实形状 + 单行 ≤300 字符 / 整封 ≤30KB 的兜底断言。
- 🚫 **dry-run 写的台账不许被读成「已送达」**：「上一封是否送达」只认 `metrics.mode == "sent"` 的行。
- 🚫 JS 与 Python 两侧写 `ops_runs` 的 `run_date` 都必须按 **Asia/Shanghai**（JS 曾用 `toISOString()` 取 UTC，每天 8 小时落错桶）。

## ⚠️ 撤岗身份：purge 删行前必须先立墓碑（2026-09-08 立，修 F1）

`purge-expired.yml` 每天 `delete from jobs where status='expired'`，**近 14 天实测均值 2,871 行/天、
合计 40,199 行**。而 `job_events.job_id` 是 `ON DELETE CASCADE` → CLOSED 事件跟着一起没。
于是 `jobs_db._find_existing_id_by_canonical` 按 canonical 查不到任何行 → 走 fresh INSERT →
同一个岗以**全新 uuid + 全新 first_seen_at** 变回 active。sticky-expired 只保护「行还在」的情况。
配合 wt/hotjob 列表本来就夹带已关闭岗（52%/71%），这条链是真能跑通的。

- ✅ 防：`jobs-db/schema.sql` 的 `job_closures` 墓碑表；purge 的**墓碑写入与删除在同一个 `psql -c` 里**
  （= 同一事务），墓碑失败就整体回滚、一行都不删。**别把它拆成两个 `-c`**——那是两个独立事务。
- ⚠️ 立墓碑要排除「同 canonical 还有 active 行」：canonical 唯一约束只作用于 active，
  已关闭旧行与在招新行可并存，给它立墓碑会把一个在招岗记成已关闭。
- ⚠️ **刻意只记不拦**：命中墓碑就拒收 = 把公司真重开的岗永久删掉，违反「宁可漏判不可错杀」。
  `jobs_db.mark_reopened_from_closures` 只累加 `reopen_count`/`reopened_at`。
  **复活率是多少，查 `job_closures` 就知道**——在拿到这个数字之前，任何拦截策略都是拍脑袋。
- 回归钉在 `crawler/test_job_closures.py`（含「同一事务」与「不加外键」的契约断言）。

## ⚠️ /jobs 默认排序（sortBy=match）冷路径：三层病根都量过了，别再凭感觉砍列（2026-09-08 实测，2026-09-18 更新）

线上 `https://www.myjobradar.top/api/jobs/search` 实测（匿名、可 curl）：

| 请求 | TTFB |
|---|---:|
| `sortBy=newest&limit=10` | 3.25s |
| `sortBy=match&limit=10`（**= 打开 /jobs 的默认态**） | **14.1~16.6s** |
| 紧接着同条件 `limit=60`（命中进程内 5 分钟缓存） | 0.56s |
| `sortBy=match` + `city=北京` | 4.37s |

**别去查数据库和连接池**：同文件注释里的 EXPLAIN ANALYZE 是 **45~73ms**，函数与库都在 `hkg1`、不跨洋。
大头是**把 28,000 行候选传回函数**——其中 `summary` 占 15MB、其余关键列 4.3MB。
- 🚫 `summary` 砍不掉：`classifyJobFunction` / `keywordMatchTier` 的兄弟组排除都要读它，
  砍了是**静默改坏匹配精度**（不报错、不变慢，只是推荐变差）。
- 🚫 别指望那个进程内 Map 缓存：serverless 多实例命中率≈0，上表 0.56s 那一行是同实例连打才有的。
  也**别改成 `unstable_cache`**：Next 数据缓存单条约 2MB 上限，19MB 的候选集根本放不进去。
- ✅ 真正的解法是**物化派生字段**（`job_function` 等落成列，写入时算好，照 `recruitment_category` 的先例），
  让候选取数根本不需要 summary。属 schema + 全表回填 + 等价性验收，**单独立项**，别顺手改。
  📌 **`jobs.job_function` 已于 2026-09-15 物化上线**（列 + 触发器 + 回填 535k 行 + `--check --all` 对拍 0 差异；
  见「校招专区首屏」段与 [[job-radar-campus-job-function-materialization]]）。**校招链已切读该列**；
  但**此处 `/jobs` 主搜索冷路径尚未切**（`keywordMatchTier` 的兄弟组排除仍读 summary）——要砍 summary 得先确认
  匹配所需的其它 summary 用途都能用列替代，仍属单独立项，别顺手改。
  📌 **2026-09-17 切了一半：正文「按需传」**（`lib/jobs-store/search.ts` 的 `candidateSummaryExpr`）。不是砍 summary，
  是只给「打分/精筛真会读正文」的行传：scoreJob 的职能门必拒的行（用户目标职能是产品时，研发/销售/制造… 占 active 77%）
  正文不传；匿名且没开 keyword/jobRole/experience 精筛时一行都不传；命中页卡片摘要由 `hydratePageColumns` 按 id 回补。
  等价性靠三件事：① `classifyJobFunction` / `recruitmentCategory` **有物化列就认列**（`lib/china-keyword-expansion.js`，
  分类所有权归数据库的最后一块，此前 /jobs /today 都在用截断摘要重算、与卡片徽标打架）；② 排除词下推 SQL
  （`appendExcludeWhere`，与 scoreJob 同字段集，顺带让撞上限的计数不再因排除词弃权）；③ 读正文的三个精筛任一生效就退回全传。
  真库量：newest 28,000 行正文 20 MB → 产品用户 4.1 MB / 研发用户 7.7 MB / 匿名 0。
  ⚠️ 改 `CANDIDATE_BASE_COLUMNS` / `HYDRATE_COLUMNS` 必须保住「summary 在回补列里」，否则卡片没摘要
  （`tests/jobs-store-search-summary-gate.test.js`）。线上 TTFB 数字见 `docs/reviews/2026-09-17-core-features-adversarial-review.md`。
  📌 **2026-09-18 登录态切完：SQL 粗排 + 1000 窗 + 收窄条件走索引**。三层病根按先后各自量过，别只记一层：
  ① **带宽**（2026-09-17 psql 裸拉 8MB 要 42.9s ≈ 1.5Mbit/s）→ 解法是**少传行**：登录 match 走 `prescoreOrderBy`
  （方向 30 / 城市 20 / 公司 15 / 7 天 10，每项 `is true`）只回 1000 行且不传正文（原 2.8 万行 20MB → 0.8MB）；
  ② **粗排 SQL 本身全表扫**（2026-09-18 分段账本 fetch 5.5s 只拉 1000 行；EXPLAIN 是 Parallel Seq Scan 13.5 万 buffer、
  库上 2.3~2.6s）→ 候选查询多带一条 `(search_doc @@ 方向 tsquery or first_seen_at > now()-7d)`，GIN + `(status,first_seen_at)`
  两个索引 BitmapOr，同画像 493ms；**只进候选 SQL 不进 conds**，计数口径不变。带城市/关键词的 FTS 路径同一套（8000 行 → 1000）。
  ③ **函数实例**：每次请求常落到不同实例，进程内 5 分钟缓存对首屏基本无效（三连打三个实例）。
  等价性尺子：`JOBS_MATCH_PRESCORE=off` 退回全窗精排取真值，第一页 60 条逐用户对拍（数字在报告 §10）。
  ⚠️ 没有方向词的用户（画像无 target_roles）粗排只剩城市/公司/7 天，仍是全表扫——量级同旧，不算回归但也没提速。
  （2026-09-23 核：近 7 天 80 次真实搜索里**没有一次**落在这条路上——慢的是下面第四、五层，别再把「慢」默认归到这里。）
  📌 **2026-09-23 第四层：规划器估错行数**（审计 `exp.search_slow_rate_7d` 33.75% 起查，80 次搜索全集按用户画像逐条复现）。
  ❌ 「不加筛选 / 只选校招 / 只选实习」只取最新 1000 行，库上却 Parallel Seq Scan 13.9 万 buffer、0.6~1s（冷缓存更久）。
  ✅ 根因：`coalesce(job_scope,'domestic')='domestic'` 是表达式、没有统计信息，规划器按默认 0.5% 估（实际 67%）→
  以为按时间索引要翻很久，改走整表扫再排序。改写成逐值等价的 `(job_scope='domestic' or job_scope is null)`（`lib/job-scope.ts`）
  → Index Scan 1.5k buffer、4~196ms。`listLatestActive`（/jobs 首屏 SSR）同一写法同时受益。
  🚫 **新写 where 别用函数/coalesce 包列**，写完先 `EXPLAIN` 看估计行数和实际行数差几个数量级。
  📌 **第五层：招聘类型没索引 + 库机内存装不下数据**（2GB 内存 / 2.26GB 数据，冷缓存每回表一行 0.1~0.3ms）：
  「只选实习」要回表 2.9 万行才凑满 1000 行（热 76ms / 冷 2~4.6s）。加 `idx_jobs_active_recruitment_first_seen`；
  无粗排的校招/实习拆两支 `union all`（`recruitmentUnionSql`），粗排收窄按类型拆三支（`prescoreOrderBy`）——
  规划器不会自己把 OR 分配进去，写成 `(方向 or 7天) and (该类型 or 待回填)` 计划不变。
  另：选了招聘类型时 `exactTotalWhenCapped` 先 `exists` 查未分类行——此前全表 count 0.6~2.4s 算完再被门④丢掉。
  等价性：31 种真实搜索组合、改前改后交替两轮、并列按 id 定序后第一页 60 条逐位相同（不定序时旧代码自己两轮都对不上）。
  ⚠️ **剩下的大头是真实总数计数**（`exactTotalWhenCapped`，在关键路径上）：校招专区冷 1.3~2.3s、北京 / 上海冷 3.6~5.2s；
  它跑不跑取决于「有没有该类未分类行」→ 同一段代码随回填进度在快慢之间切换。它的跨实例缓存曾对所有带中文参数的请求
  （校招、实习、任何城市）全部不命中——根因与修法见上文「`unstable_cache` 在带中文查询串的请求里读写全失败」那块碑（同日修）。
  数字与残留见 docs/reviews/2026-09-17 §13。

## /today 召回加了第四层 function，层内先保标题命中（2026-09-17，18 个画像真库对拍）

`lib/jobs-store/opportunities.ts` `buildRecallSql`。三处改动与各自的实测依据：
- **方向层窗口先保「用户原词在标题里」**（城市桶之后、最新之前）：方向层命中集常远大于份额，此前只按城市→最新截断，
  精确标题命中却更早首见的岗被砍在窗外，窗里塞的是标题只沾泛词、到 stage-2 必被 role_mismatch 拒掉的岗
  （上海「机械工程师」召回 1,796 行只剩 20 可展示）。
- **国内画像填了城市 → role/company 层 where 直接收窄到「城市命中或城市未知」**：location mismatch 在 stage-2 是硬拒，
  此前这些行只是排到层尾，城市行取完后照样填满份额（前端@深圳 1,642 召回里 632 行 location_mismatch）。
- **第四层 `job_function = any(目标职能)`**（权重 3，cityNew 3→2）：方向层只看 search_doc（无正文），
  「标题泛、正文才写方向」的岗和词库没覆盖的非互联网岗它捞不到；`job_function` 列是标题+正文分类好的。
  ⚠️ **形态必须是 `job_function = any(...) and search_doc @@ 城市tsquery`（BitmapAnd 两个索引）**，
  三种反例都试过：城市门带 `or location is null` → GIN 用不上、逐行算 tsquery 3,048ms；`location ilike` 逐行过滤整桶 2,014ms；
  加 30 天窗照样 2.2s 且长尾岗大半被窗砍掉（土木 0→6 掉回 0→1）。现行 生产制造∩上海 182ms、研发∩深圳 398ms。
  配套复合索引 `idx_jobs_active_job_function_first_seen (job_function, first_seen_at desc) where active`
  （2026-09-17 已 `create index concurrently` 上线，schema.sql 同步）。
- 结果（可展示岗，`scratch w2-measure` 复跑口径）：**13 升 / 4 降 / 1 平**。长尾从无到有：土木 0→3、教师 3→6、机械 20→40；
  4 个降的是算法/数据/市场/财务（−44~−93，各仍 ≥475，远超每日 20~30 张）——方向层份额从 5/8 降到 5/12 的代价，
  双向都报、别只看净值。in-DB 耗时 127~802ms（改前两例 250/287ms）。
- 顺带闭掉 F8 残差：`RECALL_COLUMNS` 带回 `recruitment_category / recruitment_explicit / job_function`，stage-2 认列。
  此前用 300 字摘要重算 → 线上给社招岗写「校招岗位」的匹配理由。
- /today main 区加相邻散列（`spreadByCompany` 复用 /jobs 的滑窗，任意 6 张同一家 ≤2）：公司配额只限总数不限相邻，
  线上前 8 张全是字节跳动。⚠️ `spreadByCompany` 默认读顶层 `company`，Opportunity 的公司在 `job.company` 下，
  必须传 `keyOf`，否则所有项同一个空键、散列等于没做（tests/opportunity-grouping 钉着）。
- **目标城市填省 → 按全省地级市解析，召回城市门与 stage-2 资格门读同一份展开（2026-09-23）**：
  ❌ 填「陕西」「广东」的用户只看得到 location 字面写着省名的岗：广东画像看不到深圳 / 广州 / 佛山（全库在招 +36,623 个），
  陕西画像前 20 张全是 location 为空的岗。✅ 根因：`locationState` 与城市门都是「目标原词 + normalizeChinaCity」子串；
  `expandChinaCityTargets` 只有 /jobs 在用、一省只展开 1–2 个省会。✅ 防：`lib/opportunities/location-targets.ts`（两端共用）+
  `lib/geo.locationProvinces`（映射 `lib/cn-province-prefectures.json`，crawler/geo.py 同口径，共享夹具
  `tests/fixtures/cn-location-provinces.json`）；「杭州 深圳 无锡 宁波」这种一格多值在 `buildRadarProfile` 读侧也拆（同 `normalizeCityPhrases`）。
  🚫 别退回「含该省任一地级名」的裸子串：8,107 种在招写法逐条对拍，它会把「大连市-中山区」判广东、「安徽省·马鞍山市」判辽宁、
  「天津-河北区」判河北、「乌海市·海南区」判海南（后两条旧口径就中，一并纠正）。
  📊 8 个受影响画像交替两轮：展示岗落在目标外 0→0，召回里被误拒的省内岗 273→0；其余 60 个画像召回 SQL 逐字节相同。
  代价：多省画像库内 warm 120~230→540~640ms，仍在「北京上海杭州」这类城市画像（540~1,090ms）范围内。
  ⚠️ 没覆盖：县级市（昆山 / 义乌）与拼音地点（全库只 4 行）；只写区名不写市的（「闵行,嘉定,…,黄浦」）认不出是上海。
  📌 纠错（同日）：此处原写「「地名+方位路」会误认（延安东路→陕西）」，已修：街道规则从「路 / 街」扩到
  `[东西南北中]?(路|街|大道|大街)`（南京东路 / 西藏中路 / 深圳大道），两端同改。在招 2.6 万种写法逐条对拍：
  丢省 1 种 2 行（陕西→未知，农行上海岗）、多省 0；代价是以本市命名的大道单独出现（「深圳大道」）也不认，全库 0 行。
  - **/jobs 同口径（2026-09-23）**。📌 纠错：此处原写「/jobs 仍是一省 1–2 城」，实际更窄——FTS 候选门按**原词**查 search_doc，
    只取到字面写着省名的岗（线上筛「广东」3,434、筛「深圳」一城 23,394）；城市群 / 带「市」同一个洞（珠三角 0 / 长三角 11 / 「北京市」34）。
    ✅ 筛选、`scoreJob` 城市 +20、粗排、校招「对你有货」统一走 `lib/job-filter` 的 `locationMatchesCityFilter` / `cityFtsTerms`
    （普通城市 SQL 逐字节不变）。27 省 A/B 交替两轮零漂移：该进没进 0（全集）；新放行 2,053 种写法 / 31,939 行机审只错上面那 1 条。
    ⚠️ 省目标的 where 只是超集（地名 ilike 误入全库 374 行，辽宁 170 是「马鞍山」）→ `exactTotalWhenCapped` 按 location 分组、用同一判定复核再求和，
    自检③只扣城市判掉的行；**别改回 count(*)**，否则给出多数的确定数字。代价：「广东」计数库内 warm 416ms / 冷 2s，与「北京」同档。
    🚫 省级解析在 `lib/cn-location-provinces.js`，**不许 require("./geo")**：job-filter / scoring / campus-facets 被客户端组件引用，
    引 geo.js 会把 52KB 词表打进 /jobs /campus /today /saved 首屏包（实测各 +16kB；拆出后 +4~5kB）。
- **/today 慢先看 `?__timing=1` 分段，大头是召回 SQL 的冷缓存，不是传输也不是 CPU（2026-09-23 实测）**：
  线上登录态三段串行 = 画像读取（悉尼）0.2~0.56s + 召回 0.43~0.82s 热 / **2.2~4.8s 冷** + stage-2 计算。
  同一画像召回库内 EXPLAIN 热 513ms、十分钟后再跑 2,210ms（read 19,823 块）——jobs 堆 1.1GB、shared_buffers 512MB，
  爬虫写入几分钟就把缓存挤掉，**真实用户一天来一次 = 基本都是冷的**。50 个画像就绪用户首轮 EXPLAIN 库内 37ms~5.9s（16 人 >1.3s），
  读块分散在方向 / 城市新岗 / 职能各层（合计 50 万 / 40 万 / 35 万块），没有单层能一刀修掉。
  🚫 **加索引 / 瘦身救不了（同日量过下限）**：假设有个能把全部过滤条件（含 7 天窗）都下推的完美索引，50 画像回表的不同堆块
  也只从 76.8 万降到 28.8 万（37.5%）；最重的 3 个画像仍 75~83%——过完全部条件还剩几万行，
  而每层「全排序后取 1,800」必须把它们全读一遍。命中行稀疏（≈1.2 行/块），把行做窄（投影表 / 正文挪 TOAST）估算只省 1.1~1.5 倍。
  最重那个画像背靠背第二次仍 6.1s / read 58,526 块：单条查询的工作集就大过 512MB shared_buffers。
  → 创始人拍板：不加内存、不给召回加时间窗（砍长尾），代码层做 ↓。
- **✅ /today 召回已挪出请求路径：召回快照 + 限定重算（2026-09-23 上线）**。香港库 `today_recall_snapshots` 存每个用户召回各层选中的 id；
  请求时 `buildRecallSql(…, { restrict })` 在「快照 id ∪ 快照之后首见的岗」里重跑**同一条** SQL（`recall_pool` 物化，走主键 + 首见 btree，不扫方向 GIN）。
  写：`today-recall-snapshot.yml` 每 6h 全量（台账 `today_recall_snapshot`）、页面现跑后 / 快照超 1h 时 after() 回写、保存偏好（PUT）后 after() 预算。
  失效：召回 SQL 形状指纹（改偏好即对不上 → 现跑）、超 12h → 现跑、`TODAY_RECALL_SNAPSHOT=off` 全关；快照读与悉尼查询并行并顺手预热堆块。
  📊 库内（50 画像）：快照 2.5h 旧首跑 限定 p50 349 / max 593ms、read max 3,201 块 vs 现跑 p50 1,327 / max 10,428ms、read max 56,995；
  线上 /today 召回 86~257ms（改前热 0.43~0.82s / 冷 2.2~4.8s）。**展示卡片 50 人逐张相同、顺序相同（两个方向都 0）**，召回层 24 人有 ~1% 行互换（614/595 行）没传到卡片。
  🚫 快照只许由现跑结果写（限定结果回写 = 子集套子集，偏差一轮轮累积）；不传 restrict 时 SQL 与原来逐字节相同（50 画像对拍）。
  ⚠️ 仅有的偏差来源：快照之后掉出去的岗由排在限额外的岗补位 / 快照之后属性变了才满足层条件的老岗——都随快照变老增长，所以超 1h 就刷新。
  ⚠️ 对拍 harness 必须带用户真实已处理岗（快照按动作下推过），两边都不带会凭空多出几十行差异。顶栏切范围（PATCH）刻意不挂预算：前端会立刻 refresh。
  stage-2 计算的 40% 曾是 `classifyCompanyIndustry` 每次重建 override 正则，已预编译 + 按公司名记忆（线上 600~740→265~362ms）。
- **🚫 凡是「order by → limit / offset」截断，排序键必须以唯一列 `id` 收尾（2026-09-23，召回 + /jobs 候选同改）**：
  ❌ 现象：同一用户、同一份代码，/today 候选隔一会儿就换一批；改前改后对拍里「凭空丢岗」全是同一 first_seen_at 的行互换。
  ✅ 根因：爬虫一批入库在同一事务里，几百行 first_seen_at 逐字相同（一批 201 行跨层内名次 24–764，层截断 752 落在中间）；
  只按时间截断时并列块里谁进窗口由执行计划决定，而 GIN 代价估算随写入漂——**同一条 SQL 一分钟内就会换索引**
  （实测某 role 层 6 次规划 5:1 在两个 GIN 间翻）。所以它不只是「改 SQL 才抖」，线上两次刷新就可能不同。
  ✅ 防：召回 `orderOf` 末位 `id`（function 层同用它）；`lib/jobs-store/search.ts` 的 `FRESH_ORDER`（粗排 / 新鲜度 / 校招实习 union 三处）。
  📊 同 SQL + 无害扰动（tsquery 上 OR 一个永假 id 条件）：召回 56 画像旧 23 人 323 行被并列行顶替 → 新 0（仅剩 2 人差异，核实是查询间隙爬虫刚写入的行）；
  搜索 17 个 FTS 窗口旧 5 个换序 2,385 位 → 新 0。walkthrough 连跑两轮召回数不一致 12 人 → 3 人；match-eval top-25 两轮一致 5/24 → 23/24，
  严格 / 宽松准确率改前改后逐画像相同（93.0/98.3%、89.9/95.3%）；可展示岗合计 9,824 → 9,818（换了另一批并列行，3 升 5 降）。
  代价（香港库 EXPLAIN）：召回 148 层计划逐层同形、buffer +1.0%；搜索按索引取序的路径多一层 Incremental Sort（只在并列块内按 id 排、
  索引不变），buffer +0~12%，最重的是匿名城市搜索（北京 warm 37→42ms）——Incremental Sort 要读完截断点所在的那一批。
  ✅ 2026-09-24 补齐 `lib/jobs-store/read.ts` 的 `LATEST_ORDER`（listLatestActive = /jobs 首屏 SSR + /api/jobs/list 翻页、recallByPrefs）
  + 5 处 Supabase 兜底 `.order("id")`；`tests/jobs-order-tiebreak.test.js` 扫 lib/app/components，新写的裸 `order by first_seen_at desc` 直接红。
  📌 纠错：此处原写「listLatestActive 等同病未改」。同快照实测：国内首屏 60 条两版 19 条不同；走并行全表扫 + 排序的计划
  **同 SQL 同快照连跑两次** 200 位里 71 位不同（带 id 后 0）。代价：首屏 warm 0.5→0.6ms，截断点落在大并列块才明显
  （海外第 2 页 1000 条、块 2,006 行 8.9→17.8ms）。同日补 `audit_dead_links --prioritize-new`（香港库 + Supabase 兜底；400 条截断点落在
  157 行并列块，同索引 + Incremental Sort，warm 5.7→7~20ms）与 `scripts/verify-opportunity-recall.ts`。
  ⚠️ `scripts/{audit-job-duplicates,diagnose-jobs,probe-dead-links}.js` 仍是裸时间序没改：它们读的是 Supabase `jobs`（2026-09-24 实测 0 行），先得改读香港库，排序才有意义。

## 数据库迁移（已自动化，勿再手动跑 Supabase）

迁移**不需要再手动进 Supabase SQL Editor 跑**。机制：push 到 `main` 且改动 `supabase/migrations/**` 时，
`.github/workflows/migrate.yml` 自动用 `scripts/db-migrate.sh` 把未应用的迁移 apply 到生产库（`schema_migrations` 表记录版本，前缀 ≤ BASELINE 仅登记不重跑）。
- **一次性设置**：GitHub repo → Settings → Secrets → Actions 加 `SUPABASE_DB_URL`（Supabase → Settings → Database → 直连串，端口 5432，含密码）。配一次，此后零手动 SQL。
- 新迁移文件继续放 `supabase/migrations/`，前缀按序递增（如 `023_xxx.sql`），push 即自动应用。
- 加新迁移后若 BASELINE 已过期，更新 `scripts/db-migrate.sh` 的 `BASELINE`。
- **命名规约**：seed 类迁移（纯 `insert` sources 数据）文件名必须带 `_seed_` 标识；新前缀必须先 `ls supabase/migrations` 确认未被占用。前缀「纯数字 + 无新增重复」由 `scripts/check-migrations.sh` 在 CI apply 前硬校验（历史重复前缀已在脚本 GRANDFATHERED 白名单豁免，勿改名已应用文件）。
- ⚠️ **seed 迁移里一行违反 CHECK，整批一起回滚（2026-09-03 踩）**：单个迁移文件是一个事务。
  211 给京东那条写了 `crawl_method='browser'`（该列 CHECK 只认 `http` / `playwright` / `manual`），
  结果**前面三条合法的 insert 一起没进去** —— 线上现象是「这批源一条都没有」，
  极易误判成「迁移根本没触发」而往 CI/权限方向查。
  ✅ 排查顺序：先看 migrate CI 日志里 `psql:...: ERROR:` 那一行指的是**哪一行 SQL**，再谈别的。
  ✅ 写 seed 前先确认目标列的 CHECK：`select pg_get_constraintdef(oid) from pg_constraint where conname='<表>_<列>_check';`
  ✅ 改 CHECK 时注意它是「全量重建而非增量」的写法——新迁移必须把旧枚举值一个不落抄全，漏一个会把存量行打成非法。
  ✅ **上线前拿「临时表 + ROLLBACK」在真库上整份跑一遍**——但临时表必须
     `create temp table x (like public.x **including all**)`。
     🚩 用 `including defaults including constraints` 会给**假绿灯**：`LIKE` 默认不复制
     GENERATED 表达式，`sources.board`（`generated always as classify_source_board(...)`）
     在临时表里变成普通可写列。2026-09-07 实测同一份迁移 241（显式写了 `board`）：
     旧写法 `INSERT 0 1` 通过、`including all` 当场 `ERROR: cannot insert a non-DEFAULT
     value into column "board"`——而线上 migrate CI 报的正是后者，整批回滚。
     同理漏掉的还有 identity 列、索引、注释；**只要不是 `including all`，绿了也不算数**。

## 常用命令

```bash
npm install && npm run dev            # localhost:3000
npm run build && npm run lint         # ⚠️ lint 必须单独跑，见下

# 提交前回归四件套
node --test tests/*.test.js && \
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
  npm run build && git diff --check

# crawler 单源（需先有 .env.local）
cd crawler && set -a; source ../.env.local; set +a
python3 run.py --source apple         # 或 siemens / baidu / jd
```

⚠️ **`npm run build` 本地绿 ≠ Vercel 能部署**：本地 `next build` 会跳过 lint（输出里没有「Linting and checking validity of types」这一步），**Vercel 的 build 会跑 lint，且 Next 若干规则是 Error 级会直接让部署失败**（2026-07-27 实锤：`lib/admin-health.ts` 里一个变量叫 `module` 命中 `@next/next/no-assign-module-variable`，从 6d5010f 起连续 7 次部署失败，本地全程绿）。**改了 `app/` `lib/` `components/` 下的 TS/TSX 就必须另跑 `npm run lint`。**
⚠️ 在 `.claude/worktrees/*` 里跑 `next lint` 会因「主仓 + worktree 两份 .eslintrc.json / package-lock.json」报 plugin 冲突直接退出 1——这是环境问题不是代码问题；改用 `npx next lint --dir lib --dir app --dir components`，或 push 后立刻查 Vercel 部署状态兜底（`gh api repos/<owner>/<repo>/deployments` + `/statuses`）。

## 目录结构

```
app/                     # Next.js App Router 页面
  page.tsx / today-client.tsx    # Today 今日看板；jobs/ 岗位库、campus/ 校招专区、programs/ 公告制招聘
  preferences/ saved/ applied/   # 偏好 / 值得投 / 已投递
  sources/ admin/insights/ admin/health/   # 均仅管理员：源管理 / 洞察管理 / 运营看板
  login/ auth/callback/          # 登录与 OAuth 回调
  api/                           # search·discovery·refresh·resume·preferences（岗位层入口）
                                 # sources（service-role 写，绕 RLS 无 INSERT 策略）
                                 # insights + insights/dispute + insights/admin + dispute/resolve
                                 # campus-zone/jobs（按 公司+模式 取，非按 id）
components/              # JobCard / JobFilters / PreferenceForm / Navbar / ResumeProfilePanel
                         # SourceTable(presentational,含 reloadSignal) / SourceManager / AddSourceForm
                         # InsightsAdminClient / CompanyInsightDrawer / SavedCompare（后两者 portal 到 body 防闪烁）
                         # ui/  ← 设计组件库 21 个原语（见下「设计组件库」一节）
lib/                     # supabaseClient / supabaseService / auth / auth-claims / apiAuth / scoring / types / utils
                         # jobs-store/{client,search,read,write}  ← 香港 jobs 库唯一出入口
                         # must-apply-list(.ts+.json 北极星口径) / admin-health / track / match-total / job-filter
                         # campus-{facets,user-industries,zone,season} / job-fields / relative-time
                         # geo / job-scope / sponsorship / role-lexicon-en / china-keyword-expansion / canonical-url
                         # insight-{verification,match,client,bundle,chip-format,enrich-now,library}
                         # source-adapters / live-search / official-discovery / baidu-qianfan-search / liveness-client
                         # ui/{variants,hooks}  ← 组件库变体表与 hooks（变体表必须放 .ts，见「设计组件库」）
crawler/                 # ⚠️ adapters/ 逐个 adapter 的接口细节与坑 → `docs/crawler-adapter-notes.md`（改/接前必读）
                         # run.py / db.py / jobs_db.py(香港库写) / normalizer.py / robots.py / discovery.py
                         # enrich.py + enrich_backlog.py(补正文 / 逐岗探活) / audit_dead_links.py(浏览器巡检)
                         # gap_census.py → entry_finder.py → platform_fingerprint.py → gap_funnel.py(必投缺口漏斗)
                         # must_apply.py(清单口径,与 lib/must-apply-list.json 同源) / company_name_match.py(归属核名)
                         # insight_backlog.py / insight_engine.py / search_router.py / llm_budget.py(洞察供给与成本闸)
                         # ops_runs.py(台账) / ops_watchdog.py(告警规则) / probe.py(扩源探活) / audit_stale_active.py
                         # geo.py / sponsorship.py / cn_portal_tls.py(国内门户 TLS 兼容,见下红线)
supabase/migrations/     # 已到 238+（`ls supabase/migrations` 看全量，历史脉络见 docs/crawler-adapter-notes.md）
                         # 前缀递增且不得重复；seed 类文件名必须带 _seed_（CI 硬校验）
.github/workflows/       # daily-crawl / campus-crawl / enrich-crawl / enrich-backlog / liveness-sweep
                         # dead-link-audit / purge-expired / db-report / ops-watchdog / gap-funnel
                         # auto-discover(-browser/-overseas) / migrate / jobs-db-migrate / maintenance-vacuum
tests/                   # node --test 单测（*.test.js）；crawler 侧 unittest 在 crawler/test_*.py
```

**接新 adapter / 改 adapter 前必看的四条通用红线**（个案细节全在 `docs/crawler-adapter-notes.md`）：
- **必须逐个跑一遍 `adapter.should_skip(url)`**：工行 / 中国移动对 HEAD 恒返 403，建行对本项目 Bot UA 返「HTTP 200 + 零字节 body」——不覆写就整源被静默跳过、永远 0 产出且不报错。
- **本机绿 ≠ CI 绿**：本机 macOS 是 LibreSSL + 有 IPv6，GitHub runner 是 OpenSSL 3 + 无 IPv6 出口 → 国内门户常「本机全通、CI 四个源全 failed」。修法在 `crawler/cn_portal_tls.py`（强制 IPv4 + OP_LEGACY_SERVER_CONNECT，**证书校验保持开启、不许 verify=False**），这两条本机永远测不出来，靠单测断言看着。
- **接完源必须回读线上 `crawl_runs` 的 status / error_message**，别拿本机跑通当交付。
- **hotjob / wecruit 源的公司名只认租户自报的 `suite/config.companyName`，不认 slug / probe 清单（2026-09-18 立，迁移 248·274 两次张冠李戴）**：`jd.hotjob.cn` 是精雕不是京东；wecruit 租户 `SU612f55…` seed 时记成领益智造，实为特变电工（1,903 个 active 岗挂错名三个月无人发现，标题与 tbea wt 源逐字相同）。探活出岗 ≠ 归属正确。存量纠正走 `rename-job-company.yml`（按 jd_url 前缀点名）。
  📌 第三次（2026-09-23，迁移 291，moka）：租户 `dahua` 是上海大华（集团）（地产，页面 title/intro 自报），被记成浙江大华技术（安防）——根因是 auto-discover 清单 `cn='大华'`，`_verify` 只要求门户标题含 cn，「大华集团 - 社会招聘」照样放行。**清单 `cn` 必须能区分同名的另一家公司**（现为「大华技术」，`test_auto_discover` 钉着）；moka 等平台同样以门户页自报的公司名为准。
  📌 第四次（2026-09-23，北森）：**一个 ATS 租户 ≠ 一家公司**。`chinalife.zhiye.com` 同时发中国人寿与广发银行的岗，三个门户页同一 PortalId、列表一次返回整租户，每条都贴 sources.company → 531 个广发银行岗（列表里 466 + 已下线 65）挂成「中国人寿」。✅ 按每行自报的招聘机构 `Org`（DisplayFields 点名才返回；广发自己的校招页圈岗用的是同一棵树，全量逐条一致）归属，共享租户登记在 `china_ats._BEISEN_SHARED_TENANTS`；存量逐行纠正走 `reattribute-beisen-shared-tenant.yml`（`rename-job-company` 按前缀整批改名，同一前缀两家混着时用不上）。接北森源先看列表里「招聘机构」列有没有别家。
  2026-09-24 全量普查 307 个在用北森租户（新版 276 个翻全 145,919 岗；老版 30 个里 27 个无机构列、判不了）：除国寿外没有第二个「挂别家」，但同病的两个变种各查出几例（迁移 305）——**同一门户挂两个域名**（tjsemi↔zhonghuan 758 岗、ke.zhiye.com↔campus.ke.com 45 岗，jobAdId 逐个相同 → 一岗两行两个公司名；判法是比两条源页面的 `PortalId`）；**母子集团两个租户各发一份**（上实门户 149 岗里 117 个与上海医药门户标题连招聘编号一字不差，jobAdId 不同 → `china_ats._BEISEN_TWIN_PORTALS` 抓时剔除）；**源名起窄**（泰康之家→泰康保险、建发房产→建发集团）。存量孪生走 `remove-jobs-by-url-prefix.yml` 的 `twin_key`（北森没有 `#` 片段，默认口径对它数出 0，要用 `jobadid` / `title`）。
- **Playwright 在 CI 上：不等 `networkidle`、必须接管 dialog（2026-09-13 立）**。
  ❌ moka 09-10 起 410 源日产 3.6 万岗 → ~500 却全记 success：新版前端 POST `sentry-fe.mokahr.com`，该主机从 runner 连不上也不断开（本机国内网络能连，所以本机复现不出来）→ networkidle 永远等不到 → 4 路由×35s 超时被 `except` 吞成 0 岗。
  ❌ dead-link-audit 每晚一片卡 150min：中国交建详情页弹 `alert('职位已下架')`，没注册 dialog 监听 → 驱动自动 dismiss 撞上下一跳 goto → Node 驱动崩溃、Python 干等。CI 上 A/B：旧代码第 6 个岗就崩，新代码 76 分钟审 1300 岗零崩溃。
  ✅ 等「岗位卡 / 空态文案出现」而不是 networkidle（`MokaAdapter._open_route`，google.py 早有同理注释；`abchina.py` 仍在用 networkidle，出事先看这里）；`page.on("dialog")` 自己 dismiss 并吞掉异常（`audit_dead_links._install_dialog_guard`）；「所有路由都没渲染出来」必须抛错记 failed，只有真看到空态才许 0 岗 success。

## 数据库表（核心表，权限见 002_rls.sql）

| 表 | 用途 | 权限 |
|---|---|---|
| profiles | 用户扩展信息（含 `role`，管理员判定靠它） | 自己读写 |
| sources | 企业招聘源（含 `regions` 抓取地区，默认 `{CN}`） | 所有人读，crawler 写 |
| source_candidates | 官方源发现候选 | admin 读，service role 写 |
| jobs | 共享岗位库（已迁自建香港 PG，含 `country_code`/`job_scope`/`sponsorship_signal`，见核心产品原则 §4） | 所有人读，crawler 写 |
| user_preferences | 用户偏好（含 `job_scope`/`target_regions` 求职范围、`experience_stage` 求职阶段实习/校招/社招，迁移 172） | 自己读写 |
| candidate_profiles | 简历档案（含英文侧 `en_*` 与 `has_en_resume`） | 自己读写 |
| job_actions | 值得投(saved)/忽略/投递（applied 行含投递进展 `stage`：笔试/面试/offer/已结束，迁移 173） | 自己读写 |
| crawl_runs | 抓取日志 | admin 读，crawler 写 |
| discovery_runs | 官方源发现日志 | admin 读，service role 写 |
| events | 自有埋点（简历解析质量等去标识 diagnostics） | 自己写，admin 聚合 |
| ops_runs | 后台任务每日台账（运营看板②每日战报来源，迁移 159） | service_role 读写 |
| must_apply_gap_attempts | 必投缺口漏斗台账：每家缺口公司走到哪一步/失败原因/复查日期（迁移 185） | service_role 写，admin 读 |

共享 `jobs`，偏好与操作按 `user_id` 隔离（同一岗位可被 A 标投递、B 标收藏）。

### 模块 B 职业洞察层（与岗位层严格分离，migration 013/014）

六张表（company_profiles / insight_items / insight_sources / insight_item_sources / insight_disputes / company_hiring_monthly）、五维 dimension、三层供给（T1 自有岗位库派生 / T2 官方事实 Wikidata+EDGAR / T3 多源搜索+判官）、admin 网页维护零 SQL——**细节全在 `docs/insights-module.md`，做这个模块前必读**。正文只留四条不可越的红线：
- **三级 `grade`**：`fact` 须带来源 / `experience` 须 sample_size≥5 且多源 / `rumor` **默认拦截**。
- **展示前必过 `lib/insight-verification.ts`** 的分级 / 时效 / 去标识 / 归因门；无可信结果返回 `insight_unverified` / `insight_outdated`，**不许降级放行**。
- **只走搜索 API 取去标识聚合 + 判官核验 + ≥2 源，不直接爬社区**；官方源=fact，搜索源必须聚合去标识。
- **AI 辅助草稿强制 `status=retired`**，必须人工核对 + 补真实来源过门才展示；不进 cron、不按用户触发（控账单）。
- **公司归属的中文子串门（2026-09-17 立）**：`lib/insight-match.ts` 此前「含汉字就许子串命中」→「京东」命中「京东方」、
  「中国银行」命中「中国银行业协会」，京东方（BOE）的岗被算进京东的派生指标。现行：长名比短名多出的那一截必须**全部**是
  公司装饰词/地名（腾讯科技（北京）✓、中国银行深圳分行 ✓；京东方 ✗、腾讯音乐 ✗、京东物流 ✗）。子公司归集团画像靠
  `company_profiles.aliases` 显式登记，不靠子串猜——归属准确性高于一切。撤回/下架接口现会 `revalidateTag("insight-library")`，
  管理员端同步清本会话抽屉缓存（I5 残差）。
- 检索额度是**全局共享**的（见「搜索额度是全局共享的」一节）；千帆免费额度 50/天，耗尽时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，**不要反复点「发现」或跑 5-query live 验证**。

## 四层「搜索/刷新」必须区分（高频踩坑点）

不可混为一谈，更不可把有限候选源池叫「实时网搜」：

1. **本地 jobs 搜索** — 只查 `jobs` 表，无外部请求。
2. **「刷新公司库」`/api/refresh`**（前端 Jobs 页「刷新公司库新岗位」按钮，全异步·流式）— 解析用户 scope（当前筛选 + 偏好兜底，按相关性 + 每平台多样性 cap 前 N=25 家）→ 节流/幂等 → 插 `discovery_runs(mode='company_refresh', diagnostics={source_ids,filters,click_time})` → workflow_dispatch GitHub Actions → CI 跑 `crawler/discovery.py CompanyRefreshRecipe`（httpx 源先、浏览器源后，逐源增量回写产出+进度）→ 前端复用 discovery 轮询(`/api/discovery/status`)流式并入。**覆盖用户全部公司源（含飞书/北森/Moka 浏览器源），取代旧 `/api/search` 的窄同步刷新**。设计/硬化见 `docs/superpowers/specs/2026-06-11-refresh-company-library-design.md`。
3. **已知源刷新** `/api/search`（旧同步路径，前端已不主用）— 只内联抓百度/京东/Apple + ≤8 greenhouse/lever，serverless 秒回。仍保留作 API；**已处理 exclude_keywords**（从用户偏好读取，每个源 upsert 前用 `excludeJobs` 剔除命中岗位，与 crawler 同口径）。
4. **官方源发现** `/api/discovery` — 百度千帆为主 provider，**低频、串行、可缓存**（相同 user/query/city/job_type 45 分钟复用缓存）；默认只调 1 个 generated query，「继续发现更多」才调第 2 个。

> 三/四层都靠 GitHub Actions workflow_dispatch（需 Vercel 配 `GITHUB_DISPATCH_TOKEN`+`GITHUB_DISPATCH_REPO`）；`/api/refresh` 与 `/api/discovery/dispatch` 共用这套异步轨道 + `discovery_runs` 表，零新表。

## 公告制招聘（/programs）供给：官方公告自动抓取（2026-09-15 上线）

事业单位/体制内很多招聘是**公告制**（一条公告 = 批量岗位 + 报名截止日，官网没有逐岗详情页），进不了 jobs 库（过不了 jd_url 红线，也不该假装是岗位）。`/programs` 承载它，两路数据：`apply_programs`（手工核实的边缘央企/项目/人才库条目，迁移 226）+ `announcement_postings`（官方招聘公告自动抓取，迁移 252），统一渲染为「招聘公告」卡，**一条公告 = 一个投递入口，不拆岗位**。设计文档 `docs/superpowers/specs/2026-09-15-announcement-recruitment-supply-design.md`，记忆 [[job-radar-announcement-supply-pipeline]]。抓取管道 `crawler/announcements/`（portals 白名单/classify 过滤/deadline 抽取/harvest/expire），调度 `announcement-crawl.yml`。四条红线：

- **归属靠官方域名白名单天然保证**（`portals.PORTALS` 逐省登记，host + 逐省 `detail_pat` + 标题 INCLUDE/EXCLUDE 三重过滤）→ 不会张冠李戴（企业爬取最头疼、这里免费解决的）。人社厅下属官方机构域名（如省人事考试中心 `lnrsks.com` / `qhpta.com`）经创始人授权可纳入白名单，同「国聘是第三方禁令唯一例外」先例；仍只抓官方源，**不碰公众号**（内容与官网栏目重复且列表无法程序化枚举）、**不碰第三方商业平台**（中公/华图，红线）。
- **时效**：报名截止日抽成结构化 `deadline` 列 → 过期自动下架；抽不到走「发布日/首见日 + TTL(默认 45 天)」兜底 + RLS `deadline >= current_date` 双保险。**过期公告比死岗更伤**，别只靠人工。
- **🚫 入库时判一次不算数，必须每天在正文上重判（2026-09-18 立，逐条实测 118 条在展示的公告）**：
  ❌ 现象：点进去是「关闭报名系统公告」「专业测试公告」「面试确认公告」「报名确认人数公告」「岗位表」
     —— 它们标题里都带「招聘」，正向门直接放行，此后一路 active 挂到 45 天 TTL。
  ✅ 三个根因，缺一不可：① 标题门只在**首次入库那一刻**看一眼；② 报名窗写在**正文**里，
     官方随时能另发一条公告把它提前关掉；③ 截止日正则只认「至」，不认「9月18日-9月24日」
     这种只有连字符的区间 —— 实测 33 条 deadline 为空的公告里 **27 条正文其实写了**。
  ✅ 防：`announcements/body.py`（正文切割，别拿整页文本判：导航侧栏页脚会污染）+
     `quality.assess`（三档 reject/flag/ok）+ `verify.py`（每日真抓正文重判，下架比例 >50% 整轮放弃写库）。
     入库端与复验端共用同一个 `assess`。live 结果：抽到截止日 67→85（0 回归 0 误抽），下架 12 条。
  ⚠️ **两次误杀都栽在「否定性判断」上，回归钉在 `crawler/test_announcement_quality.py`**：
     「**重启**报名系统公告」是**新开的报名窗**（9/16-9/24 正在报），不是过程通知；
     正文引用《…关闭报名系统公告》是在指**另一份文件**，判「本公告关没关」前必须先剥书名号。
     同理 `_BODY_SELF_APPLY` 收窄一点就会把本页自收报名的正常公告标成「汇总索引页」。
- **国聘公告是央国企那块供给的唯一来源（2026-09-18 接，`announcements/iguopin.py`）**：各省人社厅
  结构性只有高校/事业单位，接之前库里**央国企一条都没有**。列表接口一次 100 条、报名起止日是
  **结构化字段**（100/100 有），整轮只需 1 次请求（`apply_url` 列表里就带，别逐条打 `/info`——会被限流返 403）。
  ⚠️ 它的前端路由表里**没有** detail 路由，别去猜 `/detail?id=`（会被 SPA 打回首页）。
  ⚠️ `apply_url` 少数落到智联/前程无忧/中华英才（实测 3/100）→ 红线，丢弃。
  ⚠️ **它的地理编码会错**：「福州市鼓楼区」→ 开封、「贵州锦丰矿业」→ 江苏丰县 ⇒ 市名/省名必须
     **按中文词边界**出现在标题里才采信，否则写未知（「五**大连**池」曾被裸子串认成大连）。
     它的「校招」标签同样不可信（81/100，含「社会公开招聘」）⇒ 受众以标题为准。
- **⚠️ geo-block + 双 runner（2026-09-16，27 省 live）**：很多省 gov 服务器拒连境外 IP（GitHub US runner 与香港服务器都连不上，`make_transport` retry=2 仍失败，非 TLS 是地理可达性）。解法 = **创始人 Mac 的 launchd**（大陆路由，每日 12:30，`scripts/run-announcement-crawl.sh` → `harvest --include-geo-blocked`）跑**全部省**；GitHub `announcement-crawl.yml` 只跑境外可达 4 省（北京/广东/湖北/福建）作常开兜底，两边 upsert 幂等。**加省准入两条判据**：`portals.PORTALS`（GitHub 跑）看 CI `list_errors`；`portals._GEO_BLOCKED_FROM_CI`（Mac 跑）看**本机 dry-run**（CI 够不着它们）。🔴 **plist 是 wrapper 的绝对路径，仓库一移动定时任务就静默失效**（2026-09-15 仓库移到 `diy/` 断过一次，改 plist 路径 + reload 修好）。彻底不依赖 Mac 开机 = 大陆 SCF/轻量服务器/自托管 runner，待创始人定（[[job-radar-backend-review-2026-09-03]]）。加省清单与 detail_pat 逐省细节在 `portals.py` 注释，不写这里。
- **综合栏目可接**，但只保留真招聘岗位公告：靠 `classify` 标题门在列表端滤掉公示/名单/遴选/决算/征求意见等；创始人原话「我们要的是岗位招聘公告，其他公告不需要」。
- **「JS 渲染」不等于「要浏览器」（2026-09-16 立）**：多数 JS 省的数据其实内嵌在页面/接口里，curl 即得，`list_format` 分四种形态处理，**无需浏览器**：`html`（静态 `<a>`，含 `<record><![CDATA[]]>` 逐块解析，如天津/江苏）、`script_json`（`<script>var …={…}` 内嵌 JSON，如江西）、`json_fragment`（非公开 GET 接口返 `{"data":{"html":"…片段"}}`，如浙江，较脆见 `portals.py` 注释）、`json_api`（结构化 GET JSON，如黑龙江）。**接新 JS 省先 curl 看有没有内嵌 JSON/片段接口，别默认要浏览器**。**覆盖 30/31，只缺河北**（真 Vue SPA，确无匿名可取数据）。2026-09-18 补接 海南/贵州/云南 + 换源 四川/宁夏/内蒙古（原 URL 指的是综合栏目或已停更 368 天），此前文档写「只剩河北」是错的。
  - ⚠️ **接新省两个必修前提，不做就静默产出 0 条**：① `Portal.encoding`——内蒙古人事考试院是 GB2312 且响应头不声明 charset，httpx 猜 utf-8 会整页乱码、标题门全不命中而**不报错**；② 分页是查询参数的省（四川 `&i=` / 内蒙古 `&mmm=` / 云南 `&page=`）套不进 `page_pattern` 的路径拼接，得把各页完整 URL 列进 `list_urls`。
  - ⚠️ **「单年一批」的省当下产出 0 是正常的**（四川/宁夏/西藏/内蒙古）：今年那批报名早结束，换对源的价值在下一批开的时候能抓到。别把 0 读成没修好，也别因此去放宽标题门。
  - ⚠️ 换源时 **portal key / 省份重复是静默的**（`PORTALS_BY_KEY` 只留最后一条），本次真出现过新旧两条并存 → 已钉契约测试。

## 数据质量优先级（最高）

`jd_url` 准确性高于一切。**禁止写入 active jobs**：招聘首页 / 搜索页 / 导航页 / 帮助页·FAQ / 登录页 / 语言切换页 / 专题入口页 / 空链接或猜测链接。拿不到稳定岗位详情链接的 source 只能记 `partial_success`，不得标记完整成功。质量门：`company/title/jd_url` 非空 + HTTP 200 + 页面含标题或核心片段。

**唯一性下沉到 DB（migration 144）**：`jobs.canonical_jd_url`（归一 tracking 参数 + 尾斜杠；`#` SPA hash 路由原样不碰）+ active partial unique index 保证「同一岗位链接在 active 里唯一」。
- ⚠️ **`canonicalize_jd_url` 归一逻辑活在三处，改一处必须三处同改、字节级一致**：`lib/canonical-url.js`（前端/JS 写入端）、`crawler/normalizer.py`（爬虫端）、`supabase/migrations/144_jobs_canonical_jd_url.sql` 的 SQL 函数（回填/触发器/审计）。任一处 drift 会导致同岗算出不同 canonical → 去重失效或误并。
- 改规则后必须同步两套纯函数测试：`tests/canonical-url.test.js` + `crawler/test_canonical.py`。
- 加唯一约束类迁移：上约束**前**必须先 dedup 存量重复（降级而非删除，保 `job_actions` 外键），否则 `CREATE UNIQUE INDEX` 在生产有重复时会失败并永久阻塞后续迁移；push 前先在**香港库**上按新唯一键 `group by … having count(*) > 1` 数影响面。
  📌 纠错（2026-09-24）：此处原写「先跑 `node scripts/audit-job-duplicates.js`」——它读的是 Supabase `jobs`，Phase 1（2026-06-19）后那张表不是真数据
  （09-24 实测 0 行），跑出来恒为「无重复」= 假绿。它改读香港库之前别用。
- ⚠️ **大表（jobs 10 万级）全表回填/建索引迁移必须抬超时**：在迁移事务内加 `set local statement_timeout = '1800s';`。Supabase 默认 statement_timeout ≈ 2min，全表 `update … set x = f(col)` 会被强杀致整个迁移回滚（migration 144 踩过这个坑）。

## 当前 source 状态

2026-07-02 海外扩展：`sources.regions` 默认 `{CN}`，迁移 `169_seed_overseas_regions.sql` 仅把已验证且 enabled 的 http 外企 ATS 源保守放开到 `{CN,US,SG,Remote}`；浏览器/Playwright 源暂不一次性放开，需单独评估容量。台湾不在 seed 范围内，normalizer 继续拒收台湾地点。

### 🚫「必投某家零岗」先查这条源的 `regions` 有没有 CN，再去找入口（2026-09-05 立）

`sources.regions` 不只决定「额外抓哪些海外地区」，它同时是**后置过滤的白名单** ——
adapter 里 `normalizer.location_in_source_regions(location, self.regions)` 一票否决。
一条漏了 CN 的源会把自己抓回来的中国岗当场丢掉，而 status 照样 success、**没有任何失败信号**。

实录：**大陆集团（Continental）**必投长期显示零源零岗，查下来根本不是没有中国入口 ——
`api.smartrecruiters.com/…/continental/postings?country=cn` 有 29 个岗，
官网 `jobs.continental.com` 每条岗位都带 `smartRecruitersId`+`client:continental`
（**官网就是 SmartRecruiters 的皮，同一个池子**：POST `tx_conjobs_api[itemsPerPage]=100` 翻完
8 页 736 条，`countryLabel=China` 也正好 29 条、REF 号逐个对得上）。
补上 CN 即得（迁移 230），**不需要也不该新增源**（会变成迁移 225 壳牌那种影子源）。

⚠️ **不是个案**：全库 1,333 个 enabled 源里 **50 个 regions 不含 CN**
（workday 27 / greenhouse 9 / smartrecruiters 8 / ashby 4 / lever 1 / eightfold 1），
名单含 迪士尼·Adobe·Salesforce·Boeing·Samsung·百威·玛氏·富达。
光 smartrecruiters 那 8 家实测就有 237 个中国岗天天被抓回来又扔掉
（AbbVie 169 / Continental 29 / Grab 14 / Expeditors 14 / Ubisoft 11）。
✅ 排查顺序：**先看 regions，再看 adapter，最后才去找入口**。反过来会白跑一天。
⚠️ 查 `sources` 必须分页：PostgREST 默认 1000 行截断，不分页会数出「1,000 个源、50 家漏配」
这种一眼假的整数（真值 1,333 / 50）。

**⚠️ 补了 CN 还可能丢岗：geo 必须认小写 ISO 国别码 `cn`。**
外企 ATS 的 `location.country` 给的是 `cn`，而城市名是**空格分词的拼音**
（"He Fei Shi" / "Ning Bo Shi" / "Zhe Jiang Sheng" / "Yang Pu Qu"），
与 `CHINA_LOCATION_MARKERS` 里的 `hefei`/`ningbo` 按词边界**一个都对不上**
⇒ `derive_country_code` 返回 None ⇒ `location_in_scope` 落「非远程且无国家」的 False 分支
⇒ 中国岗被当成非中国岗丢掉。大陆集团 29 个中国岗里 8 个（28%）就是这么丢的。
全库 596 行含独立 `cn` 词的 active 岗逐行核过，现判定 100% 已是 CN ⇒ 加它零误伤。
改这条要 `crawler/geo.py` 与 `lib/geo.js` **两边同改**（回归钉在 test_geo.py / geo.test.js）。

### 🚫 中文地名归属：宁可漏判，不可错杀（2026-09-05 立）

`derive_country_code` 认不出地名时，岗位的国内外归属**完全押在 `sources.regions` 一个字段上**——某个源哪天被放开 US，它名下这批岗就**静默**翻成 overseas，不报错、只是国内供给少一块（live 实测曾有 8.3 万个「中文地点 + 在招」的岗 `country_code` 为空）。所以词表必须认中文地名：`CHINA_CJK_PLACE_MARKERS`（省级 34 + 地级市 / 自治州 / 地区 / 盟 352 条，**县区级不收**，「保定市-莲池区」靠上级前缀命中）+ `TAIWAN/JAPAN/KOREA_CJK_MARKERS` 配套兜底。
- 🚫 **不许用「地点含 省/市/区/县/自治州 → 中国」这条规则**：它能覆盖 84% 缺口，但会把「新北市 / 大阪市 / 東京都 / 首尔市」一起判成中国，**直接踩台湾红线**。
- **顺序是设计的一部分**：`TW` 必须排在 `CN` **前**（「Taipei, Taiwan, Province of China」含 "china"，排后面会被当大陆放行）；`JP`/`KR` 必须排在 `CN` **后**（「青岛市、日本、潍坊市」这类一岗多地写法要保住 CN）。
- **选词只收「繁体裸名 + 简体带后缀名」**：常州有新北区 → TW 只收「新北市」；福州有连江县 → 只收繁体「連江」；日本北海道含「北海」→ CN 只收「北海市」；「邢台南和区」含「台南」→ TW 只收「台南市」。**漏判一个台湾岗无害**（回到 `code=None`，非远程照样被 `location_in_scope` 丢掉），**错判一个大陆岗是把在招岗静默删掉**。
- **外企 ATS 给的小写 `cn` 国别码也必须认**：它们的城市名是空格分词拼音（"He Fei Shi" / "Ning Bo Shi"），与词表按词边界一个都对不上 → 不认 `cn` 就把中国岗当非中国岗丢了。
- **词表两端逐条一致**：`tests/geo.test.js` 会读 `crawler/geo.py` 抽词表做 deepEqual，改一边不改另一边直接红。改 `crawler/geo.py` 必须同改 `lib/geo.js`。
- ⚠️ **顺序必须是「先推代码、再回填」**：`country_code`/`job_scope` 在 `_UPDATE_COLS` 里、不在 `_PRESERVE_IF_EMPTY` 里，列表重抓会用**当时 CI 上那版代码**覆盖——2026-09-05 回填完 3 分钟 `campus-crawl` 起来，用旧代码把 11,613 行刷回 NULL。
- ⚠️ **两字母码在「开头」和「结尾」是两回事，别把结尾那张表复制过去**（2026-09-06 加）：Workday 系还有一种把码写最前面的格式（`MY, JOHOR, VIRTUAL` / `SE, Solna`），但**这个位置上美国州缩写比国别码更常见** —— live 全库「开头两字母 + 逗号」7,403 行里 `GA, Atlanta…`117 / `NY, BROADWAY…`116 / `CA, Burbank…`50 全是「州, 城市, 门牌」。所以规则是**撞美国州缩写的一律弃权**（MO 是密苏里不是澳门、IN 是印第安纳不是印度），只有 CA/IN 在串里另有该国省/邦硬证据时才认；且整条规则排在 `derive_country_code` **最后一步**（`SE, Bothell, Washington, United, States` 是波音厂区代号，早在第一步就判了 US）。实测影响面 120 行：国内→境外 69、境外→国内 0、只补 country_code 51。取舍与实证反例（GM=通用汽车厂区前缀不是冈比亚、NA=北美占位不是纳米比亚）写在 `crawler/geo.py` 的 `ISO_ALPHA2_CODES` 那段注释里。
- 🚫 **国家 / 范围必须按「别名折叠之前」的原文判（2026-09-23 立）**：❌ workday 在招岗 6,526 行 `country_code` 为空却判 domestic，其中 4,383 行存的是「远程」，路径原文是 `United-States---Remote` / `Remote-Mexico` / `UK-Remote`；greenhouse / smartrecruiters / ashby 同病（live 重抓 77 源 2,899 个）。✅ 根因：`normalize()` 先 `clean_location` 再判国家，而 `normalize_city` 是**子串**折叠——串里有 remote 就整串换成「远程」，国家当场丢光（smartrecruiters 出口特意展开的 `Remote Germany` 也被它抹掉）。✅ 防：`normalizer.geo_basis`，别名后判不出国家就用原文判；CITY_ALIASES 的目标值里只有「远程」判不出国家，所以只动被折叠的行，`test_only_remote_alias_target_lacks_country` 钉着这个前提。workday 另在 `_loc_from_path` 展开 ISO3 国别码（白名单；PHL=费城、NOR=站点编号是实测撞车码）、还原 `United-Kingdom` 这类多词国名的连字符。
  📌 **续（同日）：地点压根没写国家的（'Durham' / 'Remote' / 'One Island East'）改问对方 ATS，不按 regions 猜**：❌ 上面修完仍剩 1,715 行按 regions 兜底判 domestic。✅ 防：`RawJob.country_code` = ATS 结构化字段**自报**的国家，`normalize` 只在 `scope_depends_on_regions`（CN 源与纯海外源答案不同）时采信，地点能说清一律以地点为准；workday 取 detail 的 `jobRequisitionLocation.country.alpha2Code`（`jobPostingInfo.country` 会错：赛默飞 Remote, Georgia 写成格鲁吉亚），任一地点沾大中华即判大中华。⚠️ **防来回跳**：国家查询不受 `CRAWL_DETAIL_CAP` 管（快档 / 重档同答案）；detail 4xx 是确定答复、照走兜底；超时 / 5xx 重试仍失败 → 该岗本轮不写库、`fetch_complete=False`。回归钉在 `crawler/test_declared_country.py`。live：新代码爬过的 45,692 行与预测逐行一致，国内→境外 708（+ 回填爬虫够不着的 60）、反向 0；DBS 快档 46s→307s（~300 次查询）。剩下 603 行里 540 行 detail 已 403/422（不对外），是探活问题不是 geo 问题。
- 🚫 **location 为空 ≠ 城市未知：标题里的城市在写库时物化进 location（2026-09-23 立）**：❌ 康龙化成「有机合成研究员-西安」、万物云「福州-项目管理岗（实习生）」location 为空，/today 城市门认「location 为空」放行、stage-2 判「城市未知」只降级 → 外地岗推给所有城市的用户（真实用户目标上海/杭州，7 张卡全在外地）。✅ 防：`geo.title_city_location` / `titleCityLocation`（两端共读 `tests/fixtures/title-city-cases.json`），经 `normalizer.location_or_title_city`（run.py + discovery 两条链）与 `lib/jobs-store/write.ts` 写库；**只在 adapter 给空时填、绝不覆盖**，带省 / 全国 / 海外段、公司名括号注册地一律不填。有地点的 34,990 行对照 98.0% 一致；存量已回填 3,372 行。⚠️ `normalize()` 里标题兜底必须排在 `geo_basis` **之前**（合并时栽过：排反了 location='西安' 而 country_code=NULL，`test_empty_location_falls_back_to_title_city` 钉着）。
- 📌 验收方法：拉全库 `distinct location`（约 2 万个写法）**逐条对拍改前 / 改后**，「大中华 → 境外」这个方向**必须为 0**。⚠️ 库里的 `location` 是**别名折叠之后**的文本，拿它、或拿 adapter `parse` 的出口量，都会和真实写库结果差一层——量地点类改动要把原始地点**完整过一遍 `normalize()`**（workday 能从 jd_url 路径复原原文，其它源只能 live 重抓）。逐条选词理由与实测数字 → `docs/module-deep-notes.md`。

## 🚫「接口返 0 / 403」不能证明「对方没开」（2026-09-04 立，一晚栽三次）

判一家公司有没有开校招，**唯一可信的依据是对方页面自己怎么说**（招聘公告、网申起止日期），
不是我们某个接口的返回值。已经栽了六次，全是同一个错：

| 公司 | 当时的「证据」 | 真相 |
|---|---|---|
| 哔哩哔哩 | 社招接口传 `recruitType=1/2` 返 `total=0` | 校招在**另一条 API**（`/api/campus/position/positionList`），372 岗；首页当天就挂着「2027届秋季校园招聘正式启动」 |
| 阿里巴巴 | `campus-talent.alibaba.com` 匿名 POST 返 403，判「login_wall」 | 不是登录，是 **CSRF**：GET 页面拿 `XSRF-TOKEN` cookie → POST 带 `?_csrf=`，1,075 岗 |
| 小米 | 飞书两个 `storefront_id` 返回**完全相同**的 1887 条，判「私有部署没有校招板块」 | 试错了维度，真正的开关是**请求头 `website-path`**，campus 764 / internship 554 / newretailing 121 |
| 百度 | 列表接口传 `recruitType=CAMPUS` 返 0 | 校招那一档百度自己叫 **GRADUATE**；传 CAMPUS 接口回 `Illegal argument : recruitType`，adapter 只看到 0 条就跳过。改对之后 157 个校招岗 |
| 华为 | 老门户 `reccampportal` 传 `jobType=2` 返 `totalRows=0`，判「对方没开」 | 校招 2026 年搬到新站 `career.huawei.com/cn/campus-recruitment` + 另一个网关；官网 2026-08-15 就挂着「2027届应届生招聘启动」。应届 69 + 实习 31 |
| 商汤 / 海底捞 | 飞书详情页 404 → `should_skip` 判「tenant detail portal closed」，整源跳过 | **门户好好的，是我们把 URL 前缀写死成 `index`**。租户首页自报 `"website_info":{…,"path":"exp"}` 才是唯一有效前缀。商汤 80 岗（原本 0）、海底捞 119 岗；海底捞更坏——列表一直正常，36 个在招岗带着必然 404 的 jd_url 躺在库里。**📌 2026-09-24 更正**：海底捞那 119 岗在公开门户上**全是「已下线」**（自报门户 072846 是校招站、公开首页「开启新的工作（0）」）——换前缀只让页面 200，内容仍是已下线；「详情页 200」≠「岗在线」，见下方飞书 website-path 一节 |

✅ 正确姿势：① 先渲染对方的校招页，看它自己写没写「XX 届校园招聘启动」+ 网申日期；
② 再从**页面自己发的请求**里找入口（拦 XHR / 读它的 JS 路由表），不要拿社招接口试参数；
③ 参数值也要从它的代码里读，别猜——**猜参数最容易骗自己**：曾以为「华为校招是 `jobType=0`，
   我们只试过 1/2/3」，2026-09-04 实测 `jobType=0` 同样返 `totalRows=0`；老门户压根没有校招，
   在那上面继续试参数是死路。校招在**另一个站另一个网关**上。
④ **「HTTP 200 + 空 data」同样是假阴性**：华为新网关少带任意一个 `x-*` 头
   （x-hw-id / x-jalor-tenantalias / x-language / x-alb-gray / x-referer）就返 200 但 data 为空。
   adapter 遇到这种情况必须**抛错记 failed**，不许安静返 0 条——安静返 0 正是错误结论的来源。
⑤ **别把「我们配错了」说成「对方关了」**：飞书那两家的教训是——报错信息本身
   （"portal closed"）就是个未经证实的**结论**，它把「404」直接翻译成了「对方关门」。
   404 只说明**这个 URL** 不通，不说明这个租户不招人。修法是让探测器先问对方
   「你的门户路径是什么」再判（`feishu._repair_detail_template`），修不好才跳。
   ⚠️ 但兜底不等于放开猜：全库 85 个飞书租户逐个 live 探完，只有 2 家需要走这条路，
   其余 83 家 `/index/` 本来就通——**「自报 path != index」推断出的 22 家坏源里 20 家是假警报**，
   靠的是逐个真探而不是靠推断。健康租户零额外请求。
⑥ **确实抓不了的要说清是哪一种**：快手校招 `campus.kuaishou.cn/robots.txt` = `Disallow: /`，
   这是合规红线不是技术问题，不要再去试；但同官网的**日常实习**在 `zhaopin.kuaishou.cn`
   （无 robots 限制、同接口同签名，只差 `positionNatureCode=C002`），1,046 个岗是能抓的。
⑦ 🔑 **点击只能证伪你走的那条路，证明不了全集**（2026-09-06 立，这是本节所有案例的共同根）。
   把「我没找到」升级成「确实不存在」只有一个办法：**捞出全站页面/路由清单再逐个看**。
   - 站点上了 Akamai（国家电网 `curl` 直接 412）时，**在已打开的页面里同源 `fetch` 它自己的 JS**
     就能绕过，同一招还能把全站页面清单捞全。国家电网正是这么判死的（12 个页面逐个看，
     `jobSearch/jobPost/jobColl/jobConc/jobJust` 全在登录区，清单里没有任何 jobDetail 类页面）。
   - 反例（同一天，同一个人）：国家能源集团看到公告页 `/annc/showg**g**?id=` 就以为摸清了
     `annc` 这条路径，真正的岗位页是 `/annc/showg**w**?id=`，**只差一个字母，3000+ 岗匿名可开**。
     ⇒ 见到「相邻路径」不等于摸清整条路径。
⑧ **「POST 回 405」= 打错主机，不是接口不存在**：中通打 `hr.zto.com` 任何 POST 都返 405，
   真网关写在 bundle 的 webpack 模块里（`PROD.HostName`），根本不在主域上。
   配套手法：network 面板抓不到 XHR 时去读 `js/app.*.js` 的路由表与接口名；
   **API 域名可能不在主域上**。中通由此从「无逐岗页」翻成 101 个岗（社招 79 + 校招 22）。

## ⚠️ 飞书招聘的校招岗藏在 `website-path` 请求头后面（2026-09-04 立）

同一个飞书租户可挂多个门户，**用哪个门户由请求头 `website-path` 决定**（与 URL 路径同名）：
不带该头 = 社招全集；`campus` / `internship` / `newretailing` = 各自独立的池子。纯 httpx 可达，
**不需要浏览器、不需要 `_signature`**（曾以为要签名，是因为重放时把这个头丢了）。

- **加一个租户的校招源零代码**：插一行 `source_url = https://{host}/campus/position` 即可，
  `FeishuRecruitAdapter` 按路径自动切门户与详情模板（`lib/source-adapters.ts` 不用动）。
- 🚫 **主门户按「公开门户」抓，不抓「不带头的全集」（2026-09-24 更正，创始人授权）**：
  ❌ 原文（2026-09-04 立）：「`website-path: index` 是更小的子集——蔚来不带头 2055、带 index 1801，少 254 个；
     `_bind_website_path` 把 index 当无子门户，钉在 tests 里别改」。错在只比了**条数**，没问多出来那批在公开页上是不是活的。
     从立碑起就是错的，库里一直躺着这批死链：死链巡检删了又被列表重抓回来（job_closures 飞书 URL 累计复活 11,581 次）。
  ✅ 实测（133 个飞书系源逐岗全量核，非抽样）：不带头多出来的岗，详情接口带 `website-path:<链接所在门户>` 读
     `channel_online_status=0`，公开页显示「该职位已下线」；⚠️ 这个状态**按门户算**——同一岗不带头读 1、带 index 头读 0。
     蔚来当天不带头 2,087 / 公开门户 1,794，多出的 591/591 已下线。上线后存量下架 11,092、补进 2,521、误杀 0，
     下架后 12 家各抽 1 岗浏览器实开 12/12 已下线。「不带头 ⊇ 门户」也不成立（超级猩猩 6 / 17，美宜佳 10 / 96）。
  ✅ 防：`adapters/feishu._httpx_fetch_main`——主门户 = 租户首页自报 `website_info.path` ∪ index，都带头取，
     每行按它真在线的门户拼 jd_url；index 门户不存在（接口回 `-9000003 site not exist`）算空门户；拿不到自报门户不标抓全。
     回归钉在 `crawler/test_feishu_httpx.MainPortalTest`。存量死链堆积时跑 `feishu-portal-reconcile.yml`
     （逐岗读状态、只下架读到 0 的、每源阳性对照 + 全局对照，默认 dry-run）。
  ⚠️ 小米私有部署偶尔**无视 website-path 头**返回全集（2026-09-23 newretailing 一轮抓回 2,075，正常 110）
     → 幽灵行占比过半、list-absence 安全闸清不掉，只能重跑对账工具。
- ⚠️ `portal_type` **不是**开关：带 `website-path: campus` 时传 2 或 6 返回同一批。

## ⚠️ 列表抓取上限与「短页误判末页」（2026-09-04 立）

- 单源列表上限统一走 `adapters/base.resolve_list_cap`（`DEFAULT_LIST_CAP=8000`，
  env `CRAWL_MAX_JOBS` 可整体调档，出事改 repo variable 即可、不用重新部署）。
  旧的 600 硬顶让 32 个源每轮漏 10.7 万个岗**且 status 全是 success**。
- ⚠️ 末页判据一律用「这一页有没有带来新岗位」，**不要用「本页条数 < pageSize」**：
  北森按 IP 限流（响应头 `X-RateLimit-Limit-<host><ip>-second: 50`），限流时回短页，
  一撞就整源截断（中国交建自报 2565 只抓到 800）。beisen/feishu 已改并加了退避重试。
- ⚠️ **上限调高会放大对同一 CDN 的请求量**，进而触发对方限流 → 反而抓得更少。
  改上限后必须做**逐源前后对比**（不是只看聚合缺口）：2026-09-04 那次聚合是
  「26 源多抓 3.1 万」，但同一轮里 20 个源少抓了 461 个岗，净值向好把回归洗掉了。
- ⚠️ **抬上限之后必须量「多进来的是什么」**，不能只看「多抓了多少」。2026-09-04 抬到 8000
  一轮多入库 5.2 万个岗，其中 **2.1 万（41%）是三家门店批量发布的同质副本**——
  星巴克 9,044 行归一后只有 36 种角色（96% 是「星级咖啡师」三种）、来伊份 7,301 行 90 种、
  喜茶 5,775 行 237 种。按城市看在招岗里这三家的占比：杭州 19.9% / 上海 12.1% / 北京 9.7%。
  → `adapters/base.RepetitionBrake`：连续 400 条没带来一个新的**归一标题**就停止翻页。
  判据必须用归一标题、不能用岗位 id（门店岗每条 id 都不同）。分离度实测差一个数量级：
  批量 99.6%/98.8%/95.9% vs 正常 奇瑞 47.7%/新东方 46.4%/我爱我家 42.7%，中间没有骑墙的源。
  ⚠️ 刹停 = 没抓全 → `fetch_complete` 必须为 False，否则 list-absence 会把没翻到的尾巴整批判撤岗。
  存量用 `crawler/collapse_bulk_duplicates.py`（+ workflow）按「角色 × 城市」折叠成 removed（可逆）；
  **写库必须显式点名公司**——「重复率高」有两种成因、处置相反（另一种是陈旧 active 堆积，
  比亚迪 6,313 行里 3,862 行三天没再被抓到，那是探活的活，折叠它只会掩盖问题）。
- ⚠️ **一页拿不到就 raise 会把整源扔掉**。顺丰 `_fetch_page` 原本在重试用尽后抛异常，
  结果「末页少 2 条 → 2,164 个在招岗全部丢掉」：expected_rows 是按**首页**的 totalResult 算的，
  而翻 217 页要 4~5 分钟，期间上下架必然让真实总数漂移。正确做法 = 返回拿到的那一页 +
  让 `fetch_complete` 如实记「没抓全」。少抓几条和扔掉整源，代价差三个数量级。

## ⚠️ 「渠道总数之和」当分母 = 造假缺口（2026-09-04 再立一次）

多渠道 adapter（社招/校招/实习分开查）里，**渠道之间可能互相重叠**，
`len(去重后) >= sum(各渠道 total)` 会恒为 False → 每轮都被记成「漏了几百个岗」。
- 小红书实测：social 858 + campus 406 + intern 302 = 1,566，但 intern 那 302 个 positionId
  **全部**已出现在 campus/social 里，去重后只有 1,263。
- 华为社招那边 2026-07-28 踩过同一个坑，后果更严重：`fetch_complete` 永远 False →
  依赖它的 list-absence 撤岗一次都没跑起来，官网只剩 9 个岗、库里压着 460 个 active 下不了架。
✅ 统一口径：**逐渠道判**「这个渠道抓到它自报的总数了吗」，全部为真才算抓全。
huawei / huawei_campus / xiaohongshu 现在都是这个写法，新增多渠道 adapter 照抄。

## ⚠️ crawl_runs：`running` 是占位符不是状态（2026-09-05 立，迁移 234）

`create_crawl_run` **在 insert 那一刻就写一个占位符**，跑完才由 `update_crawl_run` 覆盖成终态。进程半途死掉（CI 超时 / 取消、OOM、被 kill）这行就再没人回写。占位符原来是 `'skipped'`，于是「跑崩了」和「按设计跳过」**在 status 上完全同形**，而规则 F 只认 `failed` → 静默丢源。迁移 234 把占位符改成 `'running'`（对齐 `discovery_runs` 早有的 queued/running）。

- **判「没收尾」用 `finished_at is null`，不要只认 `status='running'`**：72 条历史孤儿没回填，至今仍是 `skipped` + `finished_at is null`，只认新占位符会漏掉它们。告警在 `ops_watchdog` 规则 I（`evaluate_unfinished_crawls`，宽限期 `UNFINISHED_CRAWL_HOURS=6`）。
- ❌ **快照里的「空记录」不等于崩溃**：2026-09-05 当场看到 10 个源（华为 / 字节跳动 / 伊利 / 顺丰…）留着空记录，**1~3 分钟后全部 success 收尾**——它们只是查询那一瞬间在飞。✅ 防：判据必须带宽限期，别把 `finished_at is null` 单独当证据（迁移 234 注释把这 10 条当成 CI 被杀的例子，**那条是错的**，已在规则 I 的 docstring 里更正）。
- ❌ **CI 全绿照样丢源，别直奔 workflow 超时**：2026-09-04 两批成因相反——19:11 的 `daily-job-crawl` 确实 failure + 步骤被中断（3 条）；而 09:32 的 `enrichment-crawl` **六片全 success、guard 也 success**，照样有 7 个 workday 源开跑后再无下文。✅ 防：看到规则 I 的告警，先确认那次 run 到底红没红，再决定查 CI 还是查 adapter。
- **终态两次都没写成**（成功路径 `update_crawl_run` 抛错落进 except、except 里再写 `failed` 又失败）→ 计进 `daily_crawl` 台账的 `ops_runs.metrics.crawl_run_unrecorded` 并打一条 `::warning::`。它是**唯一**能区分「进程被杀」和「进程活着但回写失败」的证据（上面 7 个 workday 源正卡在这个岔口，GitHub 日志已截断、事后无从复原）。⚠️ 目前没有告警规则读这个指标，排查规则 I 时要手动对读。
- **`skipped` 里曾混着「连不上」**：HEAD 预检失败被 `return f"Connection failed: {e}"` 记成「跳过」，而规则 F 只认 `failed` → 一个永久连不上的源可以无限期静默。已于 `729df39`（2026-08-28）改成 `except Exception: return None`（fail-open 且不进 host 缓存），live 复核修复前 53 条、**修复后 0 条**；AST 扫过全部 36 个 `should_skip` 覆写确认无一在 except 里 return 跳过原因，路径已封死。

🪞 **这块碑真正要记的教训**：我差点把这个**已修**的洞又修一遍。症状是从**线上存量数据**里查出来的（54 条历史行还躺在表里），读起来像「现在还在发生」，其实它 9 天前就停了。**看到存量里的坏数据，第一件事是查「最后一次发生是什么时候」**（`select max(started_at)` 一句话的事），不是直接去改代码——否则会「修一个不存在的问题」，还可能顺手把好代码改坏。

## ⚠️ 重档分片看「预计耗时」不看源数；量耗时、数漏抓查 crawl_runs 不查 CI 日志（2026-09-14 立）

❌ 现象：`enrich (2)` 09-08/10/11/12 撞 180min 被取消，每晚浏览器档只开跑 35~45 个、**27~37 个源当晚零 crawl_runs**；跑完的晚上这片也要 136~176min，而 moka 没卡住的晚上其余 5 片只要 40~84min。
✅ 根因：`_shard_by_host` 按**源数**装箱。国聘 28 源同主机 = 一队一个线程串行，这片线程池 91~134min，而浏览器档要等线程池整体结束才开跑，装箱器照样给它 72 个浏览器源。
✅ 防：`enrich-crawl.yml` 的 plan job 跑 `crawler/shard_plan.py`，按 crawl_runs 近 7 晚耗时装箱，产物分发给各片（`run.py --shard-plan`）。前向回测（第 N 晚只用 N 之前的历史，线程池复刻回放、与真实 job 差 1~3min）正常晚上最长片 175/173/151/135 → 114/131/91/107min；回归钉在 `crawler/test_shard_plan.py`。
- ⚠️ **计划只能算一次、各片共用同一个文件**：各片自己读历史会读到不同的行（别的车道一直在写 crawl_runs、gap_funnel 会删行）→ 映射不一致 → 漏抓 + 重抓。带了计划却读不到必须让这片失败，不许一片退回按源数、其余片用计划。
- ⚠️ **国聘那片的下限 = 国聘一队的串行耗时，装箱救不了**。再往国聘加源，这片会自己撞 180（plan job 会打「单个 key 自己就超了」的 warning）→ 那时要提速国聘或放宽它的同主机串行，加片没用。
- ⚠️ **6 片容不下「全体变慢」**：09-10~09-12 moka 卡 networkidle 那种浏览器档 ~3 倍变慢，回放新装箱最长片仍 179~204min；7 片 158~172、8 片 141~146。加片前先量香港库连接峰值（每片线程池 6 条）。
- 🚫 **CI 日志不能拿来量单源耗时、数谁没跑**：stdout 块缓冲，时间戳是一批一批落的，被杀的片尾巴日志直接丢。09-12 那片日志只列出 146 个源、日志里「国聘京东方跑了 55 分钟」都是这个假象——库里是 156 个并发源 + 38 个浏览器源开跑过、京东方 5.9 分钟。
- 🚫 **别用「那晚这个源在 crawl_runs 里有行」判定重档跑到了它**：campus-crawl / daily-crawl 同一时段也在给同一批源写行。判重档浏览器档跑到哪，要顺着「上一个 finished_at ≈ 下一个 started_at」的首尾相接链去数（这次先用「有行」数，得出每晚只漏 2~11 个，是错的）。

## 🚫 归属准确性没有旁路 —— 国聘集团展开曾 84% 挂错公司（2026-09-04 立）

`crawler/adapters/iguopin.py` 的「集团子公司展开」这条路径过去对 `_group_child` 行
**直接 return True、整个跳过核名**。后果：拿子公司名去关键词搜，而**国聘的搜索是集团级模糊匹配**，
把毫不相干的公司也捞回来挂到集团名下。全量复核 1,031 家，**862 家（84%）归属错误、2,439 个岗**：
「屯昌县劳动就业服务中心（华润集团）」「中信建投期货有限公司（恒力石化）」
「中国（海南）改革发展研究院有限责任公司（南方电网）」—— 国聘自己写着它们分别是
事业单位 / 地方国企 / 民营企业。用户按「华润」筛出来的是屯昌县劳动就业服务中心。

✅ 判据只能是**国聘自己的 `group_id`**（公司主页接口 `/company/index/v1/home`，按 company_id 缓存）。
修的过程试错两版，两版都错，别再走：
- ❌ **改用「子公司名」核名** → 放行 0 条。国聘搜索是集团级的：搜「海南电网有限责任公司」
  返回的鼎和财产保险是**真兄弟公司但名字对不上**，按名字核会把真岗全毙掉。
- ❌ **「查不到集团就保守放行」** → 照样挡不住。那家研究院是「查到了、但**没有**集团」，
  和「接口失败查不到」是两回事，混成一种就永远漏。
  三态必须分开：有集团 / 查到了无集团（**定论，拒**）/ 请求失败（放行，下轮重查）。
- ⚠️ 有集团口径时它对**所有**行生效，不只对 `_group_child`——直接关键词搜出来的
  国网国际融资租赁也是真子公司，名字里没有「国家电网」，按名字核会误杀。
- ⚠️ 归属结论只有 `fetch` 做得了（要联网查），`parse` 里没这个能力：用 `_attribution_ok`
  把结论带下去，否则 parse 的复查会按名字把真子公司**再毙一次**。

- ⚠️ **集团锚点不能是「搜索结果第一行」（2026-09-17 立）**：谁排第一取决于排序，同一个「华润置地」源，社招排序碰巧
  是华润的公司，加上 `nature=应届生` 后第一行变成中铝瑞闽 → 整源 40 家中铝子公司挂到华润置地名下；同批还有
  百胜中国→中国联通、京东方→「宁波吉德电器（京东方向）」、泰康→国投集团、中国建筑→中国建研院（这一个在**社招源上
  一直是错的**，只是没人看）。✅ 现行：按顺序试前 5 个不同公司，**集团简称或集团全称（`group_name`）过核名**的才当锚点，
  都不过就不展开（28 源双向对拍：11 不变、1 纠正、8 错集团被拦、8 原本就展开失败、0 新增误挂；中海油/中国能建靠全称救回）。
  锚点行自己的名字**不是**判据——「国网国际融资租赁」名字里没有国家电网却是真子公司。
- **国聘校招通道 = `&nature=115xW5oQ`**（国聘「应届生」性质码，取自 xiaoyuan.iguopin.com 真实跳转；接口要**数组**，
  传字符串返 total=None）。一家一条校招源（迁移 255），因为关键词搜索封顶 400、逐岗核验封顶 300，大集团的校招岗会被社招挤出窗口。

📌 通用教训：**为防张冠李戴造的门（`company_name_match`），不能被任何「可信来源」旁路绕过**。
「国聘说这些是子公司」听起来可信，但它给的是**搜索结果**不是**归属声明**，两者差着 84%。
存量复核工具：`crawler/audit_iguopin_attribution.py` + `audit-iguopin-attribution.yml`。

## ⚠️ 必投清单公司名 ↔ sources.company 的归属匹配（2026-08-27 立）

清单里存的是**品牌短名**（腾讯音乐 / 工商银行），库里 `sources.company` 存的常是**实体全称或带后缀**
（腾讯音乐 TME / 中国工商银行）。**用 `.eq()` 精确匹配会大面积对不上** ——
`campus_official_backlog` 就是这么每天空跑至少一周的：40 家目标里 30 家判「没有官方域名」直接跳过、
产出恒为 0（2026-08-27 实测：精确匹配可用 12/40，改归属匹配后 19/40）。

✅ 统一用 `crawler/must_apply.resolve_owner(name, must_apply.all_names())` / `sources_for(...)`。
规则 = **清单名必须是库里名字的子串，命中多个时最长的清单名胜出**。
- ❌ 不能用裸子串 `%京东%`：会把**京东方（BOE）** 算成京东 → 拿 boe.com 给京东的校招日期做接地，
  这是「归属准确性高于一切」的红线。
- ❌ 也不能用 `company_name_match.company_name_matches`：它防的是另一种坑（token 不在开头，
  如「北京华晋中通电力」≠ 中通），对「京东方 vs 京东」返回 True，挡不住这个。
- ⚠️ **只认单方向**（清单名 ⊂ 库里名）。写成双向包含会让库里的「京东」被更长的「京东科技」抢走
  —— 这个 bug 在实现时被单测当场抓到，用例已钉在 `crawler/test_must_apply_owner.py`。

## ⚠️ 名字对不上 ≠ 没有源：必投清单的别名 aliases（2026-09-04 立）

`resolve_owner` 是**单向子串**（清单名 ⊂ 库里名），救不了「字面完全不重叠」这一类：壳牌在库里记的是英文 `Shell`，缺口普查拿中文「壳牌」匹配不上 → 判「零源缺口」→ **插了第二条源** → 与已有源是同一个 Workday 站点仅大小写不同 → 大小写带进 jd_url、`canonical_jd_url` 区分大小写 → 唯一索引拦不住 → **同一个岗在库里存两行**（迁移 225 已修）。
📌 **「有岗但指标显示 0」比「真没岗」更危险——它会驱动人去重复补源。**
- ✅ 修法 = 清单条目可选 `"aliases": ["%Continental%"]`（ILIKE 模式，与 `pattern` 同语义）。**TS `mustApplyPatterns()` 与 Python `must_apply.company_patterns()` 共读同一份 JSON，改一边的语义必须同改另一边**，否则北极星与缺口台账会给出两个互相打架的数字。
- ⚠️ **加别名 = 改北极星口径**，必须逐条有据（库里真有这行公司名）；`tests/must-apply-list.test.js` 把当前别名清单钉死 + 张冠李戴门（别名不得命中同清单另一家）。
- ⚠️ **别拿改名当修法**：把清单里的「大陆集团」改成 `Continental` 会把 352 个海外岗算成国内供给。别名只改「怎么匹配」，不改「这家归哪份清单」。
- ⚠️ `owner_index()` 不传 scope = 国内+海外并集，此时**规范名恒压过别名**；要跨语言归属就明确传 `scope`。
- ✅ **必投覆盖率只数「本 scope 自己的岗」**（2026-09-05 创始人拍板）：此前两份清单共吃一个合计 → 海外清单的星巴克显示 1,920 个健康岗（实际全是中国门店岗）。缺口普查 `_JOB_AGGREGATE_SQL` 的 `job_scope` 必须**参数绑定、不拼字符串**；品牌 rollup 列同样过滤，否则海外岗会从父公司门户后门漏进国内覆盖。
- ⚠️ **「本范围 0」必须解释**，否则会被读成「供给没了」：台账记 `other_scope_healthy_jobs`，看板标「另有 N 个岗在海外/国内」（`otherScopeNote`）——前者要补源，后者什么都不用做。
- ⚠️ `job_scope` 只有 `domestic`/`overseas` 两个取值、无 NULL。真冒出第三种取值时**宁可不计入任一 scope**，也不要偷偷算进国内（`mergeScopeRows` 有断言钉死）。
- ⚠️ `unstable_cache` 条目**跨部署存活**（TTL 180s），上线那一小段缓存里是**旧形状**的行 → `scopedCounts()` 没有 byScope 时必须回退平铺合计，**不许改成直接 `byScope[scope]`**（会把 /admin/health 打挂）。
- 壳牌影子源全过程、口径切换的逐家实测数字、同类复查方法 → `docs/module-deep-notes.md`。

## 🚫 必投「healthy」不等于「校招接了」：渠道是独立一轴（2026-09-17 立，迁移 254）

❌ 现象：秋招季各行各业都开了，而国内必投 321 家里近 3 天有校招岗的只有 **171 家（53%）**：46 家只接了社招
（招行 / 民生 / 微众 / 快手 / 美的 / 比亚迪 / 顺丰 / 万科…）、20 家有源但零岗（农行 / 中信银行 / 国家电网 / 京东方…）、
89 家没源（中国银行 / 中信证券 / 宁波银行 / 三一 / 富士康 / 中国石化…）。台账却天天报 healthy。
✅ 根因：`must_apply_gap_attempts.state` 只回答「有没有健康岗」，一家社招 500 岗就算 healthy；源模型一家公司通常只有
一条社招 URL，「校招渠道」在指标里根本不存在 → **库里的 0 被读成「对方没开」**（同「接口返 0 ≠ 对方没开」那块碑）。
✅ 防：`campus_channel` 列（healthy = 近 3 天抓到校招岗，**产出反查优先**，社招门户也会出校招岗 / idle = 有 campus·mixed
源但零岗 / missing = 无校招渠道源），`gap_census.classify_company` 算、`ops_runs.gap_funnel.metrics.campus_channel` 记趋势、
/admin/health 供给页三张卡、看门狗规则 O 只在校招季（3·4·9·10·11 月）吵。
⚠️ 判「这家校招开没开」**只认对方页面**，不认我们的计数；idle 先查 `crawl_runs` 源坏没坏，missing 按平台分簇接
（hotjob / wt / beisen / moka），每家过探活门才入库。
- ⚠️ **`recruitment_category is null` = 「还没算」，不是「不是校招」（2026-09-17 立，迁移 258）**：它是被 `jobs_guard_recruitment_class`
  触发器主动作废等回填的缓存；backfill 名义每 2 小时、实跑约 4 次/天，全库 3,380 行 NULL 全是近 3 天新抓的。按它数数把 NULL
  读成 0 会静默制造假缺陷（24 家 idle 里 6 家纯属此）。census 现在把「渠道在 + 零校招 + 还有没算完的行」记成 `pending`，
  只降级 idle、不降级 missing。
- ⚠️ **ATS 自报的招聘类别就是事实来源，别让大小写把它吃掉**：北森 `Category`（校园招聘/社会招聘/实习生招聘）曾被通用 `_map`
  的小写键整包丢掉，16 租户 24,828 岗逐岗对拍：校招 +5,149 / 实习 +105、反向 45 条全是纠正，一致率 81%→97%。接 adapter 先问
  「对方返回体里有没有它自己声明的类别」。**绝不带 `Kind`**（"全职" 会被裁决成社招）。
- ⚠️ **列表有行却一条都映射不出来必须记 failed**：复星医药连着 33 次 success + 0 岗，根因是 `beisen_routes.json` 一条过期
  `ssr_path` 登记把每行 jd_url 拼成空串。「官网不存在」也只是我们的观测——中化 111 次 failed 只是搬了域名和 suiteKey。
- **校招车道**（`gap_funnel.process_campus_channel`，每轮 `GAP_FUNNEL_CAMPUS_CAP` 默认 5 家）：对 missing 的公司搜
  「{公司} 校园招聘 官网」，指纹认出平台后按平台换算校招板块 URL（`campus_source_url`：hotjob school.html / 飞书
  /campus/position / 国聘 nature=应届生 / moka 只认 campus-recruitment / 外企 ATS 无校招板块 → 不接），过同一道真抓验收门。
  结论只写 `evidence.campus_lane` + `campus_next_retry_at`（默认退避 7 天），**不碰 state / official_entry_url**——那是社招入口的账。
  - 🚫 **纠错（2026-09-23）：上面「按平台换算校招板块 URL」对国聘 / slug 车道从没生效过**。❌ 9-18~9-20 台账报「新增 10 个校招源」，
    实为 10 条国聘**社招** URL（不带 nature=应届生，board=social）；这些公司下一轮仍是 missing，再派生同一个社招 URL →
    撞「source_url 已由 enabled source 占用」→ 异常 +1 天重试，招行 / 比亚迪 / 海信 / 中海油 / 大悦城天天空转。
    ✅ 根因：换算原先包在 fingerprinter 外面，而带 preset 的候选根本不调 fingerprinter、国聘 URL 又是评估时才补的。
    ✅ 防：换算挪进 `_evaluate_candidates`（身份门与国聘补 URL 之后，`board_transform=_to_campus_board`）；
    `test_campus_lane_converts_preset_candidates_to_campus_board` 钉着，另有反向用例保证社招主队列不被换成校招 URL。

## 搜索额度是全局共享的 —— 贪心方必须给校招链留一份（2026-08-28 立）

`search_usage` 的每日额度是**所有链共用一个池子**。T3 洞察 drain 会一路吃到 0
（`cap = remaining`，队列多长就吃多久），而校招时间线链 cron 排在它后面 45 分钟
→ **每天开跑时 remaining 恒为 0、第一家就 break**。
实测 2026-08-21~27 连续 7 天 `ops_runs` 记 `companies_processed: 0`，
**却因为不抛异常一直报 success**（绿灯 ≠ 有产出，见「爬虫体检方法论」）。

✅ 修法 = `search_router.campus_reserve()`（env `SEARCH_RESERVE_CAMPUS`，默认 25）+
`remaining_above_reserve()`：**只有 T3 这类贪心方调后者**，校招链继续调 `remaining()`
把预留的那份真正用掉。设 0 = 回到旧行为。
⚠️ **别指望靠调 cron 先后解决**——那只会把饿死的换成另一条链。
⚠️ 以后再加吃搜索额度的链，先想清楚它是「贪心方」还是「被预留方」，别默认 `remaining()`。

## LLM 成本纪律（2026-08-27 成本审计后立）

**钱的 86% 烧在职业洞察 T3 一条链**（每家公司 = 主题数 × (1 writer + ~2.7 judge)，唯一的乘法结构）。
教训：**LLM 侧此前完全没有天花板**，花多少全看队列多长——账户 2026-08-25 欠费了都没人察觉，
因为**代码里从不记录 API 返回的 `usage`**，只能按字符数瞎估。

现行四道约束（改这块务必保住）：
1. **模型**：主 `Qwen/Qwen3-30B-A3B-Instruct-2507`（¥0.7/¥2.8）、降级 `THUDM/GLM-4-32B-0414`（智谱，
   **跨厂商是刻意的**——2026-07-31 DeepSeek-V3 整个系列被挤爆 100% 429 持续 3 天，靠降级扛住）。
   ⚠️ **降级模型绝不能选「思考模式」模型**：实测 `Qwen/Qwen3-8B` 同一 prompt 输出 269 tokens
   （非思考的只要 14-15），推理 token 会把 max_tokens 撑爆导致 JSON 截断——本项目栽过一模一样的坑
   （扩源那条链 max_tokens=2000 截断，LLM 喂清单从没成功过，见 commit f82ba7f）。
   换模型**必须先 live 验一次输出 token 数**再上。
   ⚠️ 模型名**不要带 `Pro/` 前缀**：`Pro/` 不是更好的档，但只能扣充值余额，非 Pro 还能吃赠费余额。
2. **日顶**：`crawler/llm_budget.py`（env `LLM_DAILY_CAP`，默认 250），在 `enrich_company_t3` 里
   按主题 gate、**按 engine 的真实调用数结算**（不按估算预扣）。
   ⚠️ 它是**成本闸不是安全闸**：读写计数失败一律 fail-open 放行（Supabase 抖一下就停摆整条链，代价更大）。
   ⚠️ 简历解析在 JS 侧（`lib/llm.js`），这个 Python 闸**管不到它**；豁免机制只是先把口子留着。
3. **用量记账**：每次调用打一行 `[llm-usage] model=… tag=… in=… out=…`（CI 日志可 grep 聚合），
   cron 收尾由 `E.record_usage_ops_run(sb)` 写进 `ops_runs`。**别再让花费不可观测。**
4. **省调用的两处**：writer 只喂前 8 条来源（`INSIGHT_WRITER_MAX_SOURCES`）；judge 之前先做引文子串
   预筛（`quote_supported()`，归一后比子串，空白/标点/全半角差异一律容忍——**宁可多花一次判官也不误杀**）。

## ⚠️ 校招专区首屏：只下发聚合分面，绝不逐条下发岗位（2026-09-02 立）

`/campus` 首屏曾 **responseEnd 10.1s / 单页 2.09 MB HTML**，而 TTFB 只有 189ms——**慢的不是取数排队，是 SSR 那一段本身**（把 30 家公司的 16,494 个校招岗逐条序列化进 props）。判读法记住：**`TTFB 快 + responseEnd 慢` = 生成 / 传输页面本身的问题**，别去查连接池和数据库。改动前务必读懂现行形态，别改回去：
1. **页面一条岗位记录都不下发**，只下发 `lib/campus-facets.ts` 的聚合分面 `[城市下标, 学历下标, 职能下标, 届别, 计数]`——客户端只用这四个维度填下拉和算计数（live 实测 16,494 条压成 1,917 个四元组，props 2,086 KB → 52.6 KB）。⚠️ **构建 `buildCampusFacets` 与匹配 `countMatchingFacets` 刻意放同一文件**：下标口径两端一漂，卡面就安静地报错数字——不报错、不崩，只骗用户；等价性由 `tests/campus-facets.test.js` 穷举全部筛选组合钉死。
2. **重活按行业清单缓存**（`unstable_cache` 10 分钟，只依赖必投清单、不含用户私有数据）。⚠️ `windowStatus` 与排序**刻意留在缓存外每请求现算**（依赖「此刻」的 72h 新鲜度阈值，一起缓存会把徽章冻住）；⚠️ 缓存函数体内**不得读 `cookies()`/`headers()`**。
3. **聚合 SQL 不用 `company ilike any()`**：带前导 % 用不了任何索引 → 39 万 active 行并行全表扫（live EXPLAIN 2567ms / 127,726 buffers）。改成先取全部 active 公司名走索引、JS 解析出确切名字、再 `company = any()`（957ms / 46,413 buffers，结果集逐行相同）。
4. **展开某家公司走 `/api/campus-zone/jobs`（按 公司+模式），不按 id**：按 id 取要先把 16,494 个 uuid 下发到浏览器（光 uuid 就 0.59 MB）。⚠️ 旧的 by-ids 调法有个真 bug——把 campus 与 intern 的 id 拼一起再截前 200，**大厂的实习桶被校招桶挤没、实习模式展开必然空白**。
   📌 **2026-09-15 起改为服务端按筛选分页 + 回精确 total（Phase B，去掉「前 200」硬顶）**：`getCampusCompanyJobs(list, pattern, bucket, {filters, offset, limit})`——归属+届别门+桶+分面筛选+排序全用轻字段（职能读物化列 `job_function`、桶读 `recruitment_category` 列），数清全部候选得精确 `total`，只给「这一页」取正文；前端抽屉按 `pattern|mode|filterKey` 累计分页 + 「加载更多」。**筛选必须服务端下推**（客户端只翻页不二次过滤），否则「看全部符合筛选的岗位」又会被单页截断。归属/届别门/桶口径与 getCampusZone 逐字一致（见第 5 条）。
5. **归属规则三处必须一致**（getCampusZone / getCampusCompanyJobs / 分面计数）：list 里**第一个 pattern 命中者得**（`腾讯音乐 TME` 归 `%腾讯音乐%` 不归 `%腾讯%`）。任一处漂移 → 卡面计数与展开列表对不上；live 交叉验证法：卡面计数与接口返回条数在未截断的公司上必须逐个相等。
6. **🚫 `unstable_cache` 的重算被杀 = 永远服务旧快照且不报错（2026-09-09 线上实锤，卡了 6 天）**：
   ❌ 现象：/campus 卡面 京东 0 / 小米 6 / 百度 2 / vivo 0、全部「数据待更新」，而库里是 127 / 852 / 158 / 166、
   `last_seen_at` 当天；不走缓存的 `/api/campus-zone/jobs` 返回的就是库里的数。卡面数字正好等于 09-03 打通前的快照。
   ✅ 根因：`loadCampusBoard` 重算要把 30 家 ~2 万岗**含 JD 正文（6.5MB）**拖回函数跑分类，live 数秒到十几秒；
   Hobby 档函数默认 10s，后台重算被杀后 Next 继续服务旧条目，且 Vercel 数据缓存**跨部署存活**——部署也刷不掉。
   ✅ 防：① page `maxDuration = 60`；② 快照带 `generatedAtMs`，页面渲染「数据更新于 N 分钟前」（服务端算成字符串再下发，
   见 `lib/relative-time.snapshotAgeLabel`）——**任何 `unstable_cache` 包着的重活都该这么做**，否则卡死无人知；
   ③ 重算打 `[campus-board] … ms=` 日志；④ 要刷掉卡死的条目，**换 cache key**（现为 v3），别指望 revalidate。
   📌 **2026-09-15 根因已拔除**：职能物化成 `jobs.job_function` 列后，`getCampusZone` / `buildCampusFacets`
   **不再拉 JD 正文**（facet 分类载荷 6.5MB→35kB），后台重算变轻、不再被超时杀。计数+徽章另由
   `getCampusFreshStats` 独立于快照取数（止血，保留为安全网）。详见 [[job-radar-campus-job-function-materialization]]。
   📌 2026-09-23：它和它依赖的「全部 active 公司名」都不再每请求打库——线上 /campus 首屏实测 8.8~10.1s，
   其中 `select distinct company` 已退化成全表扫 3.1s、fresh 聚合冷盘 3.6s，且公司名只有进程内缓存（多实例≈0 命中）。
   现为：公司名走松散索引扫描 + 跨实例 `unstable_cache` 5 分钟；fresh 走独立 60s `unstable_cache`（卡面「数据更新于」读它的 fetchedAtMs，卡住看得见）。
   ⚠️ 因此「别把 summary 从校招取数里砍掉」这条**已不再适用于校招链**（职能读列了）；`buildCampusFacets`
   现在读 `job_function` 列、仅列为 NULL 时才退回现算。`/jobs` 主搜索冷路径另说（见「/jobs 默认排序冷路径」段，仍未切）。
8. **「对你有货」的对口数必须算在 `unstable_cache` 之外（2026-09-17 立）**：必投清单是静态北极星，不因用户方向增删公司，
   变的只是先看谁。对口数 = 清单 ∩ 有该用户对得上的校招/实习岗，由 `lib/campus-facets.countFacetsForFit` 在同一份分面上算
   （共用下标编码，必须与 `buildCampusFacets` 同文件）。⚠️ 它吃用户私有画像，进了按行业共享的快照就会把 A 的方向算给 B 看
   （类型层用 `CachedCampusCard = Omit<…, fit*>` 堵死；live 30 家 7,537 岗只要 1~2ms）。⚠️ 下标数组为空有两种含义，靠
   `fnRequested`/`cityRequested` 区分「没填」（全放行）与「填了但对不上」（应为 0）。⚠️ 判不出方向 `fitCount` 记 null 不是 0。
   ⚠️ 对口数来自 10 分钟快照、总数每请求现算 → 必须夹上限，否则出现「对口 20 / 共 12」。
7. **SQL 粗筛必须是 JS 准入门的超集，且直接认 `recruitment_category` 列**：`CAMPUS_PREFILTER_SQL` 曾停在 2026-08-07
   之前的 url 正则（不认 moka 的 `-recruitment` / `_apply` 后缀、不认 `/internship/`），大疆 131/139、中兴 60/60 个
   「校招」在专区里静默消失。列与 JS 现算同源（`crawler/recruitment_classify.py` 隔进程调同一份 JS；live 对拍
   20,311 行零不一致），`campusAdmission` 有列就认列，正则只兜 NULL。契约测试 `tests/campus-zone-prefilter.test.js`。

## 🧪 「更准了」必须拿尺子说话：match-eval + 用户体验走查（2026-09-17 立）

- **精度尺子** `scripts/match-eval`（LLM 独立裁判，严格=同一具体角色）。⚠️ 判官必须 temperature=0 + 判决缓存：
  实测同一批 25 个岗（24 个相同）两次裁判严格准确率 88% 与 40%，尺子自己在抖时对拍出来的升降全是噪音。
  改任何召回/匹配/词库前后都要跑，报**逐画像**的严格准确率，不许只报「候选变多了」（本轮就是这么把「更准」说出口的）。
- **体验尺子** `scripts/ux-walkthrough/walkthrough.js`（每日 `ux-walkthrough.yml`，`ops_runs.ux_walkthrough`）：拿真实用户画像逐个
  模拟推荐 / 方向 / 洞察覆盖 / 校招专区 / 接口 TTFB。它第一天就抓到 7/44 用户推荐页 0 岗（手填岗位写法 4 人 +
  求职范围海外错配 3 人），这两类单测永远报不了警——只有喂真实画像才看得见。
  ⚠️ **检测器必须调生产端同一个函数，不许自己另判一遍（2026-09-23 立）**：`role_input_format` 曾只看原文有没有分隔符、
  方向命中曾拿没拆开的原文分类——09-20~22 每天报的 18 条里 **7 条是生产端早已处理好的写法**（「销售；采购」自 09-17 起就被
  `normalizeRolePhrases` 拆成两个方向，走查却把销售岗算成跑偏）。现在两处都走 `normalizeRolePhrases`。
  `role_mismatch_high` 分不清「库里没货」与「真被拦了」：动词库前先按 标题 × 城市 × 阶段 数库里有多少这类岗
  （09-23 那 7 条里 5 条是供给不足；真被拦的 2 条是叫法缺口，补了芯片验证 / 风控两组）。
- ⚠️ **「同职能」≠「同角色」，概念组里的领域锚点是最大的漏洞（2026-09-17 立）**：数据分析被推「大数据开发」、AI 产品经理被推
  「产品运营」、财务被推「财务科技全栈开发」——21 条独立裁判判错的岗 0 条是职能层捞的，全是标题只靠组里的**领域词**
  （数据/产品/品牌/财务）精确命中而标题真正的角色词属于另一个簇。防法 `GROUP_DOMAIN_ANCHORS` + `_titleRoleClusterConflict`
  （lib/china-keyword-expansion.js，/today 与 /jobs 共用一处）；**角色词绝不能进锚点表**。
  「准确率涨了」必须逐条对拍 top-25 进出名单——第一版净值向好里藏着 3 个被杀掉的真岗（「商务」认领、括号限定语当角色）。
- 匿名 `/api/jobs/search?sortBy=match` **不再拉 2.8 万行整窗**：无偏好打分全 0 = 纯新鲜度，走逐页攒够即停；有偏好才看满窗口。
9. **默认态 = 全部校招岗，「必投 30 家」只是一个入口（2026-09-18 创始人拍板）**：库里 active 校招岗 69,138 个 / 978 家（`recruitment_explicit` 口径，
   过当季届别门 66,051），而旧专区只给必投清单里的 ~30 家看——差两个数量级。现行形态：视图 A「全部校招岗」复用 `/api/jobs/search`
   （`jobType` 锁成 校招/实习 下推物化列，登录 match 走粗排 1000 窗，**SSR 不下发任何岗位行**，挂载后才请求）；视图 B = 原必投看板一字未改，
   顶部 Segmented 切换、localStorage 记上次选择。头部库存数走 `countCampusLibrary` + `unstable_cache` 300s，与列表候选同一份 where
   （双向对拍：列表有头部无 2,292 / 头部有列表无 0，只会少说不会多说）。⚠️ `jobType` 锁定有三条静默泄漏路径（筛选控件 / 已选 chip / 清空），
   契约测试 `tests/campus-all-jobs.test.js` 各有断言，别解开。设计与数字：`docs/superpowers/specs/2026-09-18-campus-zone-all-campus-jobs-design.md`。
- ⚠️ **改前 / 改后必须背靠背、同一份画像连续跑，否则库在动会被读成「代码回归」（2026-09-18 凌晨险些误撤）**：
  方向词分支合并后我隔了一段时间才跑 match-eval，读到 5 格下降（财务 A 96→48），当场撤回；对方做受控对照
  （`git archive` 出两棵树、共用一份 `parsed-profiles.json`、两轮交替跑）12 格逐格一致，我复跑同样一致——
  差的是这段时间里爬虫/探活改了候选池 + 判官对新岗的判决。✅ 防：对拍一律「基线-变体-基线-变体」交替连续跑，
  两轮基线不一致就先别下结论；「严格」口径对「财务分析 / 审计」这种宽方向天然敏感（24/25 是 same_family），看格子要连宽松一起看。

## 认证

Supabase Auth（邮箱登录）+ cookie session。`middleware.ts` 排除 `/api/*`，API 未登录返回 `401 application/json`，不被页面重定向拦截。Sources 页仅管理员。

**管理员判定**：页面 `lib/auth.isAdmin()` = `profiles.role === 'admin'`（开管理员 = 把该用户 `profiles.role` 改成 `'admin'`，不是环境变量）；`/admin/insights`、`/admin/health` 都用它做门。

**⚠️ 鉴权一律走本地 JWT 验签，禁止在请求路径上调 `supabase.auth.getUser()`（2026-07-30 定，live 实测 566ms → 0.7ms）**：Supabase 托管在**悉尼**，`getUser()` 每次都打网络到那里。统一入口是 `lib/auth-claims.ts` 的 `verifyRequestClaims(supabase)`（内部 `getClaims()` + **模块级 JWKS 缓存**），`middleware.ts` 与 `lib/apiAuth.requireUser()`（23 个 API 路由共用）都走它。
- **坑**：`auth-js` 的 `fetchJwk` 把公钥缓存在 **GoTrueClient 实例**上，而 serverless 每请求都新建实例 ⇒ 实例缓存永远为空 ⇒ 每请求改成拉一次 JWKS，等于用「取公钥」换掉「验 token」，一次往返都没省。**所以缓存必须在模块级、并用 `options.jwks` 显式喂进去**，改这块务必保住此不变量。
- JWKS 缓存 TTL 固定 **10 分钟**，对齐 Supabase 官方 Edge 缓存时长；缓存更久会在密钥轮换/吊销后误拒仍然有效的 token。
- 项目已启用 **ES256 非对称签名**（实测 token 头 `alg=ES256`、`kid` 与 JWKS 一致），本地验签直接生效、无需控制台操作。若哪天退回对称密钥（HS256），`getClaims` 会自动回落 `getUser`——不会坏，只是不快。
- **取舍**：本地验签只证明「签名有效且未过期」，封禁 / 改邮箱要等 access token 过期（默认 1h）才生效。需要 Auth 服务器权威最新记录的场景才显式用 `getUser()`。

**页面取当前用户走 `lib/auth.getRequestUser()`，别在页面里再验一次（性能）**：middleware 已对每个页面请求做过安全级验证 + 会话刷新 + 未登录重定向，并把验证后的 `user.id/email` 注入转发请求头 `x-user-id`/`x-user-email`（仅服务端可见、入口先 delete 防伪造）；页面用 `getRequestUser()` 零网络读取。注意：① `/api/*` 不经 middleware，仍各自 `requireUser()`；② 改 middleware 的请求头转发时，cookie 头须在验证之后用刷新过的 `request.cookies` 重写，否则 token 刷新那一拍页面会拿到过期 cookie。

**客户端组件不要自己调 `supabase.auth.getUser()` 拿登录态**：那是浏览器直连悉尼的一次跨洋往返。改由服务端外壳透传——`components/Navbar.tsx` 即此模式（服务端读 `getRequestUser()` → `<NavbarClient initialEmail=…>`，20 个引用点无需改动），顺带消掉「先闪一下未登录顶栏」。

**冷启动 / tab 切换不卡**：每个数据页路由配 `loading.tsx`（复用 `components/Skeletons.tsx` 暖纸骨架 + 真实页头），force-dynamic 路由没有 loading 边界会「点 tab 冻屏 + prefetch 失效」；页面内互不依赖的服务端 `await` 用 `Promise.all` 并行。详见记忆 `job-radar-cold-start-tab-latency`。

## 简历画像

粘贴文本 / `.txt` / `.md` / PDF / Word(`.docx`) / 图片 → candidate profile → 用户确认后同步 `user_preferences`（只服务排序，不替代检索）。英文简历作为可选 variant 写入 `candidate_profiles.en_target_roles/en_skills/en_target_keywords/has_en_resume`，仅在求职范围为海外或全都要时优先用于海外匹配；国内范围继续走中文档案。空文本返回 `400 empty_resume_text`。

## 开发规范

- 按现有风格改，最小化改动，不做无关格式化/重构。
- 复用已有 lib / components / 类型，不引入重型依赖。
- 不吞错（catch 至少记录）。
- 外部请求只走 lib 层封装与 crawler adapters；遵守合规边界。

### 设计组件库：新代码一律走 `@/components/ui`，别再手写（2026-09-04 立）

产品有自己的组件库（21 个原语 + `lib/ui/hooks.ts`）。**写任何前端之前先看一眼有没有现成的**——改造前 28 个文件各写各的 `<button>`、9 个各写各的转圈、6 个各写各的「锁滚动 + ESC」、`inputCls` 同一串样式存在**三份**、全站 5 个弹层**一个焦点陷阱都没有**。
**完整用法、加 / 退役组件的规矩、Radix 取舍、动效令牌全在 `DESIGN.md` 的「组件库」一节**（`/design` 页跑的就是产品里真实那一个组件、同一份 CSS，所以它不会说谎），决策来由见 `docs/superpowers/specs/2026-09-04-design-system-component-library-design.md`。正文只留七条硬红线：
- **一律从 barrel 进**：`import { Button } from "@/components/ui"`，不深链具体文件。
- **组件库内禁止出现 hex 色值**：颜色一律走 `--tone-*` / `--ink-*` 令牌（七族语义色，明暗自动切换）；要加新色**先在 `globals.css` 定义明暗两套 + `tailwind.config.js` 登记**，再用语义类名。
- **动效不许写死毫秒和贝塞尔**：用 `--spring-{smooth,snappy,bouncy,press}` + `--dur-{press,toggle,panel,sheet}`（按 SwiftUI 弹簧方程解出来的，调手感跑 `scripts/gen-spring-easing.py`）；按压反馈用 `.press-feedback`（scale 0.97，**不是 0.9**——0.9 会读成「这东西要被删掉了」）。
- **变体表写在 `lib/ui/variants.ts` 这个 `.ts` 里**，不要写进组件的 `.tsx`：`tests/_load-ts.js` 只认 `.ts`，放对地方契约测试才能真加载它做断言。cva **只加尺寸轴**，颜色继续由 `.btn-*` 等既有类提供——往变体表里抄颜色 = 制造第二份颜色定义。
- **可访问性做进原语，不靠调用方记得**：`Modal` 默认带焦点陷阱 + `role="dialog"` + `aria-modal` + 锁滚动 + ESC；`Segmented` 的 `ariaLabel` 是**必填 prop**。靠人记得写的 aria 迟早会漏。
- **废弃组件搬进 `components/ui/deprecated/` + 打 `@deprecated`，不要直接删**（学 GitHub Primer）；存量迁移 = **新代码必须用库、老代码碰到再换**，不做一次性全站替换。迁移判据是**「能不能证明像素不变」**：只有亮暗成对出现在同一类串里才换令牌，只有亮色没 `dark:` 的一律跳过；归并「差一点点」的同类颜色属于**有意的视觉改动**，要创始人拍板。
- 🚫 **Tailwind UI 是商业授权**（常被误认为开源）、**Aceternity** 禁止转售衍生品、**Magic UI / Motion Primitives** 要装第二个动画运行时（已有 GSAP）——都不用。抄 MIT 代码进仓库必须在 `LICENSES/` 留版权声明。
契约测试 `tests/design-system-contract.test.js`（13 条）守着以上规矩，新增组件请顺手补断言。

### 点击反馈分档：每个异步操作都要有中间态 + 结果态（2026-09-03 立）

创始人定的方向：这个产品的前端是**重交互、重细节**的。凡是「点一下要等服务端」的操作，
用户必须看见两件事——**它在跑**、**它成没成**。按频次分两档，别混用：

| 档 | 用什么 | 适用 |
|---|---|---|
| 重提交（低频，用户要停下来等结果） | `components/SaveToast.tsx`（居中，转圈 → 打勾/叉，自动消失） | 保存资料 / 保存偏好 / **AI 解析简历** / 保存简历画像 / 校招反馈 |
| 就地操作（高频，结果已经写在按钮上） | `components/ActionToast.tsx`（底部胶囊，1.8s，不遮内容不阻断；带「撤销」的自动延到 4s） | 值得投 / 标记投递 / 忽略 / 取消值得投 / 后台审核 |
| 取数、翻页 | 按钮内 pending（转圈 + 文案）+ 骨架屏 | 加载更多 / 刷新公司库 / 搜索 |

- **失败绝不许静默**。踩过的实例：`SourceTable` 的启用/禁用开关失败时什么都不做（用户以为切成功了）、
  `saved-client` 取消值得投失败只是把卡片悄悄放回去、`CompanyInsightDrawer` 申诉 `!res.ok` 直接吞掉。
  这三类「点了像没反应 / 像成功了其实没成」比慢更伤信任。
- ⚠️ **别拿乐观更新的回调当成功提示**：`JobCard.onActionChange` 在乐观更新和失败回滚时**各调一次**，
  用它弹 toast 会把回滚说成成功。落库后的结果走 `onActionResult({jobId, action, ok})`。
- **岗位动作文案只有一份**：`jobActionToastText()`，`/jobs` `/saved` 共用（`/today` 有自己带「撤销」的 toast）。
- 站内不用原生 `alert()`：阻断、样式与全站不一致，且移动端体验差。
- 契约测试钉在 `tests/ux-hardening-contract.test.js`（「点击反馈契约」一段），新增异步交互请顺手补断言。

### 会被 SSR 渲染的日期一律走 `formatDateLabel`，禁止裸 `toLocaleDateString`（2026-09-02 立）

`toLocaleDateString` / `toLocaleString` 按**运行时**时区格式化。**Vercel 函数跑 UTC、浏览器跑用户本地时区（国内 UTC+8）**，
于是同一个时间戳 SSR 渲染成「2026/8/30」、hydration 渲染成「2026/8/31」→ React 判定文本不一致 →
**Minified React error #418，每次加载必现**（2026-09-02 实测 /today /jobs /campus 三个页面全中）。

- ✅ 防：`lib/relative-time.formatDateLabel(input, options?)`，内部钉死 `timeZone: "Asia/Shanghai"`。
  岗位发布日 / 截止日 / 投递日本来就是「北京时间的哪一天」，与看的人在哪儿无关，两端因此必然一致。
- ⚠️ **不要用 `suppressHydrationWarning` 掩盖**——那是真不一致，用户首帧看到的是错的日期。
- 判断要不要改：**这段文字会不会进服务端渲染的 HTML**。挂载后才 fetch 再渲染的（SourceTable /
  CompanyWatchQueue / InsightsAdminClient / CompanyInsightDrawer / JobLibraryStat 的「最近同步」）
  不参与 hydration，可以不管。
- ⚠️ **本地默认复现不出来**：`npm run dev` 的服务端和浏览器都是 Asia/Shanghai。要复现必须
  `env TZ=UTC npm run dev`（对齐 Vercel）或 `TZ=America/New_York`（更容易越过日界）。
- 回归测试钉在 `tests/relative-time.test.js`（跨 3 个运行时时区断言同一输出）。

### 排版与文字颜色：一律用语义类，禁止再写 inline hex 文字色（2026-09-02 立）

`app/globals.css` 有一套语义排版系统，**新代码必须用它**，不要再写 `text-[#5f594e]` 或
`text-[13px]` 这类散装写法。

- **字阶**：`.t-display`（页面主标题）/ `.t-h1` / `.t-h2`（区块标题）/ `.t-h3`（卡片·组标题）/
  `.t-body`（正文 15px）/ `.t-body-sm`（次正文 14px）/ `.t-label`（表单标签·按钮 13px）/
  `.t-caption`（元信息 12px）/ `.t-micro`（徽标 11px）/ `.t-num`（数字，等宽 tabular-nums）。
  每个类把「字号 + 行高 + 字重 + 字距 + 墨色」一次给全，调用方不再各写各的。
- **墨色**：`.ink-1`（主）/ `.ink-2`（次）/ `.ink-3`（标签）/ `.ink-4`（占位·禁用）。
  **明暗两套值都在 CSS 变量里，用了 ink-* 就不要再加 `dark:` 变体**（会盖掉它）。
- **字重只用 400 / 500 / 600 / 700 四档，正文一律 400。** 改造前全站 98% 的文字挤在
  medium(500) 与 semibold(600) 两档，等于没有层级，满屏「中等粗」看着又平又糊——这是
  「字体丑」的主因，不是字体文件的问题。
- **中文行高比英文大一档**（正文 1.7），中文正文字距不收紧（0），只有 ≥18px 的西文/数字
  标题才用负字距。
- ⚠️ **对比度是硬要求**：旧的三级色 `#9a9184` / `#8a8275` 在暖纸底 `#f4efe6` 上对比度只有
  2.9:1 / 3.2:1，**低于 WCAG AA 的 4.5:1**，这就是用户反复反馈「关键信息太浅、看不出」的
  量化根因。`--ink-3` 已压到 `#6b6355`（≈5.0:1）。新加文字色前先算对比度，别再退回去。
- **字体栈**在 `--font-sans` / `--font-display`，按「西文在前、中文在后」排：西文走
  SF Pro / Segoe UI，中文自动回落 PingFang SC / 微软雅黑。**反过来把中文字体提前会让西文
  也用中文字体的拉丁字形（又宽又丑），是中文站最常见的字体错误。** 仍不引入 webfont
  （规避国内 Google Fonts 封锁 + 离线构建不挂）。
- **语义色不归墨色管**：蓝 `#3f7cc0`/`#7fb2e8`、绿 `#3fae6a`/`#a3d06a`、橙 `#d08a4a`
  这些是状态语义，照旧写具体值，别塞进 ink-*。

### 筛选器：不做展开/收起（2026-09-02 立）

`components/JobFilters.tsx` 是「顶部吸顶 filter bar + 「更多」弹窗（标题「筛选」，移动端入口叫「筛选」）+ 已选 chip 行」形态。
竞品调研（BOSS/拉勾/猎聘/智联/51job/LinkedIn/Indeed/Wellfound 8 家）结论：8/8 都用吸顶
filter bar，而「维度放不下」的业界标准解法**不是折叠手风琴，是把溢出维度收进「更多」
弹层**。所以：**不要再往筛选器里加 `<details>` / 手风琴 / 折叠区**，加维度就往
弹层里放。契约测试 `tests/ux-hardening-contract.test.js` 守着这条。
- 岗位职能的可选值域**唯一来源**是 `lib/china-keyword-expansion.js` 导出的
  `JOB_FUNCTION_BUCKETS`，UI 从它渲染。加职能桶只改那一处，别在 UI 里留第二份硬编码，
  否则用户会筛到永远不可能命中的「幽灵条件」。
- ⚠️ **筛选条里的弹层必须 portal 到 body，禁止 absolute 定位在条里**：筛选条内层是
  `overflow-x-auto`（移动端要横滑），而**滚动容器两个轴都裁剪**——463px 高的弹层会被裁进 42px
  高的条里，`[role=dialog]` 在 DOM 里明明存在、屏幕上什么都不出现，用户只会得出「这些按钮
  点不了」的结论（2026-09-02 线上实测确认，创始人正是这么反馈的）。修法 = `createPortal` 到
  body + `fixed` 手动锚位 + 监听 `scroll`(capture) / `resize` 重新对位。契约测试已钉死。
- ⚠️ **「更多」打开的是居中弹窗，不是侧边抽屉**：抽屉的遮罩只有 `bg-black/30`，在浅色底上几乎
  看不出来，筛选条看着还是亮的、像能点，实际点到的是遮罩。现行形态 = 桌面端从「更多」
  按钮放大展开的居中弹窗（点击那一刻量按钮矩形 → `--fx/--fy/--fs` 喂给 CSS keyframe），
  移动端底部 Sheet；遮罩加深到 `#1a1714/45` + 模糊，背景明确读成不可交互。
- ⚠️ **弹层的「点外部关闭」要连自己的触发按钮一起豁免**：关外部逻辑挂在 window 的
  `pointerdown` 上、判据是「目标不在弹层内」，而触发按钮本来就不在弹层里 → 点它会先被判成
  「点了外面」而关闭、紧接着的 `click` 又把它开回来，**净效果是同一个按钮永远关不掉**。
  修法是让「触发按钮 + 弹层」的包裹层 `stopPropagation` 掉 pointerdown，已有回归断言钉死。

## 测试规范

- 纯函数优先（scoring、live-search 格式化/校验、normalizer、quality gate、discovery budget）。
- crawler 用 unittest，单测不打真实网络。
- 改 schema 必须同步更新 migrations + 测试（schema 以 migrations 为准，需求文档以 `PRD.md` 为准）。

## 边界（Phase 1 不做）

自动投递 / 登录企业招聘系统 / 绕验证码 / 第三方招聘平台 / PDF·DOCX 复杂解析 / 邮件·飞书·微信推送 / Redis·Celery·K8s·监控大套件 / 无关 UI 大改。

> 注：LLM 不再是硬边界——按「必要时克制接入」原则使用（见 `PRD.md` §0 LLM 使用原则）；已落地简历解析（lib/llm.js）+ 洞察 AI 辅助草稿，岗位匹配/JD 摘要按需可接入、非强制。

## 禁止事项

未经允许不 `git push` / `reset --hard` / `clean`；不读取或输出 `.env*`、service_role key 等密钥；不 force push main；不跳过 hooks。

### ⚠️ 公开仓库红线（2026-08-07 立，含自动门禁）

**本仓库是 GitHub PUBLIC 的**：文件内容、提交历史、提交者姓名邮箱全世界可见，且**事后删除也撤不回**（别人 clone / fork 的副本、GitHub 缓存都还在），只能靠重写全部历史 + force push，代价极高。所以拦在提交之前。

**四类内容一律不许写进任何被跟踪的文件（含 docs / 计划 / 交接单 / agent prompt）**：

| 禁写 | 改用 |
|---|---|
| 本机绝对路径（`/Users/…`、`/home/…`）——暴露电脑用户名，本项目的用户名恰好是公司名 | `<项目根>`、`~/`、相对路径 |
| 服务器公网 IP / 主机名 / 端口组合（如香港 jobs 库） | 「见 `JOBS_DATABASE_URL` secret」 |
| 真人姓名 / 私人邮箱 / 手机号 / 微信号 | 省略，或写角色（「创始人」「PM」） |
| 任何密钥、token、带账号密码的连接串 | 只进 GitHub Secrets / Vercel env / `.env.local` |

**提交身份必须配好**，否则 git 会退化成 `<系统用户名>@<主机名>`，把电脑用户名永久写进公开记录（本仓库已因此留下 34 个作者名为公司名的提交）：

```bash
git config --global user.name  '<你的 GitHub 用户名>'
git config --global user.email '<你的 GitHub noreply 邮箱>'   # GitHub → Settings → Emails 获取
```

**自动门禁**：`.githooks/pre-commit` 在每次提交前查身份 + 扫内容，命中即拦。规则在 `scripts/scan-sensitive.sh`。
- 启用（每个 clone 一次，`npm install` 会自动执行）：`git config core.hooksPath .githooks`
- 定期体检全库：`npm run scan:sensitive`
- 误报处理：优先改写内容用占位符；确属误报在脚本的 `*_ALLOW` 里加豁免。**不要 `git commit --no-verify` 绕过**。

## 项目特殊注意事项

1. **⚠️ 运行前提 = .env.local**：必须有 `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`。数据库迁移由 CI 自动 apply（见上文「数据库迁移（已自动化…）」），无需手动跑 SQL。绝不提交 / 读取 / 打印这些密钥值。
2. **⚠️ 父级 CLAUDE.md 混淆**：家目录 `~/CLAUDE.md` 描述的是另一个项目（余声/YuSheng），会被当作父级上下文加载。本项目是求职雷达，与 YuSheng 无关，冲突时以本文件为准。
3. **build 与 dev 不要同时**：dev server 运行期间跑 `npm run build` 会改写 `.next`，导致旧 dev server 静态资源 404；build 后要重启 `npm run dev` 再做浏览器验证。
4. **沙箱限制**：环境可能禁止监听端口 / 阻断网络（Supabase / 百度 / 京东 live）；`git push`、live SQL / 链接验证也需用户本机执行，不能用本地单测冒充 live 验证。
5. **Vercel 实时 upsert**：必须把 `SUPABASE_SERVICE_ROLE_KEY` 配为服务端环境变量，绝不暴露给浏览器。

## 测试账号（需先在 Supabase 建好）

`test@jobradar.local` / `test123456`
