# 后端闭环全面审阅 · Agent 任务书（Backend Loop Audit）

日期：2026-08-26
委托人：创始人 / 技术负责人
受托方：高级工程 Agent（本文件即你的完整任务书，可独立执行，不需要追问上下文）
性质：**审阅 + 诊断 + 优化方案**，不是实现任务（实现是下一轮）

---

## 0. 一句话任务

我们已经有一套跑得起来的后端闭环（爬虫供给 → 入库 → 治理 → 召回 → 匹配 → 呈现，外加一条职业洞察供给线）。
**它闭环了，但不够准、不够全、不够好用。** 你的任务是把这套闭环从头到尾审一遍，用**实测证据**指出问题，
给出**按投入产出排序**的优化方案。

允许你读代码、连生产库、跑只读查询、跑单测、看 CI 历史。**不要改业务代码、不要 push、不要跑任何写库操作。**

---

## 1. 产品最终要什么（判断优先级的唯一标尺）

用户来到产品，必须真正拿到两件事。任何优化点，都要能回答「它让下面哪一条更接近达成」：

**核心价值 ①：岗位找人，而不是人找岗位**
- 推荐要**准确**：推给我的岗，必须真的匹配我的简历/偏好（方向、城市、阶段、行业、学历）。
- 推荐要**可靠**：推的岗必须真的还在招（点进去不能是死链/已关闭）。
- 岗位库要**全面**：用户想得到的公司，库里得有，且有真实可投的岗——用户不该再去别处搜一遍。

**核心价值 ②：职业洞察要 solid**
- 多维度真信息差（行业 / 岗位 / 公司文化 / 薪酬强度 / 晋升路径 / 招聘时机 / 上市与业绩）。
- 帮用户判断「要不要投、要不要去、怎么选 offer」。
- 必须可信、可溯源、不过期——宁可说「暂无可信信息」，也不能编。

**次要约束**：前端交互尽量少步骤。本轮不审前端交互设计，但**如果某个后端设计逼着前端多加步骤，要点出来**。

---

## 2. 系统现状地图（照这个走，别从零摸）

### 2.1 数据落在哪（先搞清这个，否则查错库）

| 数据 | 位置 | 访问方式 |
|---|---|---|
| `jobs` 热表（约 38 万 active） | **自建香港 PostgreSQL 17** | 连接串在 `JOBS_DATABASE_URL`（GitHub Secret / Vercel env / 本地 `.env.local`）。app 侧走 `lib/jobs-store/`，爬虫侧走 `crawler/jobs_db.py` |
| `sources` / `crawl_runs` / `discovery_runs` / `ops_runs` / 用户表 / 洞察全套 | **Supabase** | PostgREST 或直连；⚠️ PostgREST 默认 1000 行静默截断，必须分页（`lib/supabase-paginate.ts` / `crawler/db.fetch_all_rows`） |
| Auth | Supabase（悉尼） | 请求路径上一律本地 JWT 验签，见 `lib/auth-claims.ts` |

`jobs` 表 schema 权威在 `jobs-db/schema.sql`（不是 supabase migrations）。

### 2.2 供给层（岗位从哪来）

四条并行的供给通道，各有独立编排：

1. **日常抓取**：`.github/workflows/daily-crawl.yml` + `enrich-crawl.yml` → `crawler/run.py` 分片跑 `crawler/adapters/*`（40+ adapter：自建门户 / 通用 ATS(greenhouse/lever/workday/beisen/moka/feishu/hotjob-wt) / 国聘 / 大厂 SPA）
2. **每日自动扩源**：`auto-discover.yml`（httpx，`crawler/auto_discover.py`，`PLATFORMS = {"feishu","hotjob"}`）+ `auto-discover-browser.yml`（beisen/moka）+ `auto-discover-overseas.yml`。清单来自 `crawler/targets_*.json`，另有 LLM 生成器 `crawler/generate_targets.py` 持续喂料。**所有候选必须过 live 探活门才入库**。
3. **必投缺口漏斗**：`gap-funnel.yml` → `crawler/gap_census.py`（清单×库存 → 台账 `must_apply_gap_attempts`）→ `entry_finder.py`（找官方招聘入口）→ `platform_fingerprint.py`（认平台）→ `gap_funnel.py`（真抓 + 验收门 + 按原因退避）
4. **校招高频车道**：`campus-crawl.yml` + `crawler/campus_lane.py` / `campus_crawl.py`（`sources.board` 分流、开闸检测、届别 `grad_class`）
5. **用户触发**：`/api/refresh`（刷新公司库，异步 workflow_dispatch）、`/api/discovery`（官方源发现）、`/api/search`（旧同步已知源刷新）

### 2.3 入库与治理层（质量怎么保）

- **归一/质量门**：`crawler/normalizer.py`（含 `geo.py` / `grad_class.py` / `sponsorship.py` / `salary.py`）；`jd_url` 质量门；canonical URL 去重（`lib/canonical-url.js` + `crawler/normalizer.py` + `jobs-db/schema.sql` 三处必须字节级一致）
- **富化**（补 JD 正文）：`enrich-backlog.yml` / `enrich-backlog-browser.yml` → `crawler/enrich_backlog.py` + `enrich.py`
- **探活/撤岗**：`liveness-sweep.yml`（逐岗 detail 判死）+ `dead-link-audit.yml`（浏览器 SPA 源）+ 展示时异步探活 `/api/jobs/liveness-check`（`lib/liveness-client.js`）
- **清理**：`purge-expired.yml`（expired 永久删）、`maintenance-vacuum.yml`
- **体检**：`db-report.yml`（只读 psql 报告）、`/admin/health`（运营看板，`lib/admin-health.ts`）
- **北极星指标**：必投清单健康覆盖（`lib/must-apply-list.ts` + `lib/must-apply-list.json`，11 行业 × 30 家；健康 = `active` 且 `summary` 去空白 ≥60 字）

### 2.4 召回与匹配层（推荐怎么产生）— **本轮重点怀疑区**

**Today（今日机会）路径**：
```
lib/opportunities/service.ts
  → recallOpportunityCandidates()  [lib/jobs-store/opportunities.ts]
        三层加权轮转 SQL：方向(role) / 目标公司(company) / 目标城市近7天新增(cityNew)
        RECALL_BUDGET = 900        ← lib/jobs-store/opportunities.ts:56
  → computeMatchFacts()            [lib/opportunities/eligibility.ts:150]
  → checkEligibility()             [lib/opportunities/eligibility.ts:210]  硬门，第一个不过就拒
        拒绝序：inactive → thin_summary → source_disabled → stale → excluded
                → already_actioned → role_mismatch → location_mismatch
                → stage_mismatch → education_mismatch → industry_mismatch
        unknown 维度不拒绝，累积成 degraded（放行 + 打分轻罚）
  → scoreOpportunity()             [lib/opportunities/scoring.ts]
  → 分组/信号/时效                  [grouping.ts / signals.ts / freshness.ts / intensity.ts]
```

**Jobs（岗位库）路径**：`app/api/jobs/search|list` → `lib/jobs-store/search.ts`（中文 bigram FTS）→ `lib/scoring.ts:scoreJob`（**软打分，不是硬门**）+ `lib/job-filter.ts`

**共用匹配器**（改动这几个文件会同时影响两条路径）：
- `lib/china-keyword-expansion.js`（922 行）：`keywordMatchTier`（exact/related/null）、`classifyJobFunction`（职能门）、`recruitmentCategory`（实习/校招/社招）、`normalizeChinaCity`
- `lib/company-industry.js`（211 行）：11 类行业分类 + `jobIndustryAllowed` 跨行业硬门
- `lib/education-rank.js`：学历 pass/degrade/reject
- `lib/job-scope.ts` / `lib/geo.js`：国内/海外范围

### 2.5 洞察层（模块 B）

- 三层供给：**T1** 自有岗位库派生（`lib/insight-derive.ts`，读时现算）/ **T2** 官方事实（`crawler/wikidata.py`、`official_edgar.py`、`official_cninfo.py`）/ **T3** 经验（`crawler/search_router.py` 多源搜索 → `insight_engine.py` 接地+判官+≥2 源共识）
- 编排：`insight-enrich.yml`（单公司现查快车道）/ `insight-enrich-t3.yml` / `insight-staleness-sweep.yml`（过期下架）
- 展示门：`lib/insight-verification.ts`（分级 fact/experience/rumor + 时效 + 去标识 + 归因），过不了返回 `insight_unverified` / `insight_outdated`
- 众包补充：`/api/insights/submit`（≥5 条匿名聚合才展示）
- 五维：`timing` / `listing` / `compensation_intensity` / `path` / `culture`（另有 `hiring`）

---

## 3. 已实测基线（2026-08-26，你可以复核，但不必重复测）

**岗位库**
| 指标 | 实测值 |
|---|---|
| active 岗位 | 380,595 |
| 其中有 JD 正文（≥60 字） | 373,117（98.0%） |
| active 但**从未探活**（`enrich_checked_at is null`） | 77,633（20.4%） |
| 近 7 天新增 | 28,643 |
| **不同公司数** | **1,162** |
| Top-20 公司占 active 比例 | 25.9%（字节 20,577 / Amazon 11,804 / Wells Fargo 6,034 / 比亚迪 5,936 …） |
| `sources` 表行数 | 1,444 |
| Today 单次召回预算 | **900 行 = 库存的 0.24%** |

**必投清单**（`must_apply_gap_attempts` 321 行）：健康覆盖约 **205/321**（2026-08 攻坚后）。历史塌陷行业：金融、教育、能源化工、物流供应链、传媒文娱。

**洞察**
| 指标 | 实测值 |
|---|---|
| `insight_items` 总行数 | 6,310 |
| 其中 `status=active` | 6,164 |
| **有 ≥1 条 active 洞察的公司数** | **484** |
| 覆盖率（对比 1,162 家在招公司） | **≈41.7%** |
| 维度完整度 | 5 维全有 93 家 / 4 维 202 / 3 维 75 / 2 维 79 / 1 维 35 |
| `company_profiles` | 1,112 |

---

## 4. 六条审阅主线

每条给你：**用户症状 → 我们的初步怀疑（可能错，请证伪）→ 你必须回答的问题 → 建议实测方法**。
⚠️ 「初步怀疑」是线索不是结论。本项目多次出现「凭感觉判错」（见 §5），**请优先证伪**。

---

### 主线 A：推荐准确性 —「推给我一堆不匹配我简历的岗」

**初步怀疑（按可能性排序）**
1. `keywordMatchTier` 的 `related` 档太松（`lib/china-keyword-expansion.js:799` 附近，兄弟组排除逻辑复杂），"相关" 泛化过头。
2. `checkEligibility` 里 unknown → degraded 放行的口子太多：`location unknown` / `stage unknown` / `education unknown` / `industry unknown` 四个维度同时 unknown 的岗仍会被展示，只是轻罚。库里大量岗缺 `location`/`education`/`job_type` 字段 → degraded 成为常态而非例外。
3. Jobs 页走的是 `lib/scoring.ts` **软打分**，没有 Today 的硬门 —— 两条路径口径不一致，用户在 Jobs 页看到的"匹配"和 Today 不是一回事。
4. 简历 → 偏好的映射失真：`lib/resume-parser.js` / `resume-extract.js` 抽出的 `target_roles`/`target_keywords` 太宽或太杂，污染下游（注意 `userTargetFunctions` 已刻意只用 target_roles 不用 keywords，说明这个坑踩过）。

**你必须回答**
- A1. 取 3–5 个真实用户画像（或构造覆盖不同行业/阶段的画像），跑一遍 Today 全链路，**逐岗标注**：这条岗为什么被放行？命中的是 exact 还是 related？degraded 了哪几维？人工判断它到底该不该出现？给出**误报率**（不该出现却出现）和**漏报率**（该出现却没出现）。
- A2. degraded 维度的分布是多少？「四维全 unknown 仍放行」的岗占展示结果多大比例？
- A3. `related` 档贡献了多少展示岗位？把 `related` 收紧到什么程度，误报下降而漏报不明显上升？
- A4. Today 硬门与 Jobs 软打分的口径差异，在真实数据上有多大？该不该统一？统一成哪一套？
- A5. 简历解析产出的偏好字段质量如何？有没有系统性污染（例如把技能词写进 target_roles）？

**方法**：读 `lib/opportunities/*` 全套 + `lib/china-keyword-expansion.js`；用只读 SQL 复现召回；离线跑 `checkEligibility`/`scoreJob` 纯函数对真实行打分（这两个都是纯函数，可直接喂数据）。已有测试在 `tests/*.test.js`。

---

### 主线 B：召回覆盖 —「该推的没推 / 库里有却捞不出来」

**初步怀疑（这条最像结构性问题）**
- **`RECALL_BUDGET = 900` 对 380,595 条 active，一次只看 0.24%**。谁进这 900 条，由三层 SQL（方向 tsquery / 目标公司 / 城市近 7 天）的加权轮转决定 —— 而代码注释自己写着：**「SQL 的方向层并不是 JS 方向门的超集」**（`lib/jobs-store/opportunities.ts:179`）。也就是说 JS 匹配器认可的岗，SQL 层可能根本没捞进来，**且这种漏是静默的、指标上看不见**。
- Top-20 公司占 26% 库存，字节一家 2 万条 —— 召回层若没有公司级多样性约束，大厂会挤占预算。
- 只有 1,162 家公司支撑 38 万岗 —— 平均每家 327 条，**长尾公司极少**，用户想要的中小公司大概率不在库里。

**你必须回答**
- B1. 量化召回漏报：对若干真实画像，用**全库扫描**（离线、只读、可慢）跑一遍 JS 匹配门，得到"理论应召回集合"，再对比 900 条召回实际捞到的，算召回率。这是本轮最重要的一个数字。
- B2. 三层加权轮转的权重与预算分配是否合理？某层取空时的名额转移是否真的生效？
- B3. 900 这个预算的瓶颈到底是什么（跨区传输？香港库 2vCPU？JS 侧打分？）——注意历史结论：**瓶颈曾是传 15MB summary，不是 SQL 本身**（`lib/jobs-store/opportunities.ts` 已做列截断）。现在还是吗？
- B4. 有没有比"扩大 budget"更划算的解法？例如：物化派生匹配字段（job_function / city_norm / stage）建索引，把 JS 硬门的一部分下推到 SQL，让召回真正成为匹配的超集。请评估可行性与迁移成本。
- B5. 公司多样性：召回/展示层要不要加 per-company cap？加了对覆盖和体验分别什么影响？

---

### 主线 C：岗位库全面性 —「很多公司爬得不够全 / 各行业 30 家覆盖不够 / 央国企完全没打通」

**已知事实**
- 必投清单 205/321，缺口台账在 Supabase `must_apply_gap_attempts`（321 行，含每家走到哪一步、失败原因、复查日期）。
- 央国企：`crawler/adapters/iguopin.py`（国聘，国资委官方平台）**已实现且 live 验证过**——它是"禁止第三方招聘平台"红线的**唯一例外**（创始人 2026-07-26 拍板）。但用户反馈「央国企没打通、没有任何岗位」，说明**要么源没启用、要么在跑但没产出、要么产出没进健康口径**。这是本主线第一个要查清的事。
- 2026-08-26 已发现四处断路（详见 git log）：本地 545 条已核验域名表被闲置、招聘内容门跑在提纯文本上误杀 SPA、队列队头阻塞（40 家从没跑过）、P1 发现的 SPA 入口白等一轮。**请复核这四处是否真的修好了、有没有同类问题还在。**

**你必须回答**
- C1. **央国企专项**：`sources` 里有多少 iguopin 源？enabled 几个？最近一次成功抓取是什么时候？产出多少健康岗？如果为 0，根因是什么（源没插 / adapter 坏 / 核名 `company_name_match` 过严 / 被探活扫成 expired / 从没进过 CI 分片）？给出可执行修复路径。
- C2. **"爬得不够全" 的量化**：抽 10–15 家头部公司（字节、腾讯、阿里、美团、华为、百度、小米、京东…），拿"库存健康岗数 ÷ 对方官网列表 total"算抓全率。历史实测头部有严重缺口（字节曾 ≤4%、百度 <1%，后已重写）。**现在的真实抓全率是多少？**注意：`crawler/adapters/base.py` 有 `paginate_all` helper 和 `PageResult.reported_total`，可用来判断是否翻到底。
- C3. **必投清单剩余 116 家缺口的分类**：分成 ① 技术上能打通（给 adapter/路由方案）② 对方根本不公开招聘（应走清单治理换人，注意硬规则：**绝不因"我们抓不到"换人**，只因"不值得投/不公开招聘"换）③ 需要人工介入（反爬/登录墙）。给出分类清单与各自动作。
- C4. **长尾问题**：1,162 家公司够不够支撑"用户不用再去别处搜"？如果不够，缺的是哪一类（按行业/城市/规模）？扩到什么量级才够？现有扩源机制（auto_discover 4 平台 + gap funnel + ats-scrapers 同步）的产能天花板在哪？
- C5. **扩源精度 vs 规模**：现在的验收门（live 探活 + 真有在招岗 + 标题核验）会不会挡掉太多真源？误杀率多少？

---

### 主线 D：岗位可靠性 —「点进去是死岗 / 假 active」

**已知事实**
- 77,633 条 active **从未被探活**（20.4%）。
- 治理机制齐全（liveness-sweep / dead-link-audit / 展示时异步探活 / purge-expired），但历史上多次"跑了等于没跑"（statement_timeout 静默失败、upsert 把 expired 刷回 active 并抹掉 `enrich_checked_at`、巡检轮转饿死 UUID 靠后的源）。

**你必须回答**
- D1. 77,633 条 never-checked 是在**增长还是收敛**？按源/adapter 拆开看，集中在哪些源？巡检产能 vs 新增速度的账算得平吗？
- D2. 现有三层探活（后台 sweep / 浏览器审计 / 展示时异步）的**实际覆盖率与命中率**分别多少？有没有源是三层都覆盖不到的盲区？
- D3. 抽样验证真实死链率：随机抽 100–200 条展示态岗位（模拟用户看到的那批），实测 HTTP 可达性 + 页面是否真是在招岗。给出**用户实际遇到死岗的概率**。
- D4. ⚠️ 红线复核：`supports_absence_liveness`（列表缺席即撤岗）当前对哪些源开着？逐个确认这些源的列表接口**确实返回全集**。历史上因为误开差点删掉 460 个在招岗（详见 CLAUDE.md「列表里没有 ≠ 已撤岗」）。

---

### 主线 E：筛选器 —「不好用、不准」

**初步怀疑**
- 筛选项的可选值是从哪来的？是库里真实存在的值，还是硬编码枚举？（历史病根之一："默认当事实"）
- 筛选后的计数与实际结果是否一致？
- 筛选是走 SQL 还是走 JS 后过滤？两者口径一致吗？
- 城市/行业/职能等维度，用户填的词与库里的值之间是否有归一层（`normalizeChinaCity` / `classifyCompanyIndustry` / `classifyJobFunction`），归一失败时怎么办？

**你必须回答**
- E1. 逐个筛选维度（城市 / 职能 / 行业 / 招聘类型 / 学历 / 经验 / 求职范围 / 公司）走一遍：选项从哪来、怎么匹配、匹配不上时的行为、结果计数是否可信。
- E2. 找出"筛了反而更差"的具体场景（选某个值后结果为空或明显不相关），给复现步骤。
- E3. 筛选器与推荐匹配器是不是同一套口径？不是的话，用户在两处会得到矛盾的结果——这是"不准"的高概率来源。
- E4. 前端交互角度：有没有筛选项是可以自动推断而不必让用户选的（少步骤原则）？

**入口**：`components/JobFilters.tsx`、`app/jobs/jobs-client.tsx`、`lib/job-filter.ts`、`lib/jobs-store/search.ts`、`app/api/jobs/search/route.ts`。历史设计文档见 `docs/superpowers/specs/2026-06-11-keyword-filter-precision-design.md`。

---

### 主线 F：职业洞察 —「要真的 solid」

**已知事实**：484/1,162 家在招公司有洞察（41.7%）；6,164 条 active；93 家五维齐全。

**你必须回答**
- F1. **覆盖**：58% 的在招公司没有任何洞察，用户点开抽屉看到的是什么？现查快车道（`insight-enrich.yml` + `lib/insight-enrich-now.js`）触发率与成功率多少？搜索额度（bocha/tavily/serper/qianfan 各自日顶）是不是产能瓶颈？按现在的速度补齐要多久？
- F2. **质量**：随机抽 20–30 条 active 洞察人工核验——来源链接还活着吗？内容与来源对得上吗？判官+≥2 源共识门实际拦掉了多少？有没有"看着像但其实是套话"的（对用户没有信息差价值）？
- F3. **时效**：`valid_until` 过期巡检真的在跑吗？现存 active 里有多少已经实质过时（例如引用两年前的组织架构）？
- F4. **维度价值**：五维里哪几维用户真的会看？`culture` 占 436 条（最多）但做了浅重免责后还剩多少信息量？有没有更该做但没做的维度（例如：真实薪资区间、面试流程与轮次、部门口碑差异、裁员/收缩信号）？
- F5. **合规边界复核**：确认没有直接爬社区/第三方招聘平台的路径（红线：智联/BOSS/前程无忧/猎聘禁止；国聘是唯一例外）。

---

## 5. 工作方法硬约束（本项目血泪教训，违反等于白干）

1. **先证伪，再下结论**。本项目多次出现凭感觉判错：曾以为"CI 突然频繁失败"（实测 24h 只有 3.4%，且多为 GitHub 官方故障）；曾以为"列表只返 13 条所以其余 460 个是死岗"（逐个核验后 460 个全部在招）。**任何"我觉得 X 有问题"，先给出证伪它的实测。**
2. **不可逆操作前，核验样本量必须匹配影响面**。要清 447 行就核验 447 行，抽查 2 个不算数。（本轮你只做只读，但你**建议**的方案里如果含删除/标记操作，必须写清核验方案。）
3. **CI 绿灯 ≠ 有产出**。判死活要看"源刷新率""真实入库条数"，不看 workflow 状态。`--limit 0` 曾等于处理 0 个却一路绿灯。
4. **run 级成功 ≠ job 级成功**。分片任务要看 job 级。
5. **指标口径必须诚实**。岗位库计数一律用 `count_valid_active_jobs()`（active + JD ≥60 字），禁止裸 `count(status='active')`。你报的任何数字都要写清口径。
6. **对生产库做前后对拍，必须在同一个 REPEATABLE READ 快照里**，否则数据在变、对拍无意义。
7. **测 DB 耗时要区分冷热缓存**。
8. **归一逻辑活在三处**（`lib/canonical-url.js` / `crawler/normalizer.py` / `jobs-db/schema.sql`），任何涉及它的建议都要说明三处怎么同步。
9. **引用的函数/文件必须真实存在**。不确定就先 grep 确认，禁止假设某个 API 存在。
10. **诚实边界**：查不到就说查不到，别用推测填空。给不出证据的怀疑，标注为「未验证假设」。

---

## 6. 交付物

一份 Markdown 报告，写到 `docs/superpowers/specs/2026-08-26-backend-loop-audit-report.md`，结构如下：

### 6.1 执行摘要（给非技术背景的创始人看，讲人话，≤1 页）
- 现在的后端整体健康度一句话结论
- 最伤用户体验的 3 个问题，每个用一句大白话说清「用户会遇到什么 → 因为后端哪里坏了」
- 如果只做 3 件事，做哪 3 件，各自预期收益

### 6.2 六条主线的逐条诊断
每条主线给出：
- **实测数据**（表格，写清口径与测量时间）
- **确诊问题**（附证据：SQL 输出 / 文件:行号 / 抽样结果）
- **证伪掉的怀疑**（哪些我们以为的问题其实不是问题——这部分同样重要）
- **未验证假设**（明确标注，说明验证需要什么）

### 6.3 问题清单（按严重度分级）
| 级别 | 定义 |
|---|---|
| P0 | 直接伤害核心价值①②，用户能感知，且现在正在发生 |
| P1 | 结构性缺陷，现在被兜底掩盖，但会随规模增长爆发 |
| P2 | 效率/成本问题，不影响用户体验 |
| P3 | 代码质量/可维护性 |

每条含：现象 / 根因（带证据）/ 影响面（量化）/ 修复方案 / 工作量估计 / 风险。

### 6.4 优化路线图
按 **ROI 排序**（收益 ÷ 成本），分三档：
- **本周能做**（改动小、收益明确）
- **两周内**（需要设计，但路径清楚）
- **需要架构决策**（例如"召回层要不要下推到 SQL""要不要引入向量检索""岗位库要不要扩到 X 万家公司"）——这类只给方案与取舍分析，**由创始人拍板**，不要擅自选定。

### 6.5 你认为我们问错了的问题
如果你在审阅中发现真正的瓶颈不在上面六条主线里，**直说**。这一节比前面所有节都值钱。

---

## 7. 边界与红线

**不许做**
- 不改业务代码（只读审阅；写报告和一次性只读分析脚本可以，脚本放 `scratchpad/` 或 `/tmp`，不进 git）
- 不 `git push`、不 `reset --hard`、不 `clean`、不 force push
- **不对生产库做任何写操作**（不 UPDATE / DELETE / INSERT / DDL；`gh workflow run` 任何会写库的 workflow 也不许）
- 不读取或打印任何密钥、token、连接串、服务器 IP（本仓库是 **GitHub PUBLIC**，写进文件即永久公开）
- 报告里禁止出现：本机绝对路径、服务器 IP/主机名、真人姓名/邮箱/手机号、任何密钥
- 不建议接入第三方招聘平台（智联/BOSS/前程无忧/猎聘），国聘 iguopin 是唯一例外
- 不建议引入重型依赖 / Redis / Celery / K8s / 监控大套件

**可以做**
- 连生产库跑**只读** SQL（`select` / `explain`）
- 跑单测：`node --test tests/*.test.js` 和 `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`
- 看 CI 历史：`gh run list` / `gh run view`
- 抓取公开网页做抽样核验（例如验证某个 jd_url 是否还活着、某公司官网 total 是多少）
- 跑 `db-report.yml`（只读报告）

---

## 8. 环境与工具

- 工作目录：本仓库的 worktree（**不要 `cd` 到主仓库根目录**）
- 环境变量：本地 `.env.local`（在**主仓库根目录**，不在 worktree 里）。用法：`set -a; source <主仓库根>/.env.local; set +a`
- 连香港 jobs 库：`psql "$JOBS_DATABASE_URL"`。⚠️ 沙箱的 TLS 代理会抹空响应，必须 `dangerouslyDisableSandbox: true`；本地缺 `JOBS_DATABASE_SSL_CA`（只 CI 有），所以走 `crawler/jobs_db.get_conn()` 严格 TLS 的路径在本地跑不了，直接用 psql
- 连 Supabase：PostgREST（`$SUPABASE_URL` + `$SUPABASE_SERVICE_ROLE_KEY`），⚠️ **必须分页**，单次最多 1000 行且静默截断
- 本环境**网络是通的**（git / gh / psql / curl 都能用）。不要以"沙箱连不上网"为由跳过 live 验证
- 大表 ilike 全扫会超时（330 个 pattern 的必投覆盖查询实测 >2min），需要分批或用索引

**必读背景文档**（别全读，按主线按需读）
- `CLAUDE.md`（项目级，含核心产品原则与所有历史踩坑，**这份一定要读完**）
- `docs/superpowers/specs/2026-07-26-must-apply-gap-funnel-design.md`（主线 C）
- `docs/superpowers/specs/2026-07-31-today-recall-two-phase-handoff.md`（主线 B）
- `docs/superpowers/specs/2026-06-09-job-radar-retrieval-recall-design.md`（主线 A/B）
- `docs/superpowers/specs/2026-06-11-keyword-filter-precision-design.md`（主线 A/E）
- `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`（主线 F）
- `docs/superpowers/specs/2026-06-28-crawler-throughput-orchestration-design.md`（主线 C/D）
- `docs/jobs-database-runbook.md`

---

## 9. 建议的执行顺序

1. 读 `CLAUDE.md` 全文 + 本文件 §2 地图，建立系统心智模型（约 1 小时）
2. 复核 §3 基线数字（只读 SQL，半小时）——**如果和你测出来的对不上，先搞清为什么，这本身可能就是一个发现**
3. **主线 B（召回覆盖）优先**——它是最可能的结构性病根，且 B1 那个"召回率"数字会直接决定 A 和 E 的诊断方向
4. 然后 A（准确性）→ E（筛选器），这两条共用匹配器，一起看效率高
5. 再 C（全面性）→ D（可靠性），这两条共用供给/治理链路
6. 最后 F（洞察），相对独立
7. 写报告，**执行摘要最后写**

预计工作量：这是一次深度审阅，不要赶。宁可六条主线做透四条并说清剩下两条没做，也不要六条都浮在表面。
