# 求职雷达 / Job Radar — 项目级 Claude Code 指南

> 本文件指导 Claude Code 在本仓库工作。规则优先级：当前明确指令 > 本文件 > 全局 `~/.claude/CLAUDE.md` > 默认行为。

## 项目概览

- 项目名称：求职雷达 / Job Radar Private Beta v0.1
- 项目类型：3–5 人内测版「公开企业官网岗位雷达看板」Web 应用
- 主要技术栈：Next.js 15.5.18 App Router + React 18 + TypeScript + Tailwind；Supabase（Auth / Postgres / RLS）；Python crawler（httpx + selectolax）；GitHub Actions 定时抓取
- 包管理器：npm（前端）/ pip（crawler，见 `crawler/requirements.txt`）
- 运行环境：Node.js `^18.18.0 || ^19.8.0 || >=20.0.0`，Python 3.11+
- 部署：前端 Vercel，crawler GitHub Actions
- **⚠️ 函数区域锁定香港 `hkg1`（`vercel.json` 的 `regions`，2026-07-30 加，别删）**：jobs 热表在香港自建 PG，函数默认区是美东 `iad1`，跨太平洋让「建库连接」这一步就要 800~1400ms（内测低流量下 `lib/jobs-store/client.ts` 的 `idleTimeoutMillis:10s` 使几乎每请求都重新握手），实测 `/api/jobs/stats` 曾要 6.6s 甚至超时。改到 `hkg1` 后与 jobs 库同城。诊断方法：`curl -D -` 看响应头 `x-vercel-id`，前缀即实际执行区域。
  - Vercel Hobby 也可选区域（限单区）；**但 Routing Middleware 不跟随该设置、固定全球边缘跑**——middleware 里的跨洋开销只能靠「不联网」消除（见「认证」段的本地 JWT 验签）。

## 核心闭环（产品第一目标）

```
公开企业官网岗位
  → crawler 抓取 / 已知源刷新 / 官方源发现候选
  → jd_url 质量门校验
  → 标准化入库 jobs
  → 用户偏好规则打分排序（lib/scoring.ts）
  → Today / Jobs 看板
  → 点击跳转官网详情
  → saved / ignored / applied 反馈
```

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
   ⚠️ **2026-07-02 方向更新**：产品已正式上线，`~800` 源不够用了 → 转入**「在保精度基础上逐步扩量」**（用户 2026-07-02 定调，优先于下面 2026-06-15 的「停止铺量」旧调）。落地 = **每日自动定向扩源已启用并真入库**：`auto-discover.yml`（httpx，每日 UTC 23）+ `auto-discover-browser.yml`（beisen/moka 浏览器，每日 UTC 21）跑 `crawler/auto_discover.py` / `auto_discover_browser.py`，从精选目标公司清单里取库里没有的公司 → live 探活 → **只入「探活通过 + 真有在招岗 + 标题核验防张冠李戴」的源**（精度红线不变，猜错/无岗自动丢）。三管齐下提产出：① `crawler/targets_tech_consumer.json`（149 家科技/互联网/新经济/消费/游戏/AI/智能硬件/SaaS 目标公司，每家多 slug 变体，`_priority` 优先探，纠正旧清单 76% 传统制造与目标用户错配）；② 提转化（多 slug + 优先探对方向）；③ 提每日配额（httpx target 30→80/insert 20→40，browser tenant 60→120/confirm 10→15）。**扩量 = 定向补目标用户要的科技/消费公司，不是无脑铺量**；仍禁止猜 slug 直接入库（靠探活门兜底）。管理员看板「自动扩源」卡可看每日产出。
   **④ 持续喂清单（LLM 生成器，`crawler/generate_targets.py`，2026-07-02 加）**：静态清单会烧完 → 每日在两个 auto-discover CI 里用 SiliconFlow（复用 `insight_engine.chat_json`，env `AUTO_DISCOVER_LLM=true` + `SILICONFLOW_API_KEY`，按行业主题按日轮转）生成一批「库里没有的」真实公司候选，喂给**同一条探活验证门**（编造/猜错 slug 探活不过自动丢，绝不入库）。`AUTO_DISCOVER_LLM` 一关即回退纯静态清单。诚实边界：LLM 的真实公司宇宙有限（几千家量级），能把库从 ~900 持续喂到几千、撑很久，但不是无限高速。
   **⑤ 缺口漏斗（2026-07-27 加，专治必投清单覆盖）**：上面①-④是「按公司清单猜 slug 探 4 个平台（feishu/hotjob/beisen/moka）」，对**非互联网行业结构性够不着**——银行/央企/外企/自建门户不在这 4 个平台上，实测 151 家必投缺口里 150 家在 sources 表连一行都没有，且 120 家天天被猜天天 0。补上的是 `crawler/gap_funnel.py` 这条**搜索找入口 → 平台指纹 → 已有 adapter 路由 / company_spa → 真抓回读健康岗才入库**的漏斗（`gap-funnel.yml`，默认 dry-run，失败按原因退避不空烧）。
   **国聘（iguopin.com，国资委官方央企招聘平台）是「第三方平台禁令」的唯一例外**（创始人 2026-07-26 拍板）：央企大多没有逐岗官方详情页，国聘是唯一能拿到稳定 jd_url 的官方渠道；智联/BOSS/前程无忧/猎聘 红线不变。
   下面 2026-06-15 的「停止铺量」原则保留作**精度约束**（砍低质量、保稳定、扩源必 live 验证），但**扩源本身不再暂停**：
   **旧调（2026-06-15，现降级为精度约束）：不再以「源数量」为唯一指标，不搞无脑大规模铺量。** ⚠️ 旧「866 源里仅 ~327 在产出、539 个（62%）0 产出」已过时——2026-06-19 db-report 实测源池已健康：**~835 enabled、~98% 在产出，仅 ~15 个 0 产出**（且多为目标相关但当前无开岗的科技/半导体/智能车公司，监控即可；当天已 disable 14 个明确低相关的传统制造/医药/重工/校招结束死源）。产出仍偏向车厂/央企/制造 + 外企海外岗，与目标用户（科技/新经济/消费求职者）部分错配。MVP 阶段目标 = 让**少而精**的高质量源**稳定**产出**目标用户真正要的**岗位；**扩大规模是后期的事，现在搞一堆低质量公司源没用、只拖累信噪比**。
   - **指标换成「目标相关的有效产出」**：不看有多少源，看多少源在稳定产出 *目标相关 + 带 jd_url + 有 JD 正文* 的高质量岗位。
   - **砍低质量**：0 产出 / adapter 已坏 / 与目标用户无关的源，优先 `disable`（保留行可回滚，别删），不留着拉低信噪比。
   - **保可靠稳定**：只留能过质量门、稳定逐岗 `jd_url`、且能被现有抓取链路**可持续抓到**的源——别加 daily 抓不过来的源（浏览器源串行单个 2–5min，daily CI 预算有限）。头部高价值源 daily 抓，长尾降频 / 按需（「更新关注公司」接长尾）。
   - **扩源后置且定向**：确需加源时只**定向补缺失的目标公司**（如比亚迪 / vivo / 顺丰 / 荣耀 / 货拉拉 / 微众 等科技消费大厂），必须 live 探活确认稳定产出真实岗位后才留（禁止猜 slug 入库）；不再随机铺量、不再把「新增 adapter」当最高优 backlog。
   - 「中国本土 > 外企」「私企500强 > 国企央企」的**相对偏好仍然成立**（用于排序与定向补源的取舍），但服从于上面的「精 > 量」总原则——**不是再去大规模铺本土源**。
   - **列表抓取夹带已关闭岗（2026-06-15 查实；结论：靠 sweep，list 端过滤做不到）**：wt / hotjob 的列表接口会返回**已关闭的岗**（wt 52% / hotjob 71% 抓进来即被 sweep 判死，2026 春招/暑期实习收尾期尤甚）。**已 live 验证 list 端没有可靠的「关闭」字段可过滤**：hotjob `canDelivery=false` 在「在招」岗上也为 false（华夏银行 live 岗 15/15 都是 false）→ 不可用；wt 列表里夹带的已关闭岗与在招岗**除身份字段（postId/postName/workPlace）外无任何区别**（endDate 仍是未来日期）。唯一可靠的关闭信号是逐岗 detail（hotjob state=1017 / wt req_state=9501），这正是 daily liveness sweep（`enrich_backlog.py --sweep` + `enrich.py`，**已验证工作正常、勿动**）在做的；且它优先复检 `enrich_checked_at=NULL` 的新岗，「假 active」窗口已很小。**所以保持 sweep、不要去做 list 端过滤（技术上做不到）**；减少 churn 只能靠 detail 探活，成本=sweep 本身。

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
   - **⚠️ 修正 §3 旧表述**「daily liveness sweep 已验证工作正常、假 active 窗口已很小」：实测它曾因上面的超时长期**没真正跑成**，别再假设它自动有效——以 db-report 数据为准。
   - **🚫「列表里没有」≠「已撤岗」——除非先证明该列表是全集（2026-07-29 立碑，差点误删 460 个在招岗）**：
     list-absence 撤岗（`supports_absence_liveness` + `jobs_db.sweep_absent_jobs`）的前提是**该源的列表接口返回岗位全集**（feishu/beisen/bytedance 是验证过确实返全量才开的）。
     ⚠️ **绝不能从「列表条数 ≪ 库里 active 条数」反推「差额都是死岗」**——这个差额有两种成因、处置**完全相反**：① 死岗堆积（该清）；② 列表接口本身只返子集（一清就是删在招岗）。
     踩坑实录：见华为列表接口只返 13 条而库里 460 个 active，就推断其余是死岗并开了 absence（commit 675e459）→ 逐个核验后**460 个全部在招、0 个撤岗**（`getJob/newHr` 返的是筛选过的子集；例 jobId=30153 列表查不到但详情接口返完整岗位名+正文）。已在 `c9a7e73` 撤回并加断言测试钉死。当时唯一挡住的是 97% 缺席越过 `max_expire_fraction=0.5` 安全闸 → sweep 主动跳过，未实际删数据；**但那道闸是兜底不是设计，别指望它**（存量降到列表规模 2 倍以内它就不拦了，而 expired 当天会被 purge 永久删除）。
     ✅ 正确姿势：拿不准列表是否全集，就走**逐岗** detail 判死（`ENRICH_REGISTRY` + liveness-sweep）。华为即用此法：`…/portalpub/getJobDetail/newHr?jobId={id}&dataSource={ds}`（httpx 零鉴权，既判死又补 `mainBusiness` 正文）；判死要求「jobname 空」**且**「有值字段数 ≤8」双条件（在招 ~32 个字段有值，不存在的 id 返 200+109 字段骨架但只 5 个有值），半截数据一律不判死——**宁可漏判不可错杀**。
     📌 通用规矩：**不可逆操作（标 expired / 删行）前，核验样本量必须匹配影响面**——要清 447 行就得核验 447 行，抽查 2 个不算数。
   - **expired 死岗 = 永久删除回收空间（2026-06-18 定方针）**：expired 是 sweep/dead-link-audit 逐岗探活**确认撤岗**，不保留 → `purge-expired.yml`（每日 UTC 02:30）`DELETE … WHERE status='expired'` + 普通 VACUUM 持续清。`removed`（抓取漏看可复活）不动。db_size 真正缩小（还盘）由 `maintenance-vacuum -f full=true` 删大批后手动跑。**库再逼近 500MB 上限 → 走 `docs/superpowers/plans/2026-06-14-jobs-database-refactor.md` 的 Phase 1：jobs 热表迁到自建 PostgreSQL（jobs-store 边界），Supabase 只留 Auth/sources/crawl_runs/用户小表。**
     - **⚠️ Phase 1 已切（2026-06-19）：`jobs` 热表现在在自建香港 Postgres 17 上，不在 Supabase。** 腾讯云轻量 2C2G/40GB，免备案。连接串（含公网 IP / 账号 / 密码）只存 **`JOBS_DATABASE_URL` secret**（GitHub Actions + Vercel）+ 本地 `.env.local`；**仓库公开，host/IP/账号/密码一律不入库、不提交、不写进文档**。Supabase 现只管 Auth / `sources` / `crawl_runs` / `discovery_runs` / 用户小表 / 洞察表。
       - **边界层**：app 读+写都走 `lib/jobs-store/`（`client.ts` pg 连接池 / `search.ts` 复刻 FTS / `read.ts` 读：list/count/companies/byIds/byUrls/byCompanies/recallByPrefs / `write.ts` 写：canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db），爬虫写走 `crawler/jobs_db.py`（psycopg2）。两端都 **gated**：配了 `JOBS_DATABASE_URL` 用香港库，否则回退 Supabase（本地无 env / 回滚安全）；**写入端 HK 报错不回退 Supabase**（避免写空库孤儿数据）。**sources/crawl_runs 永远走 Supabase**（jobs_db 只管 jobs）。
       - **schema 在 `jobs-db/schema.sql`**（从生产 `pg_dump` 忠实重建：表 + canonical 触发器 + bigram FTS(search_doc/search_tokens/GIN) + count_valid_active_jobs/active_companies/active_job_counts_by_company + 全索引 + pg_trgm）。2026-07-02 海外扩展新增 `jobs.country_code`、`jobs.job_scope`（默认 `domestic`）与 `jobs.sponsorship_signal`；`job_scope=domestic` 只覆盖大陆+香港+澳门，`overseas` 覆盖本期放开的 US/SG/Remote，台湾维持不抓、不归入任一范围。改 schema → `gh workflow run jobs-db-migrate`（幂等 apply 到 `JOBS_DATABASE_URL`）。
       - **沙箱直连香港库验证**：见 [[job-radar-live-db-access-from-sandbox]]（dangerouslyDisableSandbox + source .env.local + 用户 Homebrew psql）。
       - **改 jobs 列/索引/canonical**：三处仍要同步（lib/canonical-url.js / crawler/normalizer.py / **jobs-db/schema.sql 的 SQL 函数**，不再是 supabase migration 144）。
       - **app 端 jobs 读+写已全部落香港库（2026-06-19，commit b742ee6/28ddddb）**：原「discovery/enrich 读仍在 Supabase」遗留已清。新增 app 写层 `lib/jobs-store/write.ts`（canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db）；discovery/search 的 upsert、enrich 写回、refresh 选区、insights Tier1 派生全 gated 走香港库（11 个 `.from("jobs")` 文件全 gated，写入端失败不回退 Supabase 避免孤儿数据）。Supabase `jobs` 已是空表（TRUNCATE 过，~17MB）；gated 兜底仅在未配 `JOBS_DATABASE_URL`（本地/回滚）时回退它。**移除 gated 兜底前仍请线上确认稳定**（见 docs runbook）。详见记忆 [[job-radar-phase1-ci-jobs-db-wiring]]。
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
| 缓存 | 跨实例用 `unstable_cache` / CDN；进程内缓存只当同实例并发去重 | 进程内 Map 当缓存用，serverless 多实例命中率≈0 |
| 队列与调度 | 重活进 GitHub Actions + `ops_runs` 台账，cron 错峰、分片、限并发护连接 | 长任务塞进请求路径（点击探活 5-8s 已废弃） |
| 会话鉴权 | 本地 JWT 验签 + 模块级 JWKS 缓存，中间件注入用户头 | 每请求跨洋 `getUser()`（566ms→0.7ms） |
| 安全 | 密钥只进 Secrets/env；公开仓 pre-commit 门禁扫敏感信息 | 绝对路径/IP/真名进公开仓（不可撤回） |
| 可观测 | 每条链写 `ops_runs`（含零产出指标）+ ops-watchdog 规则 A~F | 「绿灯零产出」连续 7 天无人知 |

**每次交付前自查（缺一条就别说做完了）**：
① 先量后改，有改前改后真实数字；② 新数据先想「怎么建模成可索引可筛选的字段」，再想怎么展示；
③ 边界/错误/并发/幂等/重跑都想过；④ 后台链路有台账和告警口径；⑤ 四件套 + lint 全绿并**真的跑了**。

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

## 常用命令

```bash
# 前端
npm install
npm run dev        # localhost:3000
npm run build
npm run lint

# 测试
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"

# crawler 单源（需先有 .env.local）
cd crawler
set -a; source ../.env.local; set +a
python3 run.py --source apple   # 或 siemens / baidu / jd

# 提交前回归四件套
node --test tests/*.test.js && \
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
  npm run build && git diff --check
```

⚠️ **`npm run build` 本地绿 ≠ Vercel 能部署**：本地 `next build` 会跳过 lint（输出里没有
「Linting and checking validity of types」这一步），**Vercel 的 build 会跑 lint，且 Next 的
若干规则是 Error 级会直接让部署失败**（2026-07-27 实锤：`lib/admin-health.ts` 里一个变量叫
`module` 命中 `@next/next/no-assign-module-variable`，从 6d5010f 起连续 7 次部署失败，
本地全程绿）。**改了 `app/` `lib/` `components/` 下的 TS/TSX 就必须另跑 `npm run lint`。**
⚠️ 在 `.claude/worktrees/*` 里跑 `next lint` 会因为「主仓 + worktree 两份 .eslintrc.json /
package-lock.json」报 plugin 冲突直接退出 1 —— 这是环境问题不是代码问题；此时改用
`npx next lint --dir lib --dir app --dir components`（在能跑通的目录下），或 push 后立刻查
Vercel 部署状态兜底（`gh api repos/<owner>/<repo>/deployments` + `/statuses`）。

## 目录结构

```
app/                     # Next.js App Router 页面
  page.tsx / today-client.tsx     # Today 今日看板
  jobs/                  # Jobs 岗位库（jobs-client.tsx）
  path/                  # 职业路径（模块 ③，path-client.tsx）
  preferences/ saved/ applied/    # 偏好 / 收藏 / 已投递
  sources/               # Sources 源管理（仅管理员）：列表 + 「添加源」表单（SourceManager）
  admin/insights/        # 洞察管理页（仅管理员）：列/增/改/下架洞察 + 处理申诉（InsightsAdminClient）
  admin/health/          # 运营数据看板（仅管理员）：北极星「必投清单健康覆盖」+ 今日健康 + 各模块每日战报 + 岗位库体检 + 用户业务（去黑话 + 数据准确）
  login/ auth/callback/  # 登录与 OAuth 回调
  api/search|discovery|resume|preferences/route.ts   # 岗位层后端入口 + 简历/偏好写入
  api/sources/route.ts   # admin 加招聘源（service-role 写 sources，绕 RLS 无 INSERT 策略）
  api/insights/route.ts + insights/dispute/route.ts   # 模块 B 职业洞察读/录入/申诉
  api/insights/admin/route.ts          # admin 洞察后台：GET 列全部 / POST 增改(过校验门) / PATCH 上下架
  api/insights/dispute/resolve/route.ts # admin 处理申诉：upheld(下架对应 item) / rejected
  api/career-path/route.ts   # 模块 ③ 个性化职业路径（确定性引擎，无 LLM）
  api/campus-zone/jobs/route.ts  # 校招专区展开某家公司时按需取完整岗位行（按 公司+模式，非按 id，见下「校招专区首屏」）
components/              # JobCard / JobFilters / PreferenceForm / Navbar / ResumeProfilePanel
                         # SourceTable（presentational，含 reloadSignal）/ SourceManager / AddSourceForm（A1）
                         # InsightsAdminClient（洞察管理页客户端，A2）
                         # CompanyInsightDrawer（公司洞察抽屉，从 JobCard 打开；portal 到 body 防闪烁）
                         # SavedCompare（值得投页对比决策桌：勾选2~4岗并排比匹配/要求/新鲜度/洞察芯片；portal 同上）
lib/                     # 工具层：supabaseClient、auth、scoring、types、utils
                         # supabaseService（service-role 客户端工厂，admin 写库共用）
                         # apiAuth（requireUser/requireAdmin/assertOwnership 统一鉴权，service-role 路由共用）
                         # track（自有埋点：简历解析质量等去标识 diagnostics 白名单写 events）、admin-health（运营看板聚合纯函数 + 术语→人话映射）
                         # must-apply-list（北极星指标口径：必投清单已多行业化——11 行业 × 各 30 家，2026-07-14。
                         #   数据本体在 lib/must-apply-list.json（行业键与 lib/company-industry.js 的 INDUSTRY_CATEGORIES 同名同序），
                         #   TS 与 crawler/must_apply.py 共读同一份，杜绝两端漂移；改清单=改口径。
                         #   用户行业（user_preferences.target_industries 经 canonicalizeUserIndustry 归一）决定看哪份清单：
                         #   resolveMustApplyIndustries 空/归一不出 → 兜底「互联网/科技」。看板北极星只按「活跃行业」
                         #   （有≥1 注册用户的行业 ∪ 互联网/科技）判健康、取最差行业 band；无用户行业 = 储备清单，
                         #   只展示不拖红。爬虫探活倾斜吃全行业并集（must_apply.patterns()）；清单里库内没有的公司由
                         #   crawler/targets_must_apply.json 喂给每日自动扩源（plan_targets 梯队：用户点名 > 必投缺口 > 科技/消费 > 其余））
                         # job-fields（经验/学历/截止 正则兜底纯函数，JobCard 与 SavedCompare 共用）
                         # campus-facets（校招专区聚合分面：构建 + 匹配同文件，防两端下标口径漂移）
                         # campus-user-industries（用户行业→必投公司解析，/campus 页与展开接口共用同一份范围）
                         # source-adapters（adapter/抓取方式白名单 + validateSourceInput 纯函数）
                         # live-search（已知源刷新格式化/校验）、official-discovery、
                         # baidu-qianfan-search、china-keyword-expansion、china-official-sources、client-job-mapping
                         # geo / job-scope / role-lexicon-en = 海外地理归属、求职范围过滤、中英岗位词典
                         # insight-verification（分级/时效/去标识/归因 纯函数）、insight-match（公司归一匹配）、insight-client（浏览器去重缓存）
                         # insight-bundle（洞察展示门复用）、insight-chip-format（抽屉 hiring/financials 芯片格式）、insight-enrich-now（现查快车道节流/台账纯函数）、career-path（确定性职业路径引擎，无 LLM，模块 ③）
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
supabase/migrations/     # 001_init → 002_rls → … → 007_candidate_profile_summaries
                         # → 008_discovery_run_diagnostics → 009_discovery_async_runs → 010_seed_spa_sources
                         # → 011_seed_foreign_ats_sources → 012_seed_apple_china_source
                         # → 013_career_insights（模块 B 5 表 + RLS）→ 014_seed_career_insights（四维种子草稿）
                         # → 015_verify_experience_sources（experience 真实来源核验）
                         # → 016_rewrite_culture_and_experience_copy（去「避坑」+ 9 条 experience 正文改通俗）
                         # → …（前缀递增，详见目录）→ 158_admin_health_snapshot → 159_admin_ops_dashboard（ops_runs 台账表 + 运营看板聚合函数）→ 165_insight_enrich_now_and_hiring_monthly
                         # → 184_company_logos → 185_must_apply_gap_attempts（必投缺口漏斗台账）
                         # → 166_insight_submissions → 167_overseas_prefs → 168_sources_regions → 169_seed_overseas_regions → 172_user_pref_experience_stage（求职阶段字段）
.github/workflows/daily-crawl.yml   # 每日 + 手动抓取
.github/workflows/gap-funnel.yml    # 必投缺口漏斗（每日 UTC 22:40；默认 dry-run，apply=true 才写库）
tests/                   # node --test 单测
```

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

### 模块 B 职业洞察层（migration 013/014，与岗位层严格分离）

| 表 | 用途 | 权限 |
|---|---|---|
| company_profiles | 公司画像（company 唯一 + aliases 对齐 jobs.company） | 所有人读，admin/service 写 |
| insight_items | 洞察条目（dimension/grade/content/时效/payload） | 读仅 `active+deidentified`，admin/service 写 |
| insight_sources | 溯源（链接 + 短摘要，禁整段原文） | 读仅 `deidentified`，admin/service 写 |
| insight_item_sources | 条目↔来源 多对多 | 所有人读，admin/service 写 |
| insight_disputes | 通知-删除申诉（§7.3） | 用户可插/读自己，admin 读全部+改状态 |
| company_hiring_monthly | 月度招聘量聚合结构（年度大小年历史底座；数据不足一年时不得用于 YoY 结论） | service_role 写，admin 读 |

五维 `dimension`：`timing`(事实为主) / `listing`(上市/股票，事实，migration 023/024，易变行情不落库数字只存 payload.quote_url 链接) / `compensation_intensity` / `path` / `culture`(做浅重免责)。
AI 辅助录入：`/api/insights/admin/ai-draft`（仅 admin、单次 LLM 调用、复用 lib/llm，产出仅草稿强制 status=retired，必人工核对+补真实来源过门后才展示；不进 cron、不按用户触发，控账单）。
三级 `grade`：`fact`(须带来源) / `experience`(须 sample_size≥5 且多源) / `rumor`(默认拦截)。
展示前必过 `lib/insight-verification.ts` 的分级/时效/去标识/归因门；无可信结果返回 `insight_unverified` / `insight_outdated`。
**数据来源（v2.0 三层供给）= T1 派生（自有岗位库现算 timing/hiring/salary，读时零成本）+ T2 官方事实（Wikidata + SEC EDGAR 上市，cron）+ T3 经验（多源搜索 `search_router`→判官核验，cron）+ 人工策展 seed/admin 录入。合规线不变：官方源=fact、搜索源=去标识聚合+判官+≥2源，不直接爬社区；admin AI 辅助草稿仍须人工核对过门才展示。** **供给自动化（2026-06-20 升级，2026-07-02 补现查快车道）**：T3 检索多源化（`search_router`，见「百度千帆额度」段）；T2 加 SEC EDGAR 官方上市源；**现查触发**（`/api/insights` GET 对有在招岗位但无新鲜存储型洞察的公司，先幂等 upsert 画像，再按 `INSIGHT_ENRICH_COOLDOWN_HOURS` / `INSIGHT_ENRICH_HOURLY_CAP` 通过 `discovery_runs(mode='insight_enrich')` 节流台账触发 `insight-enrich.yml` 单公司 `workflow_dispatch`；workflow 跑 `insight_backlog.py --company` 的 T2 + T3，缺 service role/GitHub dispatch 配置时只返回 `enrich_now.skipped`，不影响抽屉展示）；**过期下架**（`insight-staleness-sweep.yml` 每日把 `valid_until` 过期的 active → retired，治「又旧」）；**即时性窗**（搜索四源统一限**近 3 年**：Tavily `start_date`/Serper `tbs` 加时间窗，千帆/博查本就 ≤1 年；T3 经验洞察写入带 `valid_until`=+1 年 → 过期巡检自动退役、180 天复核续期；重富化先退役旧代 public_web culture，不堆积老聚合）。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。 014 种子为待人工核实草稿；015 已用真实公开链接核验 experience 来源；016 把 culture 的「（避坑提示）」改「温馨提示」、9 条 experience 正文改通俗（去掉逐条媒体罗列，正文只留一句轻量归因「据公开讨论/据公开报道」以过 `passesAssertionLint`，统一「来源聚合·去标识」声明只在抽屉顶部 banner 出现一次）。抽屉会把 `payload.hiring_signal` 渲染为招聘动态芯片，把 listing `payload.financials` 渲染为业绩芯片。
**日常维护全程网页、零 SQL**：admin 在 `/admin/insights` 增/改/下架洞察、贴来源、处理申诉（走 `/api/insights/admin` + `/api/insights/dispute/resolve`，service-role 写、必过校验门）；在 `/sources` 用「添加源」表单加招聘源（走 `/api/sources`）。`adapter_name` 取值见 `lib/source-adapters.ts`（须与 `crawler/run.py` 的 ADAPTERS 对齐；greenhouse/lever 是通用 ATS，填公司名+ATS 地址即可）。

## 四层「搜索/刷新」必须区分（高频踩坑点）

不可混为一谈，更不可把有限候选源池叫「实时网搜」：

1. **本地 jobs 搜索** — 只查 `jobs` 表，无外部请求。
2. **「刷新公司库」`/api/refresh`**（前端 Jobs 页「刷新公司库新岗位」按钮，全异步·流式）— 解析用户 scope（当前筛选 + 偏好兜底，按相关性 + 每平台多样性 cap 前 N=25 家）→ 节流/幂等 → 插 `discovery_runs(mode='company_refresh', diagnostics={source_ids,filters,click_time})` → workflow_dispatch GitHub Actions → CI 跑 `crawler/discovery.py CompanyRefreshRecipe`（httpx 源先、浏览器源后，逐源增量回写产出+进度）→ 前端复用 discovery 轮询(`/api/discovery/status`)流式并入。**覆盖用户全部公司源（含飞书/北森/Moka 浏览器源），取代旧 `/api/search` 的窄同步刷新**。设计/硬化见 `docs/superpowers/specs/2026-06-11-refresh-company-library-design.md`。
3. **已知源刷新** `/api/search`（旧同步路径，前端已不主用）— 只内联抓百度/京东/Apple + ≤8 greenhouse/lever，serverless 秒回。仍保留作 API；**已处理 exclude_keywords**（从用户偏好读取，每个源 upsert 前用 `excludeJobs` 剔除命中岗位，与 crawler 同口径）。
4. **官方源发现** `/api/discovery` — 百度千帆为主 provider，**低频、串行、可缓存**（相同 user/query/city/job_type 45 分钟复用缓存）；默认只调 1 个 generated query，「继续发现更多」才调第 2 个。

> 三/四层都靠 GitHub Actions workflow_dispatch（需 Vercel 配 `GITHUB_DISPATCH_TOKEN`+`GITHUB_DISPATCH_REPO`）；`/api/refresh` 与 `/api/discovery/dispatch` 共用这套异步轨道 + `discovery_runs` 表，零新表。

## 数据质量优先级（最高）

`jd_url` 准确性高于一切。**禁止写入 active jobs**：招聘首页 / 搜索页 / 导航页 / 帮助页·FAQ / 登录页 / 语言切换页 / 专题入口页 / 空链接或猜测链接。拿不到稳定岗位详情链接的 source 只能记 `partial_success`，不得标记完整成功。质量门：`company/title/jd_url` 非空 + HTTP 200 + 页面含标题或核心片段。

**唯一性下沉到 DB（migration 144）**：`jobs.canonical_jd_url`（归一 tracking 参数 + 尾斜杠；`#` SPA hash 路由原样不碰）+ active partial unique index 保证「同一岗位链接在 active 里唯一」。
- ⚠️ **`canonicalize_jd_url` 归一逻辑活在三处，改一处必须三处同改、字节级一致**：`lib/canonical-url.js`（前端/JS 写入端）、`crawler/normalizer.py`（爬虫端）、`supabase/migrations/144_jobs_canonical_jd_url.sql` 的 SQL 函数（回填/触发器/审计）。任一处 drift 会导致同岗算出不同 canonical → 去重失效或误并。
- 改规则后必须同步两套纯函数测试：`tests/canonical-url.test.js` + `crawler/test_canonical.py`。
- 加唯一约束类迁移：上约束**前**必须先 dedup 存量重复（降级而非删除，保 `job_actions` 外键），否则 `CREATE UNIQUE INDEX` 在生产有重复时会失败并永久阻塞后续迁移；push 前先跑 `node scripts/audit-job-duplicates.js` 看影响面。
- ⚠️ **大表（jobs 10 万级）全表回填/建索引迁移必须抬超时**：在迁移事务内加 `set local statement_timeout = '1800s';`。Supabase 默认 statement_timeout ≈ 2min，全表 `update … set x = f(col)` 会被强杀致整个迁移回滚（migration 144 踩过这个坑）。

## 当前 source 状态

2026-07-02 海外扩展：`sources.regions` 默认 `{CN}`，迁移 `169_seed_overseas_regions.sql` 仅把已验证且 enabled 的 http 外企 ATS 源保守放开到 `{CN,US,SG,Remote}`；浏览器/Playwright 源暂不一次性放开，需单独评估容量。台湾不在 seed 范围内，normalizer 继续拒收台湾地点。

| Source | 状态 | 详情链接格式 |
|---|---|---|
| Apple | 可用（crawler + 已知源刷新） | `jobs.apple.com/en-us/details/...` |
| Siemens | 可用（crawler） | `jobs.siemens.com/en_US/externaljobs/JobDetail/...` |
| 百度 | 可用 | `talent.baidu.com/jobs/detail/{recruitType}/{postId}` |
| 京东 | 可用 | `zhaopin.jd.com/web/job-info-detail?requementId=...` |
| 美团 | 可用（httpx） | `zhaopin.meituan.com/web/position/detail?jobUnionId=...` |
| 快手 | 可用（Playwright 签名拦截 + 全分页） | `zhaopin.kuaishou.cn/#/official/social/job-info/{id}` |
| 哔哩哔哩 | 可用（匿名 CSRF + httpx） | `jobs.bilibili.com/social/positions/{id}` |
| 拼多多 | 可用（httpx，校招） | `careers.pddglobalhr.com/campus/grad/detail?positionId=...` |
| vivo | 可用（httpx） | `hr.vivo.com/job-detail?_irjc=...&_irjid=...` |
| 比亚迪 | 可用（公开全列表 + Playwright 批量加密 URL） | `job.byd.com/portal/pc/#/social/socialPositionDetails?...` |
| 顺丰 | 可用（httpx，最近 50 页诚实 cap） | `hr.sf-express.com/JobSearchById/{id},{positionType}` |
| 海尔 | **暂不可用** | 只解析到入口页，保持 `partial_success` |

## 🚫「接口返 0 / 403」不能证明「对方没开」（2026-09-04 立，一晚栽三次）

判一家公司有没有开校招，**唯一可信的依据是对方页面自己怎么说**（招聘公告、网申起止日期），
不是我们某个接口的返回值。已经栽了五次，全是同一个错：

| 公司 | 当时的「证据」 | 真相 |
|---|---|---|
| 哔哩哔哩 | 社招接口传 `recruitType=1/2` 返 `total=0` | 校招在**另一条 API**（`/api/campus/position/positionList`），372 岗；首页当天就挂着「2027届秋季校园招聘正式启动」 |
| 阿里巴巴 | `campus-talent.alibaba.com` 匿名 POST 返 403，判「login_wall」 | 不是登录，是 **CSRF**：GET 页面拿 `XSRF-TOKEN` cookie → POST 带 `?_csrf=`，1,075 岗 |
| 小米 | 飞书两个 `storefront_id` 返回**完全相同**的 1887 条，判「私有部署没有校招板块」 | 试错了维度，真正的开关是**请求头 `website-path`**，campus 764 / internship 554 / newretailing 121 |
| 百度 | 列表接口传 `recruitType=CAMPUS` 返 0 | 校招那一档百度自己叫 **GRADUATE**；传 CAMPUS 接口回 `Illegal argument : recruitType`，adapter 只看到 0 条就跳过。改对之后 157 个校招岗 |
| 华为 | 老门户 `reccampportal` 传 `jobType=2` 返 `totalRows=0`，判「对方没开」 | 校招 2026 年搬到新站 `career.huawei.com/cn/campus-recruitment` + 另一个网关；官网 2026-08-15 就挂着「2027届应届生招聘启动」。应届 69 + 实习 31 |

✅ 正确姿势：① 先渲染对方的校招页，看它自己写没写「XX 届校园招聘启动」+ 网申日期；
② 再从**页面自己发的请求**里找入口（拦 XHR / 读它的 JS 路由表），不要拿社招接口试参数；
③ 参数值也要从它的代码里读，别猜——**猜参数最容易骗自己**：曾以为「华为校招是 `jobType=0`，
   我们只试过 1/2/3」，2026-09-04 实测 `jobType=0` 同样返 `totalRows=0`；老门户压根没有校招，
   在那上面继续试参数是死路。校招在**另一个站另一个网关**上。
④ **「HTTP 200 + 空 data」同样是假阴性**：华为新网关少带任意一个 `x-*` 头
   （x-hw-id / x-jalor-tenantalias / x-language / x-alb-gray / x-referer）就返 200 但 data 为空。
   adapter 遇到这种情况必须**抛错记 failed**，不许安静返 0 条——安静返 0 正是错误结论的来源。
⑤ **确实抓不了的要说清是哪一种**：快手校招 `campus.kuaishou.cn/robots.txt` = `Disallow: /`，
   这是合规红线不是技术问题，不要再去试；但同官网的**日常实习**在 `zhaopin.kuaishou.cn`
   （无 robots 限制、同接口同签名，只差 `positionNatureCode=C002`），1,046 个岗是能抓的。

## ⚠️ 飞书招聘的校招岗藏在 `website-path` 请求头后面（2026-09-04 立）

同一个飞书租户可挂多个门户，**用哪个门户由请求头 `website-path` 决定**（与 URL 路径同名）：
不带该头 = 社招全集；`campus` / `internship` / `newretailing` = 各自独立的池子。纯 httpx 可达，
**不需要浏览器、不需要 `_signature`**（曾以为要签名，是因为重放时把这个头丢了）。

- **加一个租户的校招源零代码**：插一行 `source_url = https://{host}/campus/position` 即可，
  `FeishuRecruitAdapter` 按路径自动切门户与详情模板（`lib/source-adapters.ts` 不用动）。
- ⚠️ **`website-path: index` 不是「主门户」，是更小的子集**：蔚来不带头 2055 岗、带 index 只有
  1801 岗（少 254 个）。库里存量飞书源全是 `/index/position`，派生 index 就是全体缩水——
  `_bind_website_path` 因此把 index 当「无子门户」，钉在 `tests` 里别改。
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

## 百度千帆额度

免费「百度搜索」每日 50 次。控制台 0/50 或未付费时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，`/api/discovery` 直接返回 `provider_rate_limited` / `rate_limited=true`，前端稳定展示不崩。额度耗尽时不要反复点「发现」或跑 5-query live 验证。

**职业洞察 T3 检索已扩为多源路由**（`crawler/search_router.py`：博查/Tavily/Serper/千帆，配哪个 key 用哪个、未配自动跳过、各源 `*_DAILY_CAP` 日顶走 `search_usage` 表 + 迁移 156；**免费额度保守日顶**=代码默认 tavily 30 / serper 20 / bocha 50、千帆 40，**绝不一次性用完**［Serper 2500 为一次性总额、Tavily 1000/月、千帆 50/天每日重置=常驻主力］，可在 repo Variables 上调）。千帆仍受上面 50/天全局额度（`qianfan_usage`），但**不再是唯一检索源** → T3 富化吞吐不再被它单独卡死。新增 env（GitHub Secrets + 本地 `.env.local`）：`BOCHA_API_KEY` / `TAVILY_API_KEY` / `SERPER_API_KEY`（+ 可选 `*_DAILY_CAP`）。合规不变：仍只走搜索 API 取去标识聚合 + 判官核验 + ≥2 源，不直接爬社区。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。

## ⚠️ 校招专区首屏：只下发聚合分面，绝不逐条下发岗位（2026-09-02 立）

`/campus` 首屏曾 **responseEnd 10.1s / 单页 2.09 MB HTML**，而 TTFB 只有 189ms ——
**慢的不是取数排队，是 SSR 那一段本身**：把 30 家必投公司的 16,494 个校招岗逐条序列化进 props。
判读法记住：`TTFB 快 + responseEnd 慢` = 生成/传输页面本身的问题，别去查连接池和数据库排队。

现行形态（改动前务必读懂，别改回去）：
1. **页面一条岗位记录都不下发**，只下发 `lib/campus-facets.ts` 的聚合分面
   `[城市下标, 学历下标, 职能下标, 届别, 计数]`。依据：客户端拿逐条记录只做两件事——填筛选下拉、
   算「当前筛选下有几个岗」，**两件事都只依赖这四个维度**，与具体是哪个岗无关。
   live 实测 16,494 条压成 1,917 个四元组，props 2,086 KB → 52.6 KB。
   ⚠️ **构建（buildCampusFacets）与匹配（countMatchingFacets）刻意放同一文件**：下标口径两端一漂，
   卡面就安静地报错数字——不报错、不崩，只骗用户。等价性由 `tests/campus-facets.test.js`
   穷举全部筛选组合钉死，改分面必须让它继续绿。
2. **重活按行业清单缓存**（`unstable_cache`，10 分钟）。它只依赖必投清单、不含用户私有数据，所以能跨请求共享。
   ⚠️ `windowStatus` 与排序**刻意留在缓存外每请求现算**——它们依赖「此刻」（72h 新鲜度阈值），
   一起缓存会把徽章冻住。缓存里只放 `lastSeenAtMs` 这类原始输入。
   ⚠️ 缓存函数体内不得读 `cookies()`/`headers()`（unstable_cache 限制）。
3. **聚合 SQL 不用 `company ilike any()`**：带前导 % 用不了任何索引 → 39 万 active 行并行全表扫
   （live EXPLAIN 2567ms / 127,726 buffers）。改成先用 `jobs_active_company_idx` 取全部 active
   公司名（`allActiveCompanyNames`，5 分钟进程内缓存），JS 按同样的「不区分大小写子串」语义解析出
   确切名字，再 `company = any()` 走 Bitmap Index Scan（957ms / 46,413 buffers，结果集逐行相同）。
4. **展开某家公司走 `/api/campus-zone/jobs`（按 公司+模式），不按 id**：按 id 取就得先把 16,494 个
   uuid 下发到浏览器，光 uuid 就 0.59 MB，白白抵消收益。
   ⚠️ 旧的 by-ids 调法有个真 bug：把 campus 与 intern 的 id 拼一起再截前 200 →
   **大厂的实习桶被校招桶挤没，实习模式展开必然空白**。按模式取从根上没有这个问题。
   ⚠️ 取数分两段：准入门 `campusAdmission` 要看 JD 正文，但**排序键 deadline/first_seen_at 与
   归属键 company 都是轻字段** → 先只取轻字段排好序，再顺着顺序分批（500）取完整行跑准入门，
   收满 200 就停。一次性拉完整行 live 实测字节 5.8s，分段后 0.5~0.9s，语义完全一致。
5. **归属规则三处必须一致**（getCampusZone / getCampusCompanyJobs / 分面计数）：
   list 里第一个 pattern 命中者得（`腾讯音乐 TME` 归 `%腾讯音乐%` 不归 `%腾讯%`）。
   任一处漂移 → 卡面计数与展开列表对不上。live 交叉验证法：卡面计数（来自分面）与
   `/api/campus-zone/jobs` 返回条数（独立重算）在未截断的公司上必须逐个相等。

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
