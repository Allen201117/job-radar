# 求职雷达 · 外部审阅指引

> **写给**：受托对本项目做第一性原理审阅的高质量 Agent（下称"审阅方"）。
> **写作方**：本项目全程的产品与技术负责人（Claude Code），以对接人身份提供背景、证据与取证方法。
> **成稿时间**：2026-09-06。文中所有"实测数字"均带取数命令，**过 24 小时请自己重跑**，不要引用本文的数字下结论。
> **本文定位**：让你少花两天摸索、把精力放在判断上。**它是背景材料，不是结论清单。**
> 凡本文与代码/线上数据冲突，**以代码和线上数据为准**，并请在报告里点名"指引第 X 节写错了"。

---

## 0. 你的任务

对四层做审阅并给建议，四层各自的判据不同，**不要混着答**：

| 层 | 你要回答的核心问题 | 判据 |
|---|---|---|
| **L1 产品价值** | 这个产品解决的是不是真问题？现在的价值主张成立吗？ | 用户行为数据 + 供需结构，不是"听起来有没有道理" |
| **L2 产品方案** | 现在的功能形态是不是通向那个价值的最短路径？ | 每个模块能不能指出它服务哪个用户决策 |
| **L3 技术方案** | 架构选型（自建爬虫 / 三库分离 / GitHub Actions 当调度器 / 无缓存层）是不是当前约束下的最优解？ | 约束（1 人 + Agent、免费/低价基建、公开官网数据）下的可行解集合 |
| **L4 技术实现** | 选型对了，写得够不够好、够不够快、够不够稳？怎么改？ | 读代码 + 跑真实数据，给可执行的改法 |

### 用户点名要你回答的样例问题（原话转述）

> "现行的爬虫是否是最优的方案？就算爬虫是最优的实现路径，那么现在的爬虫是不是写的足够好、足够高效、足够稳定？如果不够好，怎么优化？"

爬虫是重点，但**不要只审爬虫**——L1/L2 的结论可能会让"优化爬虫"这件事本身变得不重要（见 §6.1）。

### 交付物格式要求

1. **每条结论必须能指向可复现的证据**：文件:行号 / SQL 及其返回值 / CI run id / 线上响应。指不出来的，明写"这条是推测，未验证"。
2. **分清"观测"与"结论"**：「接口返 0」是观测，「对方没这功能」是结论；升级要额外证据。本项目在这一点上栽过六次，清单见 §9.1。
3. **建议分三档**：`必须改`（真实故障 / 数据错误 / 安全）、`建议改`（有明确收益且成本可控）、`不建议改`（现状是有意的取舍，说明为什么）。**"不建议改"这一档必须有内容**——全是"要改"的报告说明没读懂取舍。
4. **凡是要下否定结论**（"这个做不到""对方没开放""没有更好的方案"），必须说明你是**扫了全集**还是**试了几个样本**。后者不构成否定结论。
5. **量化的地方要双向**：一个改动通常同时有正反两个方向的影响，只报净值等于没验证（本项目吃过亏，见 §9.4）。

---

## 1. 一页纸：这是什么产品

**求职雷达 / Job Radar**：每天自动监控一批**企业官方招聘网站**，把公开岗位收进共享岗位库，按用户偏好排序推给他，点击**直达官网原始岗位详情页**。

**第一原则**：`jd_url` 准确性 > 一切。拿不到稳定、可点开、内容对得上的逐岗链接，宁可不收录。规模从来不是成功指标。

**与招聘平台的差异**：不碰 BOSS / 智联 / 前程无忧 / 猎聘（产品红线，唯一例外是国资委官方平台"国聘"）。卖点是"官方源 + 逐岗原链接 + 按你的画像排序"。

**双层结构**（PRD 的核心设计，两层数据严禁互相污染）：
- **岗位层**：官方、确定、可点击。质量门严格。
- **洞察层**：公司信息差（时机 / 上市 / 强度 / 路径 / 文化），聚合 + 分级 + 归因 + 时效，**不作为产品断言输出**。设想中的付费点。

**线上**：https://job-radar-sigma.vercel.app ｜ **仓库**：https://github.com/Allen201117/job-radar （**PUBLIC**）

**当前产品面**（8 个登录后页面 + 3 个管理员页）：
`/today` 今日机会（主产品）· `/jobs` 岗位库 · `/insights` 洞察库 · `/path` 职业路径 · `/campus` 校招专区 · `/saved` 值得投 · `/applied` 已投递 · `/me` 我的（偏好 + 简历画像）；管理员：`/sources` `/admin/insights` `/admin/health`。

**技术栈**：Next.js 15 App Router + React 18 + TS + Tailwind（Vercel，函数区锁 `hkg1`）· Supabase（Auth / 元数据 / 用户表）· 自建 PostgreSQL 17（岗位热表，香港，2C2G）· Python crawler（httpx + selectolax，部分 Playwright）· GitHub Actions（39 个 workflow 当调度器）。

---

## 2. 真实数字（2026-09-06 实测，取数命令见 §8）

### 供给侧
| 指标 | 值 |
|---|---|
| jobs 表 active / removed / expired | 455,635 / 50,723 / 1,871 |
| 有效在招（active + 正文 ≥60 字，`count_valid_active_jobs()`） | 438,986 |
| 无正文薄卡（active） | 16,649（3.7%） |
| active 覆盖公司数 | 1,320 |
| 国内 / 海外（`job_scope`） | 314,121 / 141,514 |
| 社招 / 校招 / 实习 / 未分类 | 359,902 / 65,547 / 29,003 / 1,183 |
| 库大小 / jobs 表 | 1,935 MB / 1,729 MB（机器内存 2 GB） |
| sources 总数 / enabled | 1,567 / 1,351 |
| enabled 源抓取方式 | http 760 / playwright 591（**44% 走浏览器**） |
| enabled 源 top adapter | moka 390 · beisen 321 · hotjob 134 · feishu 122 · workday 97 · greenhouse 73（**前四合计 72%**） |
| 近 7 天日增岗 | 4,784 → 5,269 → 5,572 → 6,456 → **69,987** → 21,727 → 1,119（09-04 抬列表上限所致，非常态） |

### 治理侧（← 这里有异常，请优先查证）
| 指标 | 值 | 我的判读 |
|---|---|---|
| active 从未探活 | 112,899（24.8%） | 09-03 那次审阅时是 61,060（15.5%），**三天涨了 5.2 万** |
| active 超 7 天未探活 | 211,641（**46.4%**） | 09-03 是 24%。**探活吞吐没有跟上供给增长**，这是我目前最不放心的一条 |

### 需求侧（**这一节是本文最重要的部分**）
| 指标 | 值 |
|---|---|
| 注册用户 | 80（6月13 / 7月26 / 8月30 / 9月11） |
| 填过偏好 | 51 |
| 传过简历画像 | 28 |
| 岗位动作总数（累计三个月） | **665**：viewed 522 / ignored 69 / saved 62 / **applied 12** |
| 产生过任何动作的用户 | 34 |
| 洞察投稿 / 申诉 | 1 / 1 |

**供需比**：45.5 万个岗位 : 12 次"标记已投递"。这不是一句吐槽，是**你做 L1 判断时最硬的一条事实**。

### 工程侧
| 指标 | 值 |
|---|---|
| 提交数 / 项目年龄 | 1,294 / 97 天（2026-06-01 起） |
| 前端代码（app+lib+components） | 47,916 行 TS/TSX/JS |
| 爬虫代码 | 66,598 行 Python（含测试） |
| adapter 数 | 69 个文件 |
| Supabase 迁移 | 243 个 |
| 测试 | JS 137 文件 / 1,194 个 `test()`；Python 159 文件 / 2,027 个 `test_*` |
| GitHub Actions workflow | 39 个（30 个带 cron） |
| 近 100 次 CI（约 30 小时窗口） | success 96 / failure 3（均为 db-migrate，已修复）/ queued 1 |
| 运行时依赖 | 18 个 npm 包（含 4 个 Radix、GSAP、pg、unpdf、tesseract.js） |

### 成本侧
- **GitHub Actions：公开仓库 = 免费无限分钟**。这是"39 个 workflow"这个看似奢侈的设计能成立的根本原因，也是它的**唯一支柱**——仓库一旦转私有，成本模型立刻崩（09-03 审阅口径：日均约 1,139 分钟 runner 时间 ≈ 每天 19 小时）。
- 香港 PG：轻量 2C2G/40GB。Supabase：Free。Vercel：Hobby。LLM：SiliconFlow 按量（日顶 `LLM_DAILY_CAP` 默认 250 次调用）。搜索 API：四家免费额度拼起来用。
- **实际现金成本目前极低**，这既是优点也是约束——很多"扩容"建议在这个成本结构下不成立，提建议前先看 §6.6。

---

## 3. 产品演进史与已定方向

读这一节是为了**不要重新发散产品方向**。但"已定"不等于"正确"——你可以推翻，条件是拿出证据并说明推翻的是哪一条决策。

1. **v1（2026-06 初）**：岗位聚合看板。目标 = 跑通"抓取 → 入库 → 打分 → 看板 → 跳官网 → 反馈"最小闭环。
2. **v2 转型（2026-06-23）**：从"岗位聚合"转向"**个人机会雷达**"。核心 spec：`docs/superpowers/specs/2026-06-23-personal-opportunity-radar-pivot-design.md`，战略依据 `docs/产品转型方案-从岗位聚合到个人机会雷达.md`。要点：`/today` 升级为唯一主产品；匹配从"粗粒度加权"改为"**硬门 + 可解释排序**"；新鲜度作为进入今日机会的资格；把 source / crawler / workflow 等技术概念从普通用户界面移除。
3. **双层产品方案（PRD，2026-06-12）**：岗位检索是获客入口，职业洞察是护城河与付费点。`PRD.md` 是**唯一权威 PRD**。
4. **规模方向反转（2026-07-02）**：早期定"停止铺量、精 > 量"；上线后改为"**在保精度基础上逐步扩量**"，落地为每日自动定向扩源。⚠️ 这两条口径至今在文档里**并存**（`CLAUDE.md` 核心产品原则 §3），是我认为需要你重新裁决的地方之一。
5. **海外扩展（2026-07-02）**：放开 US / SG / Remote，台湾明确不抓。
6. **校招专区（2026-07~08）**、**洞察库 /insights（2026-09-04）**、**设计组件库（2026-09-04）** 相继上线。

**明确的产品边界（"不做"清单，违反等同实现错误）**：自动投递 / 登录企业招聘系统 / 绕验证码 / 第三方招聘平台 / 邮件微信推送 / Redis·Celery·K8s / 向量数据库 / 用 LLM 直接决定岗位排序。

---

## 4. 技术架构地图

### 4.1 数据流

```
公开企业官网 / ATS 租户门户
   │  ① 抓取：GitHub Actions cron → crawler/run.py → adapters/*.py（httpx 或 Playwright）
   ▼
crawler/normalizer.py（清洗 + 质量门 + canonical_jd_url + 地理/范围/届别派生）
   │  ② 写库：crawler/jobs_db.py（psycopg2，upsert 带 _PRESERVE_IF_EMPTY 保护）
   ▼
自建香港 PostgreSQL 17 · jobs 热表（455k 行 / 1.9 GB）
   ▲ ③ 治理：enrich（补正文）· liveness-sweep（逐岗探活判死）· dead-link-audit（浏览器 SPA）
   │        · purge-expired（删 expired）· collapse-bulk-duplicates（门店同质岗折叠）
   │  ④ 读：lib/jobs-store/{client,read,search,opportunities,write}.ts
   ▼
Next.js（Vercel hkg1）─ 硬门 + 可解释排序 ─→ /today /jobs /campus …
   │  ⑤ 反馈：job_actions（saved / ignored / applied / viewed）→ Supabase
   │  ⑥ 旁路：discovery（找新官方源）· gap_funnel（必投清单缺口漏斗）· insight_*（洞察供给）
   ▼
ops_runs 台账 + crawl_runs 日志 → ops-watchdog 规则 A~I → /admin/health
```

### 4.2 三个数据存储的分工（**边界很重要，别搞混**）

| 存储 | 装什么 | 谁读谁写 |
|---|---|---|
| **自建香港 PG** | `jobs` 热表（唯一） | app 走 `lib/jobs-store/`；爬虫走 `crawler/jobs_db.py`。两端都 gated：没配 `JOBS_DATABASE_URL` 时回退 Supabase（本地/回滚用），**但写入端失败绝不回退**（避免孤儿数据） |
| **Supabase** | Auth · `sources` · `crawl_runs` · `discovery_runs` · `ops_runs` · 用户表（`profiles`/`user_preferences`/`candidate_profiles`/`job_actions`/`events`）· 洞察 6 张表 | app + crawler |
| **浏览器 localStorage** | 只放每人自己的小便利（记住的 tab / 折叠态） | 前端 |

schema 权威：Supabase 看 `supabase/migrations/`（243 个，CI 自动 apply）；jobs 库看 `jobs-db/schema.sql`（改后跑 `gh workflow run jobs-db-migrate`）。

### 4.3 39 个 workflow 的职责分组

| 组 | workflow | 节奏 |
|---|---|---|
| 抓取 | `daily-crawl`（4 次/天）· `campus-crawl`（每 20 分钟）· `enrich-crawl` | 主供给 |
| 富化 | `enrich-backlog`（每 3h）· `enrich-backlog-browser` · `campus-cycle-enrich` | 补 JD 正文 |
| 探活/治理 | `liveness-sweep`（3 次/天）· `dead-link-audit` + `dead-link-audit-new` · `purge-expired` · `collapse-bulk-duplicates` | 死岗下架 |
| 扩源 | `auto-discover` / `-browser` / `-overseas` · `gap-funnel` · `ats-tenant-sync` · `harvest-beisen-routes` | 补供给 |
| 洞察 | `insight-enrich` · `insight-enrich-t3` · `insight-grade` · `insight-subjects` · `insight-annual-report` · `insight-staleness-sweep` | 第二价值层 |
| 观测 | `db-report` · `ops-watchdog` · `production-smoke` · `search-quota-probe` | 台账与告警 |
| 迁移/维护 | `migrate` · `jobs-db-migrate` · `jobs-db-data-migrate` · `maintenance-vacuum` · 各类 backfill | 按需 |

### 4.4 代码位置索引（省你 grep 的时间）

**爬虫**
- 入口与编排：`crawler/run.py`（685 行）
- ATS 通用层：`crawler/adapters/china_ats.py`（1,683 行，moka / beisen / company_spa 三合一，**覆盖 711 个源**）· `feishu.py`（122 源）· `workday.py` · `greenhouse.py` · `lever.py` · `avature.py` · `phenom.py`
- 大厂自建门户：`bytedance.py` `byd.py` `kuaishou.py` `abchina.py`（农行，浏览器 + 响应体 SM4 加密）· `icbc/ccb/spdb/bankcomm/cmcc.py`（国有大行，纯 httpx）
- 清洗与派生：`normalizer.py`（643）· `geo.py`（893，国别归属）· `sponsorship.py` · `china_keyword_expansion.py`
- 治理：`enrich.py`（1,132，逐岗探活 + 补正文）· `audit_dead_links.py` · `audit_stale_active.py` · `collapse_bulk_duplicates.py`
- 扩源：`discovery.py` · `auto_discover*.py` · `gap_census.py` · `gap_funnel.py`（1,305）· `entry_finder.py` · `platform_fingerprint.py`
- 洞察：`insight_backlog.py` · `insight_engine.py` · `search_router.py` · `official_edgar.py` · `official_cninfo.py`
- 观测：`ops_watchdog.py`（1,097，规则 A~I）· `ops_runs.py`

**应用**
- 岗位库边界：`lib/jobs-store/`（`client.ts` 连接池 / `search.ts` FTS / `read.ts` 864 行 / `opportunities.ts` 541 行两阶段召回 / `write.ts`）
- 匹配引擎：`lib/opportunities/`（硬门 `eligibility.ts` + 排序）· `lib/scoring.ts` · `lib/job-filter.ts` · `lib/match-total.ts`（计数诚实口径）
- 检索词库：`lib/china-keyword-expansion.js`（1,509 行，职能桶的唯一来源）
- 洞察：`lib/insight-*.ts`（verification / match / bundle / library / enrich-now）
- 必投清单口径：`lib/must-apply-list.{ts,json}` + `crawler/must_apply.py`（**两端共读同一份 JSON**）
- 鉴权：`lib/auth-claims.ts`（本地 JWT 验签 + 模块级 JWKS 缓存）· `middleware.ts` · `lib/apiAuth.ts`
- 管理看板：`app/admin/health/page.tsx`（1,634）+ `lib/admin-health.ts`（1,231）
- 设计系统：`components/ui/`（21 个原语）+ `lib/ui/`，展示页 `/design`

---

## 5. 已经验证过的结论（复现代价高，先读再质疑）

这些是**做过 live 验证并写进碑文**的判断，全部记在 `CLAUDE.md`（1,100 行，是本项目的唯一权威工程文档）。**不需要你重新论证，但欢迎你推翻——推翻的门槛是拿出反向证据，不是"我觉得"。**

1. **为什么必须自建爬虫**（`docs/superpowers/specs/2026-09-03-backend-review.md` §0）：国内 ATS 厂商 API 全部要企业逐家授权；国内数据商的数据来自第三方平台、没有官网原链接；Google for Jobs 在国内不可用。补充路线只有三条：国聘（已接）、搜索 API 找入口（已用）、用户贴链接众包（未做）。**这是最需要你复核的一条判断**——它决定了 66,598 行 Python 该不该存在。
2. **函数区必须锁 `hkg1`**：默认美东区让"建库连接"这一步就要 800~1400 ms，实测 `/api/jobs/stats` 曾 6.6 s。
3. **鉴权禁止在请求路径上调 `supabase.auth.getUser()`**：Supabase 在悉尼，实测 566 ms → 本地验签 0.7 ms。JWKS 缓存必须在**模块级**（每请求新建的 GoTrueClient 实例缓存永远为空）。
4. **失活校验绝不能放在用户点击路径上**：曾把实时探活放进 `/api/jobs/go`，点击要 5–8 s，已废弃。现在是"点击直跳 + 展示时异步探活 + 后台 sweep"三层。
5. **`canonicalize_jd_url` 归一逻辑活在三处**（`lib/canonical-url.js` / `crawler/normalizer.py` / jobs-db schema 的 SQL 函数），改一处必须三处字节级同改。
6. **list 重抓的 upsert 必须保住两个不变量**：`status` 走 `CASE` 黏住 `expired`（否则 sweep 判死的岗被刷回 active）；`_PRESERVE_IF_EMPTY`（summary 等空值不覆盖，否则每晚补的正文次日被抹）。
7. **hash 路由页面在浏览器巡检里必须 `reload()`**：同文档导航不重新渲染，会把上一个岗的"已下线"读成当前岗 → 误杀在招岗并次日永久删除。影响面 9,192 个 active 岗。
8. **"列表里没有" ≠ "已撤岗"**：除非先证明该列表返回全集。曾据此差点误删 460 个华为在招岗（逐个核验后 0 个撤岗）。
9. **归属准确性没有旁路**：国聘集团展开曾绕过核名门，84% 挂错公司（862 家 / 2,439 个岗）。
10. **"绿灯 ≠ 有产出"**：校招时间线链连续 7 天产出为 0 却一直报 success（搜索额度被贪心方吃光）。台账 `ops_runs` + watchdog 规则 A 就是为此而建。

---

## 6. 我自己怀疑的地方（请优先查这些）

以对抗式审查的姿态列出**我认为自己可能错的地方**。这不是让你附和，是给你一份有优先级的怀疑清单。

### 6.1 供需严重失衡 —— 我认为这是本项目最大的问题
三个月建了 45.5 万岗、1,351 个源、39 条自动化链、13 万行代码，换来的用户侧信号是：**80 注册 / 34 有过任何动作 / 12 次标记投递**。
- 我怀疑：产品长期在"供给侧军备竞赛"里自我强化——因为供给的进展可量化、可自动验证、令人满足，而需求侧的进展需要面对真实用户。
- 请你判断：**继续优化爬虫的边际价值是多少？** 如果答案是"很低"，那么本次审阅的正确产出可能是"停止扩量、把工程预算转向 X"，而不是"爬虫这样优化"。请直说。
- 反面也请考虑：是否存在"供给必须先到某个阈值，需求才可能被验证"的合理性？如果有，阈值是多少、现在到了吗？

### 6.2 探活吞吐追不上供给增长
09-03 时 7 天未探活占 24%，**今天 46.4%**。09-04 抬了列表上限（单源 600 → 8000）一天入库 6.99 万个岗，供给一次性跳了一个台阶，但探活链没有同步扩容。
- 后果：库里"active"的可信度在下降，而"有效在招"是首页对用户的承诺。
- 请查：探活的实际吞吐上限是多少？是被 GitHub Actions 并发限制、香港库 100 个连接位、还是对方站点限流卡住的？扩容路径是什么？
- ⚠️ 也请质疑我这条判读本身：46.4% 里有多少是"源本身还在天天抓到它"（`crawler/audit_stale_active.py` 的 A 桶，占 92%）——那种情况下岗位未必是死的，问题在抓全率而不在探活。**两种成因的处置完全相反。**

### 6.3 "精 > 量" 与 "保精度逐步扩量" 两条口径并存
`CLAUDE.md` 里 2026-06-15 的"停止铺量"和 2026-07-02 的"逐步扩量"同时挂着，靠一句"旧调降级为精度约束"缝合。实践上扩量赢了（源从 ~800 涨到 1,351）。请你裁决：在当前用户规模下，正确的口径是什么？

### 6.4 洞察层（第二价值层 / 设想中的付费点）是否成立
建了 6 张表、17,539 条洞察条目、1,313 家公司画像、6 条 cron 链、LLM 成本的 86% 都烧在这里。用户侧信号：**投稿 1 条、申诉 1 条**。
- 请判断：这一层现在是资产还是负债？如果是资产，怎么证明？如果是负债，砍到什么程度？
- 注意合规约束真实存在（不直接爬社区、去标识、分级、≥2 源共识、通知-删除申诉通道），这些不是过度设计，是这层能存在的前提。

### 6.5 44% 的源走 Playwright
591 个 playwright 源，单源串行 2–5 分钟。这是抓取成本、CI 时长、稳定性问题的主要来源（浏览器巡检也在这条路上）。
- 请查：这 591 个里有多少**其实存在 httpx 可达的接口**只是没人去挖？（本项目已有多次"以为要浏览器、其实有公开 JSON 接口"的先例：腾讯音乐 / 蚂蚁 / 米哈游 / 五家国有大行。）
- 反向也请查：有没有反过来的情况——http 源其实抓不全，应该升级？

### 6.6 单点与容量天花板
- 香港库：2C2G / 40GB，表+索引 1.9 GB 已超内存；`max_connections=100`，09-03 实测空闲时已占 58；**没有连接池代理**。
- 这台机器挂了，产品就没有岗位数据（有备份链路吗？请查 `backups/` 与 `docker-compose.jobs-db.yml` 的真实作用）。
- 请给出：在"现金成本必须极低"的约束下，可用性与容量的最优改法。**不要给出"上 K8s / 上 Redis / 上向量库"这类越过产品边界的建议**，除非你能论证边界本身错了。

### 6.7 测试形态：3,221 个用例，但几乎全是纯函数
JS 1,194 + Python 2,027 个用例，覆盖归一化、评分、地理、契约等纯函数。**端到端 / 集成 / 真实数据回归几乎没有**（`production-smoke` 是唯一的线上探针）。
- 我怀疑：这套测试对"adapter 悄悄坏掉""上游改版""数据口径漂移"这三类**本项目最常见的故障**几乎无保护——它们靠的是台账 + watchdog 事后发现。
- 请判断这个取舍对不对，以及有没有成本可控的补法。

### 6.8 文档与规则本身可能是负债
`CLAUDE.md` 1,100 行、`PRD.md` 393 行、30 份 spec、14 份 plan。规则大多是踩坑碑，价值真实；但：
- 我怀疑它已经超过"新接手者能读完"的长度，且存在过期风险（`CLAUDE.md` 自己记着一次事故：文档写"jobs 表已清空"，实际躺着 34,965 行两个半月没人发现）。
- ⚠️ **`HANDOFF.md` 是 2026-06-14 的历史快照，内容早已不成立（那时还没迁香港库），别拿它当现状。**
- 请给出：这套文档体系该怎么收敛，才能既保住碑文价值又不拖慢人。

### 6.9 我可能有的系统性偏差
- **偏好可自动验证的工作**：爬虫/治理链能自己写 SQL 验收，用户价值不能，于是精力向前者倾斜。
- **把"修好了一个坑"当成"产品前进了一步"**：碑文越多，越像在进步。
- **对规模有隐性执念**：明明写着"规模不是成功指标"，实际把源从 800 推到 1,351。
请在报告里点名你观察到的其他偏差，不用客气。

---

## 7. 问题清单

以下是我希望你明确回答的问题。**如果你认为某个问题问错了，请先纠正问题本身再回答。**

### L1 产品价值
1. "官方源 + 逐岗原链接"对中国求职者是不是一个**值得为之换掉现有习惯**的价值？还是一个"更干净但不够痛"的改良？
2. 45.5 万岗 : 12 次投递 —— 这个比例说明的是分发问题、匹配问题、还是需求本身不成立？给出你的判据。
3. 双层结构（岗位 + 洞察）是真护城河，还是两个各自没做透的半成品？
4. 如果只能保留一个模块，保哪个？为什么？
5. 现在最该做的**一件事**是什么？（只许答一件）

### L2 产品方案
6. `/today` 作为唯一主产品的转型执行到位了吗？（`/jobs` 还在、导航有 8 项，是否违背了转型 spec 的"收敛"意图）
7. "硬门 + 可解释排序"是不是比"打分排序"更对？现在的硬门会不会过严导致 today 队列经常空？（请用真实用户画像跑一遍验证）
8. 校招专区 / 洞察库 / 职业路径 三个模块，各自服务哪个用户决策？有没有该砍的？
9. 8 个导航项对一个 80 用户的产品是不是太多？
10. 缺什么？（明确指出一个未做但应该做的东西，并说明为什么它比现有 backlog 优先）

### L3 技术方案
11. **自建爬虫是不是最优路线？**请复核 §5.1 的四条论据，逐条给"成立 / 不成立 / 存疑"，并给出你能想到的**第五条路线**（如果有）。
12. GitHub Actions 当调度器（39 个 workflow / 30 个 cron）是巧妙利用免费额度，还是把编排复杂度推给了 YAML？在"1 人 + Agent"的团队规模下，正确形态是什么？
13. 三库分离（Supabase + 自建 PG + 无缓存层）的边界划得对吗？
14. 岗位检索用 Postgres bigram FTS + GIN，在 45 万行 / 2 GB 内存上还能撑多久？下一步是索引优化、读副本、还是换检索引擎？
15. 匹配引擎坚持"不用 LLM 决定排序、不用向量库"——这条边界现在还成立吗？
16. 可观测性（`ops_runs` 台账 + watchdog 规则 A~I + `/admin/health`）够不够？有没有**结构性看不见**的东西？

### L4 技术实现（爬虫为重点）
17. **`crawler/adapters/china_ats.py`（1,683 行，覆盖 711 个源 / 53%）** —— 读它。这个"三合一通用层"的抽象是对的吗？1,683 行是否已经该拆？
18. 抓取的**吞吐与稳定性**：翻页契约（`resolve_list_cap` / `RepetitionBrake` / `fetch_complete`）设计合理吗？失败处理（"一页拿不到就 raise 会扔掉整源"那类坑）还有没有同类残留？**请扫全部 69 个 adapter，不要抽样。**
19. **反爬与礼貌**：并发、退避、robots 遵守、UA 覆写、限流应对，现在是什么水平？有没有会给对方站点造成压力或让我们被封的地方？
20. **591 个 Playwright 源**：见 §6.5。给出降级到 httpx 的可行清单与预估收益。
21. **治理链正确性**：`enrich.py`（1,132 行）的逐岗判死信号，每个源都做到"双条件 / 宁可漏判不可错杀"了吗？扫全集。
22. 前端：`/today` 与 `/jobs` 的真实端到端耗时、SSR 载荷、连接占用。有没有比 09-03 报告更靠后的新问题？

---

## 8. 怎么取证

### 8.1 环境（都已验证可用）
- **网络是通的**：`git` / `gh` / `psql` / `curl` 都能出网。**不要以"沙箱连不上"为由跳过 live 验证。**
- **读香港岗位库**（只读查询请自由跑）：
  ```bash
  set -a; source .env.local; set +a
  psql "$JOBS_DATABASE_URL" -At -c "select count(*) from jobs where status='active'"
  ```
  部分环境需要给 Bash 调用加 `dangerouslyDisableSandbox`。**绝不打印连接串本身。**
- **读 Supabase**（REST，service role）：
  ```bash
  set -a; source .env.local; set +a
  curl -s -I "$SUPABASE_URL/rest/v1/sources?select=id" \
    -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
    -H "Prefer: count=exact" -H "Range: 0-0" | grep -i content-range
  ```
  ⚠️ **PostgREST 默认一次最多返回 1000 行**，不分页会数出"1,000 个源"这种一眼假的整数（真值 1,567）。这个坑在 2026-09-03 的审阅里造成过一条真实生产 bug（洞察链全线截断），**你自己取数时也会踩**。
- **CI 历史**：`gh run list --limit 100 --json name,conclusion,createdAt`；看某次失败 `gh run view <id> --log-failed`。
- **只读诊断 workflow**（安全，可以自己触发）：`gh workflow run db-report.yml`（status 分布 / 有效率 / 从未探活 / 分 adapter）。
- **跑测试**：
  ```bash
  node --test tests/*.test.js
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
  npm run build && npm run lint
  ```
  ⚠️ `npm run build` 本地会跳过 lint，而 Vercel 会跑 lint 且部分规则是 Error 级 —— 改了 `app/` `lib/` `components/` 就必须另跑 `npm run lint`。
- **跑单个源的爬虫**（不写库的干跑方式见 `crawler/run.py --help`）：
  ```bash
  cd crawler && set -a; source ../.env.local; set +a && python3 run.py --source <name>
  ```
- **看线上站**：https://job-radar-sigma.vercel.app 。测试账号 `test@jobradar.local` / `test123456`（登录后能看到 `/today` 等页面）。

### 8.2 红线（**违反即审阅作废**）
- ❌ 不读、不打印任何 `.env*` 的**内容**（`source` 进环境变量可以，`cat` / `grep` 不行）；输出里不得出现密钥 / token / 连接串 / 服务器 IP。
- ❌ 不做任何写操作：不 `update` / `delete` / `truncate` 生产数据，不改 `status`，不跑带 `--apply` 的治理脚本，不 `git push`，不 force push，不删分支。
- ❌ 仓库是 **PUBLIC**：报告里不得出现本机绝对路径（`/Users/…`）、服务器 IP / 主机名 / 端口、真人姓名 / 私人邮箱。用 `<项目根>` / 「见 `JOBS_DATABASE_URL` secret」 / 「创始人」替代。提交前跑 `npm run scan:sensitive`。
- ❌ 不要为了验证一个猜想去高频请求企业官网（对方会封，且不礼貌）。需要 live 探活时单发、限次、说明目的。
- ⚠️ 搜索 API 有每日免费额度且**全局共享**（洞察链 + 校招链共用一个池子），不要跑批量 live 检索把额度吃光。

---

## 9. 审阅陷阱（这个项目最容易得出错误结论的地方）

这一节是我三个月踩坑的浓缩。**你大概率会踩其中至少两个。**

### 9.1 "接口返 0 / 403 / 404" 不能证明"对方没开 / 不存在"
本项目栽过六次：B 站校招在另一条 API；阿里是 CSRF 不是登录墙；小米的开关是请求头不是参数；百度校招那一档叫 `GRADUATE` 不叫 `CAMPUS`；华为校招搬到了另一个站另一个网关；商汤/海底捞是**我们把 URL 前缀写死了**。
✅ 正确姿势：先渲染对方页面看它自己怎么说 → 再从**它自己发的请求**里找入口 → 参数值从它的 JS 里读，别猜。
✅ **点击只能证伪你走的那条路，证明不了全集**：要下"不存在"的结论，得捞出全站路由/页面清单逐个看。

### 9.2 "列表里没有" ≠ "已撤岗"
除非先证明该列表返回全集。差额有两种成因、处置完全相反：死岗堆积（该清）/ 列表接口只返子集（一清就是删在招岗）。判成因用 `crawler/audit_stale_active.py`（只读）。

### 9.3 "绿灯 ≠ 有产出"
CI 全绿、`status=success`、不抛异常，都不等于这条链在工作。判据是台账里的**产出数字**。反过来也成立：看到 `finished_at is null` 别急着说"崩了"，可能只是查询那一瞬间在飞（要带宽限期）。

### 9.4 聚合指标向好会洗掉分项回归
同一次改动常同时有两个相反方向的错误。实例：抬列表上限报"26 源多抓 3.1 万"，同一轮里 **20 个源少抓了 461 个岗**；补美国地名词典正向修对 12,525 个，反向把加拿大/波兰的岗**误判成美国** 2,079 个。
✅ 报数必须分项（A→B 多少、B→A 多少），**只报净值一律不算验证**。

### 9.5 存量坏数据 ≠ 现在还在坏
看到线上表里有一批坏行，**第一件事是 `select max(started_at)` 查最后一次发生是什么时候**。我差点把一个 9 天前就修好的洞又修一遍。

### 9.6 本地绿 ≠ 线上绿
macOS 是 LibreSSL + 有 IPv6，GitHub runner 是 OpenSSL 3 + 无 IPv6 出口。五家银行源本机全绿、上 CI 四个全 failed。类似地：`npm run build` 本地跳过 lint，Vercel 不跳。

### 9.7 一个源"零岗"先看 `sources.regions` 有没有 CN
`regions` 同时是后置过滤白名单，漏了 CN 会把抓回来的中国岗当场丢掉，而 `status` 照样 success、**没有任何失败信号**。全库 enabled 源里 **25 个不含 CN**（2026-09-06 实测；`CLAUDE.md` 记的 50 是 09-05 的数，之后修掉了一批 —— 这本身就是「文档会过期、拿它决策前先验一下」的活例子）。排查顺序：先看 regions，再看 adapter，最后才去找入口。

### 9.8 PostgREST 1000 行截断
见 §8.1。你自己取数会踩。

### 9.9 别把"我们配错了"说成"对方关了"
报错信息本身（如 `portal closed`）往往是一个**未经证实的结论**，不是观测。

### 9.10 不可逆操作前，核验样本量必须匹配影响面
要清 447 行就核验 447 行，抽查 2 个不算数。这条对你的**建议**同样成立：一条会导致批量改数据的建议，必须附全集核验方案。

---

## 10. 附录

### 10.1 文档权威顺序
用户当前指令 > `CLAUDE.md`（唯一权威工程文档，1,100 行） > `PRD.md`（唯一权威 PRD） > 各 spec / plan > `README.md` > 其它。
代码与文档冲突时**以代码和线上数据为准**。

### 10.2 已知过期 / 需要小心的文档
- `HANDOFF.md`（2026-06-14）：数据库空间危机的历史快照，**当时还没迁香港库**，内容基本全部失效。
- `AGENTS.md` / `AGENTS.md.bak-20260807`：与 `CLAUDE.md` 有重叠，冲突以 `CLAUDE.md` 为准。
- `docs/superpowers/plans/2026-06-14-jobs-database-refactor.md`：Phase 1 已于 2026-06-19 完成，文中"待办"多已落地。
- `CLAUDE.md` 里"2026-06-15 停止铺量"与"2026-07-02 逐步扩量"两条口径并存（见 §6.3）。

### 10.3 建议的阅读顺序（约 2 小时能建立完整认知）
1. 本文（你在读）
2. `CLAUDE.md` —— 通读，这是全项目最高密度的信息源
3. `PRD.md` §0–§4、§11–§14
4. `docs/superpowers/specs/2026-06-23-personal-opportunity-radar-pivot-design.md` §0–§1（产品转型）
5. `docs/superpowers/specs/2026-09-03-backend-review.md` —— **上一次后端审阅的完整报告，你的工作要在它之上，不是重复它**。请顺带核查它的 M1~M4 是否真的修了
6. 代码：`crawler/run.py` → `crawler/adapters/china_ats.py` → `crawler/enrich.py` → `lib/jobs-store/opportunities.ts` → `lib/opportunities/eligibility.ts`
7. 线上：`/today` `/jobs` `/admin/health`

### 10.4 术语表
| 词 | 意思 |
|---|---|
| 薄卡 | 有岗位但没 JD 正文（<60 字）的记录，只算"在库"不算"有效在招" |
| 探活 / sweep | 逐岗打详情接口判断是否已撤岗；`active → expired` |
| 富化 / enrich | 逐岗抓详情补 JD 正文等字段 |
| 必投清单 | 11 行业 × 各 30 家目标公司，北极星指标"必投清单健康覆盖"的口径 |
| 缺口漏斗 | 必投清单里库中没有的公司 → 搜索找入口 → 平台指纹 → 真抓验收才入库 |
| 三桶 / recruitmentCategory | 社招 / 校招 / 实习，前后端同口径 |
| 硬门 | 匹配里的一票否决条件（城市不符 / 命中排除词等），不参与加权 |
| 台账 / ops_runs | 每条后台链每天写一行的产出记录，watchdog 的数据源 |
| 碑 | `CLAUDE.md` 里"现象 → 根因 → 防法"三件套的踩坑记录 |

---

## 11. 最后一句

我在这个项目上连续干了三个月，**必然存在我看不见的东西**。我最希望你做的不是确认我做对了什么，而是告诉我：

> **哪一件我一直在做的事，其实不值得做。**

请直说，不用照顾我的判断。
