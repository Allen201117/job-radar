# 校招专区重构：物化「职能」结构字段 + 展开公司看全部岗位

> 状态：设计稿（待创始人 review）｜日期 2026-09-15｜分支 `claude/campus-recruitment-tags-redesign-78e54c`
> 前置：止血补丁已上线（commit `061b1ae`，见文末「背景」）。本文是止血之后的「重构」项目。

## 1. 目标与非目标

**创始人诉求（原话）**：
- ②「重新设计标签，用户常关注的那些标签固定下来，作为结构性字段」——多选后**只圈了「职能」**。
- ③「点开每一家公司，岗位展示都不全，用户有看到所有符合筛选条件岗位的诉求」。

**一句话洞察**：②③是同一个根问题。「职能」（产品/研发/设计…）现在**不是数据库字段**，是每次渲染时从
JD 正文临时算出来的。这个「临时算」——把几万条岗位的正文拖回函数分类——又重又慢、撑不过超时，正是
①「全部数据待更新」快照卡死的病根；也因为它不是字段，③按职能筛全部岗位时每翻一页都要重拖正文，
所以现在只能截前 200 个。**把职能物化成带索引的字段（写入时算好），①的病根被彻底拔掉、③也能便宜地翻完全部。**

**目标**：
1. 在 `jobs` 表物化 `job_function` 列（写入时计算、回填存量、建索引）。
2. 校招看板读路径改读该列，**不再在渲染期拉正文分类** → 重快照变轻 → 卡死病根消除。
3. 展开某家公司时支持**分页看完全部**符合筛选条件的岗位（去掉「前 200」硬顶）。

**非目标（本轮明确不做）**：
- 不物化 届别 / 批次 / 截止日期 / 新鲜度（创始人本轮未圈；届别抽取纠错、批次结构化留待后续单独立项）。
- 不动 `/jobs` 主搜索的冷路径（同样能受益于 `job_function` 列，但属另一影响面，本轮只顺带留出接口、不切它的读）。
- 不删止血引入的 `getCampusFreshStats`（保留为廉价安全网，见 §7）。

## 2. 现状（事实，均已在代码/live 核对）

- 权威分类器：`lib/china-keyword-expansion.js` 的 `classifyJobFunction(job)`。**标题权威优先**：标题能判出干净职能
  就用标题（不看 job_type/summary，避免被部门名带偏）；**只有标题落到「其他/职能」这类歧义/招聘活动标签时**，
  才退回看 `title + summary` 精修（`_classifyFunctionText`，另有 `BODY_FALLBACK_BLOCKED` 兜底）。桶值 17 个：
  产品/项目管理/设计/数据/研发/生产制造/建筑工程/运营/市场/医疗健康/金融业务/教育培训/客服服务/销售/供应链/职能/其他。
- 校招看板读路径（`lib/jobs-store/read.ts` `getCampusZone` + `hydrateSummariesForFunctionFacet`）：
  第一阶段不拉正文；对「标题判成 其他/职能」的行**第二阶段按需补 `left(summary,1000)`** 再算职能分面。
  2026-09-09 live 对拍：需要正文的 34,578 行里 `left(summary,1000)` 与全文判 **0 差异**。
- 展开单家（`getCampusCompanyJobs` + `/api/campus-zone/jobs`）：`MAX_JOBS=200`，服务端用**完整 summary** 算 `fn` 随行返回；
  分段取正文，收满 200 停。
- **已有可复用机件**（这让本项目低风险）：
  - JS 桥 `scripts/classify-job-function.js`（stdin→stdout 批量）——⚠️ 但它**只喂 title**（见 §4 关键决策）。
  - 物化先例 `recruitment_category`：`jobs-db/schema.sql` 加列 + 回填脚本 `scripts/backfill-recruitment-category.js`
    （`--check` 只读对拍 / `--apply` 只填 NULL / `--apply --all` 全重算，批量 2000）+ 写入端 `crawler/recruitment_classify.py`
    （`annotate` 只给 NULL 行补）+ 读取端「有列用列、NULL 兜底现算」（`campusAdmission`）。**本项目逐一镜像它。**

## 3. 关键决策：物化时**必须带 summary 算**（否则回归职能筛选精度）

⚠️ 这是全项目最容易踩错、且创始人的选择不覆盖的技术分叉，必须写死：

- 现有桥 `classify-job-function.js` **刻意只喂 title**（注释：summary 兜底全局约 290 个误判；派生层做分布统计，
  宁可多判「其他」）。**但那是「全库分布统计」的用途**，可接受更多「其他」。
- 校招看板要的是**准确的职能筛选**。若用 title-only 物化，那 ~34,578 个「标题歧义、靠 summary 精修」的行会退回「其他/职能」
  → **校招职能筛选比现在更差**，直接违背「让职能标签可靠」的目标。
- 因此：**物化列的计算口径 = `classifyJobFunction({ title, job_type, summary })`（带 summary），与当前校招读路径逐字相同。**
  写入/回填时我们**本来就有 summary**（crawler 刚抓到、存量行库里就有），带上零额外成本。
- 落地：新增/扩展一个「带 summary」的桥（不复用 title-only 的 `classify-job-function.js`，避免把两种用途搞混；
  可在 `classify-recruitment.js` 同一次 node 调用里顺便返回 job_function，省一次进程启动）。
- **验收硬门**：回填后必须 live 对拍「列值 == 当前校招读路径现算值」，**目标 0 差异**，再切读（镜像 recruitment_category 的做法）。

## 4. 设计

### 4.1 Schema（`jobs-db/schema.sql`，幂等；`gh workflow run jobs-db-migrate` 应用）
```sql
alter table jobs add column if not exists job_function text;   -- 值域 = JOB_FUNCTION_BUCKETS，NULL=「还没算」
-- 校招/实习筛选走它 → 部分索引（只覆盖专区关心的行，控体积）
create index if not exists idx_jobs_active_job_function
  on jobs (job_function) where status = 'active';
```
- `NULL = 还没算`，不等于「其他」。读路径遇 NULL 一律走原有兜底现算（回填期与分类失败时新岗不从筛选里消失）。

### 4.2 写入路径（两处，与 summary 同源同口径）
- `crawler/jobs_db.py`：upsert 时计算并写 `job_function`。复用 `recruitment_classify.py` 的跨进程 JS 调用，
  **在同一次 node 调用里同时拿 category 与 function**（带 summary）。分类失败 fail-open（写 NULL，不阻断抓取）。
- `lib/jobs-store/write.ts`：app 写入端同口径（in-process 直接调 `classifyJobFunction`）。
- ⚠️ **preserve-if-empty 不变量**：list 重抓时 summary 可能回 NULL（moka 系），upsert 用 `COALESCE` 保留旧 summary。
  `job_function` 必须**从 COALESCE 之后的最终 summary 重算**，绝不能用「这次没带 summary」去把一个先前带 summary
  算好的职能覆盖成「其他」。（同 `_PRESERVE_IF_EMPTY` 家族的坑，见 CLAUDE.md。）
- ⚠️ **职能跟着 summary 走**：summary 被 enrich 补上时（`enrich.py` / moka summary backfill），要一并重算 job_function
  （否则 moka 岗永远停在 title-only 的「其他」）。

### 4.3 陈旧治理（镜像 `jobs_guard_recruitment_class`）
- 触发器：当 `title` / `job_type` / `summary` 变化到影响分类时，把 `job_function` 置 NULL（下一轮 enrich/backfill 重算）。
  具体形态照抄 recruitment_category 的 guard，保证「分类依据变了、列不会留旧值」。

### 4.4 回填（一次性，存量 ~39 万 active 行）
- 新增 `scripts/backfill-job-function.js`，**结构逐条镜像** `backfill-recruitment-category.js`：
  - `--check`：只读对拍，报告「列值 vs 现算」差异，绝不写库。
  - `--apply`：只填 `job_function IS NULL` 的行（可续跑）。
  - `--apply --all`：全重算覆盖。`--batch`（默认 2000）、`--limit`。
  - 只 UPDATE `job_function` 一列，**不碰** status / enrich_checked_at / last_seen_at（jobs upsert 不变量）。
  - 读列 `id, title, job_type, summary`（带 summary，见 §3）。
- 配套 workflow（或手动跑）。39 万行 × 批 2000 ≈ 200 批；分类是 JS 不是纯 SQL，必须走脚本（不能塞进迁移的单条 UPDATE）。

### 4.5 读路径切换（回填 + 对拍 0 差异**之后**才切）
- `getCampusZone`：删掉 `hydrateSummariesForFunctionFacet` 与第一阶段的 summary CASE，直接 `select ... j.job_function`；
  `buildCampusFacets` 用列值（NULL 才现算兜底）。→ 重快照不再拉正文 → **卡死病根消除**，分面不再滞后。
- `getCampusCompanyJobs`：职能筛选下推成 `job_function = $x`（走 §4.1 索引），不再逐页拉正文分类。
- `/jobs` 冷路径：本轮**不切读**，但列已就位，后续可单独切（记一笔，别顺手改，避免影响面外溢）。

### 4.6 ③ 展开公司看全部（分页）
- `getCampusCompanyJobs` 改**游标分页**：排序键（deadline asc nulls last, then first_seen desc）稳定游标 +
  `job_function`/city/education/grad_class 全部下推 SQL（都是列）。返回 `{ jobs, nextCursor, total }`。
- `/api/campus-zone/jobs`：加 `cursor` / `limit` 参数（`MAX_JOBS=200` 降级为默认页大小）。
- `app/campus/campus-client.tsx` 展开区：**「加载更多」**（与 `/jobs` 页「加载更多（还有 N 个）」一致的既有交互模式，
  不引入无限滚动），去掉「按临近截止优先展示前 200 个」的截断文案，改成「共 N 个 · 已加载 M 个」。
- 归属/准入门口径继续与 getCampusZone 逐字一致（CLAUDE.md「归属规则三处必须一致」——本轮又多一处调用，仍钉死；
  止血已把纯聚合抽进 `lib/campus-stats.ts`，分页取数应复用同一份归属规则，不要再抄第五份）。

## 5. 分期（可分两个 PR 上线，各自独立可回滚）
- **Phase A｜物化 + 切读**：schema 列 + 写入两处 + 触发器 + 回填脚本 + `--check` 0 差异 + 切校招读路径。
  产出：卡死病根消除、职能筛选可靠、分面不再滞后。**这是重构的主体价值。**
- **Phase B｜全量分页**：`getCampusCompanyJobs` 游标分页 + API + 展开区「加载更多」。依赖 Phase A 的列才便宜。

## 6. 风险与对策
| 风险 | 对策 |
|---|---|
| title-only 物化回归职能精度 | §3：物化带 summary + 回填后 live 对拍 0 差异再切读 |
| upsert 用无 summary 的重算覆盖好值 | §4.2 从 COALESCE 后最终值重算；纳入 preserve 家族；契约测试钉死 |
| 39 万行回填成本/中断 | 批量 2000、可续跑（WHERE job_function IS NULL）、只写一列；镜像已跑通的 category 回填 |
| 索引体积 | 部分索引 `where status='active'`（只覆盖专区关心的行） |
| 切读后与现状不一致 | 切前 `--check` 全量对拍；Phase A/B 分开上，各自可回滚 |
| moka 岗初写无 summary → 停在「其他」 | §4.2「职能跟着 summary 走」：enrich/summary-backfill 时重算 |

## 7. 与止血补丁的关系
- 止血引入的 `getCampusFreshStats`（计数+新鲜度轻查询绕开快照）**保留**：Phase A 后重快照虽变轻、不易卡死，
  但轻查询仍是「计数/徽章永远现算」的廉价安全网，成本可忽略。不删。

## 8. 测试
- 单元：`classifyJobFunction` 已有测试；新增 写入端「带 summary 计算 + preserve 不覆盖」测试、
  读取端「有列用列 / NULL 兜底现算」测试、`getCampusCompanyJobs` 游标分页测试。
- 契约：归属一致性（已有）、`job_function` 列口径与现算一致（新增，仿 campus-zone-prefilter）。
- Live：回填 `--check` 全量 0 差异；切读前后卡面职能分面逐公司对拍不变。

## 背景：止血补丁（已上线，commit 061b1ae）
- 现象：/campus 全部卡「数据待更新」，而 jobs.last_seen_at=当天、campus-crawl 健康。
- 根因：整块看板打包进一个 `unstable_cache` 快照，重活偶发跑不完/报错时 Next 永远服务旧快照且不报错 →
  快照里计数与 last_seen 冻在 3 天前 → 每卡算「距今>72h」→ 全判 stale。
- 改法：计数+新鲜度徽章改用轻量分组查询每请求现算（`getCampusFreshStats`），绕开重快照；分面/时间线继续走缓存。
