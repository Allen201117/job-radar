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

## 数据库迁移（已自动化，勿再手动跑 Supabase）

迁移**不需要再手动进 Supabase SQL Editor 跑**。机制：push 到 `main` 且改动 `supabase/migrations/**` 时，
`.github/workflows/migrate.yml` 自动用 `scripts/db-migrate.sh` 把未应用的迁移 apply 到生产库（`schema_migrations` 表记录版本，前缀 ≤ BASELINE 仅登记不重跑）。
- **一次性设置**：GitHub repo → Settings → Secrets → Actions 加 `SUPABASE_DB_URL`（Supabase → Settings → Database → 直连串，端口 5432，含密码）。配一次，此后零手动 SQL。
- 新迁移文件继续放 `supabase/migrations/`，前缀按序递增（如 `023_xxx.sql`），push 即自动应用。
- 加新迁移后若 BASELINE 已过期，更新 `scripts/db-migrate.sh` 的 `BASELINE`。
- **命名规约**：seed 类迁移（纯 `insert` sources 数据）文件名必须带 `_seed_` 标识；新前缀必须先 `ls supabase/migrations` 确认未被占用。前缀「纯数字 + 无新增重复」由 `scripts/check-migrations.sh` 在 CI apply 前硬校验（历史重复前缀已在脚本 GRANDFATHERED 白名单豁免，勿改名已应用文件）。

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

`components/JobFilters.tsx` 是「顶部吸顶 filter bar + 全部筛选抽屉 + 已选 chip 行」形态。
竞品调研（BOSS/拉勾/猎聘/智联/51job/LinkedIn/Indeed/Wellfound 8 家）结论：8/8 都用吸顶
filter bar，而「维度放不下」的业界标准解法**不是折叠手风琴，是把溢出维度收进「全部筛选」
弹层**。所以：**不要再往筛选器里加 `<details>` / 手风琴 / 「更多筛选」折叠**，加维度就往
抽屉里放。契约测试 `tests/ux-hardening-contract.test.js` 守着这条。
- 岗位职能的可选值域**唯一来源**是 `lib/china-keyword-expansion.js` 导出的
  `JOB_FUNCTION_BUCKETS`，UI 从它渲染。加职能桶只改那一处，别在 UI 里留第二份硬编码，
  否则用户会筛到永远不可能命中的「幽灵条件」。
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
