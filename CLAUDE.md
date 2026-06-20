# 求职雷达 / Job Radar — 项目级 Claude Code 指南

> 本文件指导 Claude Code 在本仓库工作。规则优先级：当前明确指令 > 本文件 > 全局 `~/.claude/CLAUDE.md` > 默认行为。

## 项目概览

- 项目名称：求职雷达 / Job Radar Private Beta v0.1
- 项目类型：3–5 人内测版「公开企业官网岗位雷达看板」Web 应用
- 主要技术栈：Next.js 14 App Router + React 18 + TypeScript + Tailwind；Supabase（Auth / Postgres / RLS）；Python crawler（httpx + selectolax）；GitHub Actions 定时抓取
- 包管理器：npm（前端）/ pip（crawler，见 `crawler/requirements.txt`）
- 运行环境：Node.js 18+，Python 3.11+
- 部署：前端 Vercel，crawler GitHub Actions

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

3. **MVP 阶段：精准 / 可靠 / 稳定 > 规模（2026-06-15 定调，覆盖并取代旧「持续大规模扩源」方向）**
   **不再以「源数量」为指标，停止大规模铺量扩源。** ⚠️ 旧「866 源里仅 ~327 在产出、539 个（62%）0 产出」已过时——2026-06-19 db-report 实测源池已健康：**~835 enabled、~98% 在产出，仅 ~15 个 0 产出**（且多为目标相关但当前无开岗的科技/半导体/智能车公司，监控即可；当天已 disable 14 个明确低相关的传统制造/医药/重工/校招结束死源）。产出仍偏向车厂/央企/制造 + 外企海外岗，与目标用户（科技/新经济/消费求职者）部分错配。MVP 阶段目标 = 让**少而精**的高质量源**稳定**产出**目标用户真正要的**岗位；**扩大规模是后期的事，现在搞一堆低质量公司源没用、只拖累信噪比**。
   - **指标换成「目标相关的有效产出」**：不看有多少源，看多少源在稳定产出 *目标相关 + 带 jd_url + 有 JD 正文* 的高质量岗位。
   - **砍低质量**：0 产出 / adapter 已坏 / 与目标用户无关的源，优先 `disable`（保留行可回滚，别删），不留着拉低信噪比。
   - **保可靠稳定**：只留能过质量门、稳定逐岗 `jd_url`、且能被现有抓取链路**可持续抓到**的源——别加 daily 抓不过来的源（浏览器源串行单个 2–5min，daily CI 预算有限）。头部高价值源 daily 抓，长尾降频 / 按需（「更新关注公司」接长尾）。
   - **扩源后置且定向**：确需加源时只**定向补缺失的目标公司**（如比亚迪 / vivo / 顺丰 / 荣耀 / 货拉拉 / 微众 等科技消费大厂），必须 live 探活确认稳定产出真实岗位后才留（禁止猜 slug 入库）；不再随机铺量、不再把「新增 adapter」当最高优 backlog。
   - 「中国本土 > 外企」「私企500强 > 国企央企」的**相对偏好仍然成立**（用于排序与定向补源的取舍），但服从于上面的「精 > 量」总原则——**不是再去大规模铺本土源**。
   - **列表抓取夹带已关闭岗（2026-06-15 查实；结论：靠 sweep，list 端过滤做不到）**：wt / hotjob 的列表接口会返回**已关闭的岗**（wt 52% / hotjob 71% 抓进来即被 sweep 判死，2026 春招/暑期实习收尾期尤甚）。**已 live 验证 list 端没有可靠的「关闭」字段可过滤**：hotjob `canDelivery=false` 在「在招」岗上也为 false（华夏银行 live 岗 15/15 都是 false）→ 不可用；wt 列表里夹带的已关闭岗与在招岗**除身份字段（postId/postName/workPlace）外无任何区别**（endDate 仍是未来日期）。唯一可靠的关闭信号是逐岗 detail（hotjob state=1017 / wt req_state=9501），这正是 daily liveness sweep（`enrich_backlog.py --sweep` + `enrich.py`，**已验证工作正常、勿动**）在做的；且它优先复检 `enrich_checked_at=NULL` 的新岗，「假 active」窗口已很小。**所以保持 sweep、不要去做 list 端过滤（技术上做不到）**；减少 churn 只能靠 detail 探活，成本=sweep 本身。

4. **指标诚实，不拿低质量/失活岗滥竽充数（2026-06-16 定为方针，最高优先级）**
   首页「岗位库」计数必须用 `count_valid_active_jobs()`（= active + 有 JD 正文 ≥60 字，迁移 151），**禁止用裸 `count(status='active')`**——后者含 25% 薄卡（moka 2.6 万张几乎全无正文）+ 大量未探活的假 active，会把数字虚高到「十万多」。计数 = 真实可投的高质量岗，不是行数。
   - **失活治理靠探活、且必须确认真的在跑**：active 一度膨胀到 ~13 万 → enrich/sweep 取工作队列的 `status='active' ORDER BY …` 查询撞 service_role ~8s statement_timeout **静默失败**（db-report 实测 87% 岗 `enrich_checked_at=NULL` 从未探活、死岗下架不掉 = 恶性循环）。已加 source 前导部分索引（150 summary-drain / 151 liveness-sweep）让队列查询走索引脱离超时。`liveness-sweep.yml`（只探活不抓列表、不回潮假 active）+ `dead-link-audit.yml`（浏览器 SPA 源 beisen/moka/feishu）要定期真的跑，并以 `db-report.yml` 复核 `never_liveness_checked` 持续下降。
   - **⚠️ 修正 §3 旧表述**「daily liveness sweep 已验证工作正常、假 active 窗口已很小」：实测它曾因上面的超时长期**没真正跑成**，别再假设它自动有效——以 db-report 数据为准。
   - **expired 死岗 = 永久删除回收空间（2026-06-18 定方针）**：expired 是 sweep/dead-link-audit 逐岗探活**确认撤岗**，不保留 → `purge-expired.yml`（每日 UTC 02:30）`DELETE … WHERE status='expired'` + 普通 VACUUM 持续清。`removed`（抓取漏看可复活）不动。db_size 真正缩小（还盘）由 `maintenance-vacuum -f full=true` 删大批后手动跑。**库再逼近 500MB 上限 → 走 `docs/superpowers/plans/2026-06-14-jobs-database-refactor.md` 的 Phase 1：jobs 热表迁到自建 PostgreSQL（jobs-store 边界），Supabase 只留 Auth/sources/crawl_runs/用户小表。**
     - **⚠️ Phase 1 已切（2026-06-19）：`jobs` 热表现在在自建香港 Postgres 17 上，不在 Supabase。** 腾讯云轻量 2C2G/40GB（IP 43.128.30.163），免备案。连接串只存 **`JOBS_DATABASE_URL` secret**（GitHub Actions + Vercel）+ 本地 `.env.local`；**仓库公开，host/账号/密码一律不入库、不提交**。Supabase 现只管 Auth / `sources` / `crawl_runs` / `discovery_runs` / 用户小表 / 洞察表。
       - **边界层**：app 读+写都走 `lib/jobs-store/`（`client.ts` pg 连接池 / `search.ts` 复刻 FTS / `read.ts` 读：list/count/companies/byIds/byUrls/byCompanies/recallByPrefs / `write.ts` 写：canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db），爬虫写走 `crawler/jobs_db.py`（psycopg2）。两端都 **gated**：配了 `JOBS_DATABASE_URL` 用香港库，否则回退 Supabase（本地无 env / 回滚安全）；**写入端 HK 报错不回退 Supabase**（避免写空库孤儿数据）。**sources/crawl_runs 永远走 Supabase**（jobs_db 只管 jobs）。
       - **schema 在 `jobs-db/schema.sql`**（从生产 `pg_dump` 忠实重建：表 + canonical 触发器 + bigram FTS(search_doc/search_tokens/GIN) + count_valid_active_jobs/active_companies/active_job_counts_by_company + 全索引 + pg_trgm）。改 schema → `gh workflow run jobs-db-migrate`（幂等 apply 到 `JOBS_DATABASE_URL`）。
       - **沙箱直连香港库验证**：见 [[job-radar-live-db-access-from-sandbox]]（dangerouslyDisableSandbox + source .env.local + 用户 Homebrew psql）。
       - **改 jobs 列/索引/canonical**：三处仍要同步（lib/canonical-url.js / crawler/normalizer.py / **jobs-db/schema.sql 的 SQL 函数**，不再是 supabase migration 144）。
       - **app 端 jobs 读+写已全部落香港库（2026-06-19，commit 6d814c8/57c9f44）**：原「discovery/enrich 读仍在 Supabase」遗留已清。新增 app 写层 `lib/jobs-store/write.ts`（canonical upsert + updateJobSummaryById，镜像 crawler/jobs_db）；discovery/search 的 upsert、enrich 写回、refresh 选区、insights Tier1 派生全 gated 走香港库（11 个 `.from("jobs")` 文件全 gated，写入端失败不回退 Supabase 避免孤儿数据）。Supabase `jobs` 已是空表（TRUNCATE 过，~17MB）；gated 兜底仅在未配 `JOBS_DATABASE_URL`（本地/回滚）时回退它。**移除 gated 兜底前仍请线上确认稳定**（见 docs runbook）。详见记忆 [[job-radar-phase1-ci-jobs-db-wiring]]。
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

## 目录结构

```
app/                     # Next.js App Router 页面
  page.tsx / today-client.tsx     # Today 今日看板
  jobs/                  # Jobs 岗位库（jobs-client.tsx）
  path/                  # 职业路径（模块 ③，path-client.tsx）
  preferences/ saved/ applied/    # 偏好 / 收藏 / 已投递
  sources/               # Sources 源管理（仅管理员）：列表 + 「添加源」表单（SourceManager）
  admin/insights/        # 洞察管理页（仅管理员）：列/增/改/下架洞察 + 处理申诉（InsightsAdminClient）
  login/ auth/callback/  # 登录与 OAuth 回调
  api/search|discovery|resume/route.ts   # 岗位层后端入口
  api/sources/route.ts   # admin 加招聘源（service-role 写 sources，绕 RLS 无 INSERT 策略）
  api/insights/route.ts + insights/dispute/route.ts   # 模块 B 职业洞察读/录入/申诉
  api/insights/admin/route.ts          # admin 洞察后台：GET 列全部 / POST 增改(过校验门) / PATCH 上下架
  api/insights/dispute/resolve/route.ts # admin 处理申诉：upheld(下架对应 item) / rejected
  api/career-path/route.ts   # 模块 ③ 个性化职业路径（确定性引擎，无 LLM）
components/              # JobCard / JobFilters / PreferenceForm / Navbar / ResumeProfilePanel
                         # SourceTable（presentational，含 reloadSignal）/ SourceManager / AddSourceForm（A1）
                         # InsightsAdminClient（洞察管理页客户端，A2）
                         # CompanyInsightDrawer（公司洞察抽屉，从 JobCard 打开；portal 到 body 防闪烁）
lib/                     # 工具层：supabaseClient、auth、scoring、types、utils
                         # supabaseService（service-role 客户端工厂，admin 写库共用）
                         # source-adapters（adapter/抓取方式白名单 + validateSourceInput 纯函数）
                         # live-search（已知源刷新格式化/校验）、official-discovery、
                         # baidu-qianfan-search、china-keyword-expansion、china-official-sources、client-job-mapping
                         # insight-verification（分级/时效/去标识/归因 纯函数）、insight-match（公司归一匹配）、insight-client（浏览器去重缓存）
                         # insight-bundle（洞察展示门复用）、career-path（确定性职业路径引擎，无 LLM，模块 ③）
crawler/                 # adapters/{base,playwright_base,apple,siemens,baidu,jd,haier,tencent,bytedance,feishu,greenhouse,lever,china_ats,
                         #   meituan,kuaishou,bilibili,pinduoduo,vivo,byd}.py
                         #   china_ats.py = 本土通用 ATS（moka / beisen / company_spa；host 从 source_url 动态解析，浏览器拦截 SPA）
                         # run.py / db.py / normalizer.py / robots.py / discovery.py
                         # probe.py = 扩源探活器：批量 live 探活候选源，仅把「真返回岗位」的写进迁移（本机跑 python3 probe.py --all --emit 025）
                         # 洞察供给：insight_backlog.py(T2 Wikidata+EDGAR+巨潮/T3 经验 drain) / insight_engine.py(接地→判官→共识) / wikidata.py / official_edgar.py(SEC 美股) / official_cninfo.py(巨潮 A股,默认关需 INSIGHT_CNINFO_ENABLED) / insight_sweep.py(过期下架)
                         # search_router.py = T3 多源搜索路由：search_{bocha,tavily,serper,qianfan} provider + search_budget(每源日顶 search_usage 表)；配哪个 key 用哪个、未配跳过、多源并取喂≥2 publisher 共识门
supabase/migrations/     # 001_init → 002_rls → … → 007_candidate_profile_summaries
                         # → 008_discovery_run_diagnostics → 009_discovery_async_runs → 010_seed_spa_sources
                         # → 011_seed_foreign_ats_sources → 012_seed_apple_china_source
                         # → 013_career_insights（模块 B 5 表 + RLS）→ 014_seed_career_insights（四维种子草稿）
                         # → 015_verify_experience_sources（experience 真实来源核验）
                         # → 016_rewrite_culture_and_experience_copy（去「避坑」+ 9 条 experience 正文改通俗）
.github/workflows/daily-crawl.yml   # 每日 + 手动抓取
tests/                   # node --test 单测
```

## 数据库表（8 张，权限见 002_rls.sql）

| 表 | 用途 | 权限 |
|---|---|---|
| profiles | 用户扩展信息 | 自己读写 |
| sources | 企业招聘源 | 所有人读，crawler 写 |
| source_candidates | 官方源发现候选 | admin 读，service role 写 |
| jobs | 共享岗位库 | 所有人读，crawler 写 |
| user_preferences | 用户偏好 | 自己读写 |
| job_actions | 收藏/忽略/投递 | 自己读写 |
| crawl_runs | 抓取日志 | admin 读，crawler 写 |
| discovery_runs | 官方源发现日志 | admin 读，service role 写 |

共享 `jobs`，偏好与操作按 `user_id` 隔离（同一岗位可被 A 标投递、B 标收藏）。

### 模块 B 职业洞察层（migration 013/014，与岗位层严格分离）

| 表 | 用途 | 权限 |
|---|---|---|
| company_profiles | 公司画像（company 唯一 + aliases 对齐 jobs.company） | 所有人读，admin/service 写 |
| insight_items | 洞察条目（dimension/grade/content/时效/payload） | 读仅 `active+deidentified`，admin/service 写 |
| insight_sources | 溯源（链接 + 短摘要，禁整段原文） | 读仅 `deidentified`，admin/service 写 |
| insight_item_sources | 条目↔来源 多对多 | 所有人读，admin/service 写 |
| insight_disputes | 通知-删除申诉（§7.3） | 用户可插/读自己，admin 读全部+改状态 |

五维 `dimension`：`timing`(事实为主) / `listing`(上市/股票，事实，migration 023/024，易变行情不落库数字只存 payload.quote_url 链接) / `compensation_intensity` / `path` / `culture`(做浅重免责)。
AI 辅助录入：`/api/insights/admin/ai-draft`（仅 admin、单次 LLM 调用、复用 lib/llm，产出仅草稿强制 status=retired，必人工核对+补真实来源过门后才展示；不进 cron、不按用户触发，控账单）。
三级 `grade`：`fact`(须带来源) / `experience`(须 sample_size≥5 且多源) / `rumor`(默认拦截)。
展示前必过 `lib/insight-verification.ts` 的分级/时效/去标识/归因门；无可信结果返回 `insight_unverified` / `insight_outdated`。
**数据来源（v2.0 三层供给）= T1 派生（自有岗位库现算 timing/hiring/salary，读时零成本）+ T2 官方事实（Wikidata + SEC EDGAR 上市，cron）+ T3 经验（多源搜索 `search_router`→判官核验，cron）+ 人工策展 seed/admin 录入。合规线不变：官方源=fact、搜索源=去标识聚合+判官+≥2源，不直接爬社区；admin AI 辅助草稿仍须人工核对过门才展示。** **供给自动化（2026-06-20 升级）**：T3 检索多源化（`search_router`，见「百度千帆额度」段）；T2 加 SEC EDGAR 官方上市源；**现查触发**（`/api/insights` GET 对有在招岗位但无画像的公司建占位入队，下次 drain 优先富化，零 churn）；**过期下架**（`insight-staleness-sweep.yml` 每日把 `valid_until` 过期的 active → retired，治「又旧」）；**即时性窗**（搜索四源统一限**近 3 年**：Tavily `start_date`/Serper `tbs` 加时间窗，千帆/博查本就 ≤1 年；T3 经验洞察写入带 `valid_until`=+1 年 → 过期巡检自动退役、180 天复核续期；重富化先退役旧代 public_web culture，不堆积老聚合）。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。 014 种子为待人工核实草稿；015 已用真实公开链接核验 experience 来源；016 把 culture 的「（避坑提示）」改「温馨提示」、9 条 experience 正文改通俗（去掉逐条媒体罗列，正文只留一句轻量归因「据公开讨论/据公开报道」以过 `passesAssertionLint`，统一「来源聚合·去标识」声明只在抽屉顶部 banner 出现一次）。
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

## 百度千帆额度

免费「百度搜索」每日 50 次。控制台 0/50 或未付费时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，`/api/discovery` 直接返回 `provider_rate_limited` / `rate_limited=true`，前端稳定展示不崩。额度耗尽时不要反复点「发现」或跑 5-query live 验证。

**职业洞察 T3 检索已扩为多源路由**（`crawler/search_router.py`：博查/Tavily/Serper/千帆，配哪个 key 用哪个、未配自动跳过、各源 `*_DAILY_CAP` 日顶走 `search_usage` 表 + 迁移 156）。千帆仍受上面 50/天全局额度（`qianfan_usage`），但**不再是唯一检索源** → T3 富化吞吐不再被它单独卡死。新增 env（GitHub Secrets + 本地 `.env.local`）：`BOCHA_API_KEY` / `TAVILY_API_KEY` / `SERPER_API_KEY`（+ 可选 `*_DAILY_CAP`）。合规不变：仍只走搜索 API 取去标识聚合 + 判官核验 + ≥2 源，不直接爬社区。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。

## 认证

Supabase Auth（邮箱登录）+ cookie session。`middleware.ts` 排除 `/api/*`，API 未登录返回 `401 application/json`，不被页面重定向拦截。Sources 页仅管理员。

**页面取当前用户走 `lib/auth.getRequestUser()`，别在页面里再调 `supabase.auth.getUser()`（性能）**：middleware 已对每个页面请求做过 `getUser()`（安全级验证 + 会话刷新 + 未登录重定向），并把验证后的 `user.id/email` 注入转发请求头 `x-user-id`/`x-user-email`（仅服务端可见、入口先 delete 防伪造）；页面用 `getRequestUser()` 零网络读取，省掉每次导航重复一次 auth 网络往返。注意：① `/api/*` 不经 middleware，仍各自 `getUser()`/`requireUser()`；② 改 middleware 的请求头转发时，cookie 头须在 `getUser()` 之后用刷新过的 `request.cookies` 重写，否则 token 刷新那一拍页面会拿到过期 cookie。

**冷启动 / tab 切换不卡**：每个数据页路由配 `loading.tsx`（复用 `components/Skeletons.tsx` 暖纸骨架 + 真实页头），force-dynamic 路由没有 loading 边界会「点 tab 冻屏 + prefetch 失效」；页面内互不依赖的服务端 `await` 用 `Promise.all` 并行。详见记忆 `job-radar-cold-start-tab-latency`。

## 简历画像

粘贴文本 / `.txt` / `.md` → candidate profile → 用户确认后同步 `user_preferences`（只服务排序，不替代检索）。PDF/DOCX 返回 `415 unsupported_file_type`，空文本返回 `400 empty_resume_text`。

## 开发规范

- 按现有风格改，最小化改动，不做无关格式化/重构。
- 复用已有 lib / components / 类型，不引入重型依赖。
- 不吞错（catch 至少记录）。
- 外部请求只走 lib 层封装与 crawler adapters；遵守合规边界。

## 测试规范

- 纯函数优先（scoring、live-search 格式化/校验、normalizer、quality gate、discovery budget）。
- crawler 用 unittest，单测不打真实网络。
- 改 schema 必须同步更新 migrations + 测试（schema 以 migrations 为准，需求文档以 `PRD.md` 为准）。

## 边界（Phase 1 不做）

自动投递 / 登录企业招聘系统 / 绕验证码 / 第三方招聘平台 / PDF·DOCX 复杂解析 / 邮件·飞书·微信推送 / Redis·Celery·K8s·监控大套件 / 无关 UI 大改。

> 注：LLM 不再是硬边界——按「必要时克制接入」原则使用（见 `PRD.md` §0 LLM 使用原则）；已落地简历解析（lib/llm.js）+ 洞察 AI 辅助草稿，岗位匹配/JD 摘要按需可接入、非强制。

## 禁止事项

未经允许不 `git push` / `reset --hard` / `clean`；不读取或输出 `.env*`、service_role key 等密钥；不 force push main；不跳过 hooks。

## 项目特殊注意事项

1. **⚠️ 运行前提 = .env.local**：必须有 `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`。数据库迁移由 CI 自动 apply（见上文「数据库迁移（已自动化…）」），无需手动跑 SQL。绝不提交 / 读取 / 打印这些密钥值。
2. **⚠️ 父级 CLAUDE.md 混淆**：家目录 `/Users/bytedance/CLAUDE.md` 描述的是另一个项目（余声/YuSheng），会被当作父级上下文加载。本项目是求职雷达，与 YuSheng 无关，冲突时以本文件为准。
3. **build 与 dev 不要同时**：dev server 运行期间跑 `npm run build` 会改写 `.next`，导致旧 dev server 静态资源 404；build 后要重启 `npm run dev` 再做浏览器验证。
4. **沙箱限制**：环境可能禁止监听端口 / 阻断网络（Supabase / 百度 / 京东 live）；`git push`、live SQL / 链接验证也需用户本机执行，不能用本地单测冒充 live 验证。
5. **Vercel 实时 upsert**：必须把 `SUPABASE_SERVICE_ROLE_KEY` 配为服务端环境变量，绝不暴露给浏览器。

## 测试账号（需先在 Supabase 建好）

`test@jobradar.local` / `test123456`
