# 交接：/today 召回改「两阶段检索」——同时要准确性和速度

- 日期：2026-07-31
- 状态：✅ **已实施**，见文末「第 9 节 实施结果」。
  ⚠️ 第 4 节写的方案方向**有两处被实测推翻**（`ts_rank` 不可用、「方向×城市」不能单独成层），
  第 3 节的瓶颈定位仍然成立。以第 9 节为准。
- 前置文档：`docs/superpowers/specs/2026-07-30-latency-region-consolidation-design.md`（区域收拢 + 本地验签，已上线）

---

## 0. 创始人的硬约束（不要试图绕过）

> 「筛选的准确性和页面加载的速度，它们两个不是对冲的两个因素。因此我两个都要。」
> 「必要的时候，我也同意你重构一下当前的筛选器机制，或者页面加载的逻辑机制。」

上一轮我两次提出「拿精度换速度」的选项（调小召回上限 / 收窄排除词范围），**都被否**。
创始人的判断是对的——见第 3 节：现在这套设计**同时又慢又漏**，不是取舍问题，是设计缺陷。

授权范围：**允许重构筛选器机制与页面加载机制**。不允许的是让筛选结果变差。

---

## 1. 已上线、可放心依赖的东西（本轮成果）

| commit | 内容 | 实测 |
|---|---|---|
| `49c42b5` | 函数区迁 `hkg1`（`vercel.json`）+ 鉴权改本地 JWT 验签（`lib/auth-claims.ts`） | 鉴权 566.7ms → **0.7ms** |
| `2cca40d` | 补齐 11 个内联 `getUser()` 的接口 + 落地页 + `getProfile` | 全仓库请求路径上已无网络 `getUser()` |
| `e8a8c1e` | 校招专区不再下发 JD 正文（服务端算职能标签 + `/api/jobs/by-ids` 按需取详情） | HTML **16,659KB → 1,392KB**，7.2s → 5.1s，筛选精度零损失 |
| `759d451` | 搜索扫描候选加进程内缓存 + 并发去重（`lib/jobs-store/search.ts`） | `/api/jobs/search` 命中时 17s → **11.4s** |
| `34a8cba` | `/today` 的 source 元信息改按 id 只取召回涉及的（1121 行 → 395 行、2 次串行往返 → 1 次） | 严格更优，但**没动到总时长**（见第 2 节） |
| `26c87af` | **`/today` 分阶段耗时埋点**（`?__timing=1`） | 靠它一次问出了瓶颈 |

---

## 2. ⚠️ 已被实测证伪的三个假设（别再走一遍）

| 假设 | 做法 | 线上结果 |
|---|---|---|
| sources 全表拉取贵 | 加进程内缓存 | 6.59s → 6.56s ❌ |
| sources 行数太多 | 改按 id 只取 395 个 | 6.17s → 6.51s（对照组同期 ±6%）❌ |
| 4000 岗逐岗 JS 计算贵 | 本地纯 CPU 实测 | **430ms** ❌ 不是它 |

**犯错根因（重要，别重蹈）**：拿**本机经代理**量到的 I/O 数字去外推线上瓶颈**必然错**。
本机链路要绕美国，会把 I/O 放大数倍、把 CPU 相对缩小。
- ✅ 可以本地量并直接用的：**纯 CPU 计时**（纯函数、不碰网络）。
- ❌ 不能外推的：任何跨网络的耗时。要量就上线上埋点。

---

## 3. 真正的瓶颈（线上埋点实测，3 发样本）

```
召回（香港库）                 2432 / 2293 / 2397 ms   ← 占 feed 端到端约 80%
shell 前 4 条 Supabase(悉尼)    194 ~ 1034 ms
source 元信息(悉尼, 按 id)        0 ~  461 ms
逐岗 JS 计算（1500 候选）        577 ~  623 ms
分区                               1 ~    2 ms
展示行回填（香港库, 10 条）        4 ~    5 ms
──────────────────────────────────────────
feed 端到端                    2875 ~ 3475 ms
页面函数内总计                 3072 ~ 4366 ms
（外部观测 TTFB 2.4~4.0s，全部完成 6.2~9.0s）
```

### 3.1 召回 2.3s 的拆解

| | 耗时 | 依据 |
|---|---|---|
| DB 执行（含排除词） | **640 ms** | psql `EXPLAIN ANALYZE` 热态实测 |
| └ 其中排除词 `LIKE ANY` 贡献 | +378 ms | 不带排除词同查询 262ms |
| 传输 + node-pg 解析 | **~1650 ms** | 2300 − 640；1500 行 × 约 700B ≈ 1MB |

排除词那条 SQL 之所以贵——它逐行拼 6 个字段（含 JD 正文）再转小写做 `LIKE ANY`，用不上任何索引：
```sql
not (lower(concat_ws(' ', title, company, location, job_type, summary, salary_text)) like any($n::text[]))
```

### 3.2 🔴 核心发现：现在的设计**同时又慢又漏**

`lib/jobs-store/opportunities.ts:172`：
```sql
order by first_seen_at desc limit 1500
```

**召回是按「最新」排序取 1500 条，不是按「最匹配」。**

⇒ 一个与用户完美匹配、但排在第 1501 新的岗位，**今天根本进不了候选池**，用户永远看不到。
这不是理论风险：库里 `status='active'` 有 **317,501** 条，14 天窗 + FTS 命中后仍远超 1500。

所以「准确性 vs 速度」根本不是对冲——**当前实现在这两项上都不达标**。

---

## 4. 方案方向：两阶段检索（retrieve → rerank）

这是搜索工程的标准模式（Elasticsearch 的 `rescore`、Vespa 的 two-phase ranking 同构）：

| | 阶段一（库里做，走索引，便宜） | 阶段二（应用里做，精确，贵） |
|---|---|---|
| **标准做法** | 按**相关度**排序取 top-K，K 小 | 对这 K 条跑完整打分/硬门 |
| **我们现在** | 按**最新**排序取 1500 ❌ | 对 1500 条跑完整打分 |

我们违反的正是「阶段一必须按相关度、K 要小」这一条。改对之后**两个指标同时改善**：
- **更快**：K 从 1500 降到 ~300 → 传输与解析降到约 1/5（那是当前 1.65s 的大头）
- **更准**：不再按「新」截断 → 老的但高度匹配的岗位能进候选池

### 4.1 待验证的关键实验（下一个 session 的第一步）

Postgres 自带 `ts_rank`，schema 已有 `search_doc` tsvector + GIN 索引（见 `jobs-db/schema.sql`）。
**必须先量清楚 `ts_rank` 排序的代价**（它是 post-filter 排序，Postgres 要对所有命中行算分再排）：

```bash
cd <项目根>
set -a; source .env.local; set +a
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
COLS="id, source_id, company, title, location, job_scope, left(btrim(summary),300) as summary, jd_url, posted_at, deadline, first_seen_at, last_seen_at, enrich_checked_at, status, education"
EXCL="not (lower(concat_ws(' ',title,company,location,job_type,summary,salary_text)) like any(array['%外包%','%驻场%']))"
BASE="status='active' and last_seen_at >= now() - interval '14 days' and summary is not null and char_length(btrim(summary)) >= 60 and $EXCL"
Q="to_tsquery('simple','产品 | 运营 | 数据')"

# A 现状：按最新取 1500
psql "$JOBS_DATABASE_URL" -X -q -c "EXPLAIN (ANALYZE,TIMING ON) select $COLS from jobs where $BASE and search_doc @@ $Q order by first_seen_at desc limit 1500;"
# B 方案：按 ts_rank 相关度取 300
psql "$JOBS_DATABASE_URL" -X -q -c "EXPLAIN (ANALYZE,TIMING ON) select $COLS, ts_rank(search_doc,$Q) r from jobs where $BASE and search_doc @@ $Q order by ts_rank(search_doc,$Q) desc, first_seen_at desc limit 300;"
# C 该 tsquery 一共命中多少行（决定 ts_rank 要算多少次）
psql "$JOBS_DATABASE_URL" -X -q -t -c "select count(*) from jobs where $BASE and search_doc @@ $Q;"
```

**判读**：
- 若 B 的 DB 时间没有比 A 明显变差 → 直接采用，收益是「传输降 5 倍 + 不再漏老岗」。
- 若 B 因命中行太多而变慢 → 退一步用**混合召回**：`(按相关度 top-N) UNION (按最新 top-M)` 各取一半再去重，仍比现状准，且 K 可控。
- 无论走哪条，**阶段二（JS 打分/硬门）逻辑一行不用改**——这是这个方案风险低的原因。

### 4.2 K 取多少要有依据，不能拍脑袋
线上已有埋点可直接读 `candidates` 与 `displayed`（实测 1500 → 展示 10）。
建议做法：临时把 `feed.timing` 里加上 `counts.filtered` 的分项（inactive/mismatch/low_score/thin），
看清 1500 条是被哪一类硬门刷掉的——**能进 SQL 的硬门就该下推到 SQL**，那比调 K 更治本。

---

## 5. 🚧 已查明的约束（改之前必读，每条都验证过）

| 约束 | 依据 | 后果 |
|---|---|---|
| `SUMMARY_TRUNC` 不能降到 200 以下 | `lib/opportunities/eligibility.ts:182` 用「≥200 字」判长文 | 降了会静默改坏 `summaryLong` 判定 |
| `jd_url` 不能从 `RECALL_COLUMNS` 砍 | `lib/opportunities/hydration.ts:12` 是 `if (full)`；回填没命中就保留召回行 | 卡片会没有跳转链接 |
| 排除词必须留在 SQL | SQL 比对**完整** summary，而召回行只有 300 字 | 挪到 JS 会漏掉只在正文深处出现的排除词 |
| 召回列可砍的只有 `country_code` / `job_type` / `salary_text` | 第 5 节字段审计 | 仅约 7%，不值得单独做 |
| 改检索 SQL 必须 live 验覆盖率 | 前例：Codex 把 city 移出 tsquery → 覆盖 28678 暴跌到 1818 | 静默改坏筛选 |
| 不要并行取候选页 | `lib/jobs-store/search.ts:23-32` 有两次失败实录 | 池 max=5，超了 8s 抛 connect timeout；香港库 2vCPU，并行更慢 |
| `npm run lint` 必跑 | 本地 build 跳过 lint，Vercel 会跑且 Error 级直接挂部署 | 有连挂 7 次的先例 |

### 字段审计结论（回填前真正被消费的）
- `eligibility.ts`：company, education, first_seen_at, job_scope, last_seen_at, location, status, summary, title
- `signals.ts`：deadline, enrich_checked_at, posted_at, status
- `grouping.ts`：company, id, location, title
- `service.ts` 循环内：id, source_id, deadline, first_seen_at, last_seen_at, enrich_checked_at, posted_at

---

## 6. 工具与环境（照抄即可，省下摸索时间）

### 6.1 线上分阶段埋点（已常驻）
`/today?__timing=1` 会渲染隐藏的 `<script type="application/json" id="jr-timing">`，
含 `user_rows_ms` / `server_total_ms` / `feed.{recall,critical,parallel,sourcemeta,compute,group,hydrate,total,candidates,displayed}`。
**普通用户拿不到**（必须显式加参数），内容只有毫秒数与条数、无用户信息。
采集常开（`performance.now()` 成本可忽略），实现见 `lib/opportunities/service.ts` + `app/today/page.tsx` 的 `TimingProbe`。

### 6.2 连香港库
```bash
cd <项目根>
set -a; source .env.local; set +a
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
psql "$JOBS_DATABASE_URL" -X -q -c "…"
```
需 `dangerouslyDisableSandbox`。**绝不打印密钥**。DDL 走 `gh workflow run jobs-db-migrate`。
⚠️ 本地缺 `JOBS_DATABASE_SSL_CA`（只 CI 有）→ 走 `lib/jobs-store/client.ts` 的应用代码路径本地**跑不了**，只能用 psql。

### 6.3 带登录态测线上页面
```bash
set -a; source .env.local; set +a
REF=$(node -e "console.log(new URL(process.env.NEXT_PUBLIC_SUPABASE_URL).hostname.split('.')[0])")
S=$(curl -s -X POST "${NEXT_PUBLIC_SUPABASE_URL%/}/auth/v1/token?grant_type=password" \
  -H "apikey: $NEXT_PUBLIC_SUPABASE_ANON_KEY" -H "Content-Type: application/json" \
  -d '{"email":"test@jobradar.local","password":"test123456"}')
node -e '
const fs=require("fs");const s=JSON.parse(process.argv[1]);const ref=process.argv[2];
const b=(v)=>Buffer.from(v,"utf8").toString("base64").replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
const val="base64-"+b(JSON.stringify(s));const K=`sb-${ref}-auth-token`,M=3180;const L=["# Netscape HTTP Cookie File"];
const a=(n,v)=>L.push(["job-radar-sigma.vercel.app","FALSE","/","TRUE","0",n,v].join("\t"));
if(val.length<=M)a(K,val);else for(let i=0,k=0;i<val.length;i+=M,k++)a(`${K}.${k}`,val.slice(i,i+M));
fs.writeFileSync("/tmp/jc.txt",L.join("\n")+"\n");' "$S" "$REF"
curl -s -b /tmp/jc.txt "https://job-radar-sigma.vercel.app/today?__timing=1"
```

### 6.4 ⚠️ 测量方法论：必须带对照组
本机网络在整个会话里剧烈波动（同一页面同一天可从 2.9s 漂到 8.9s）。
**跨时段直接对比数字会得出完全错误的结论**（本轮踩过：以为改坏了，其实是网络）。
正确做法：同一时间窗内**同时测「改过的页面」和「没改过的页面」**（如 `/saved`、`/path`），
看实验组相对对照组的变化。curl 一律带 `--retry 4 --retry-all-errors`，取中位数，样本 ≥7。

### 6.5 本地测纯 CPU（可信，可直接用）
Node 24 能直接跑 TS。需要两个垫片：
- `server-only`：`ln -s next/dist/compiled/server-only node_modules/server-only`，并加 `--conditions react-server`
- 打包器风格导入（省略扩展名 + `@/` 别名）：用 `registerHooks` 写个 resolve 钩子（本轮用过，见 git 历史或重写 20 行）

---

## 7. 并行 session 注意（本轮真踩了）

另一个 session 同期在改校招专区，**git 文本合并成功但语义冲突**，合出来的 main 编译不过
（`campus-client.tsx` 的 effect 仍引用被对方移除的 `expanded`），Vercel 部署 failure。

⇒ 每次 push 前：`git fetch origin && git merge origin/main` → **重跑 build + lint** → 再 push。
⇒ push 后**必须**用 `gh api repos/Allen201117/job-radar/deployments` + `/statuses` 确认部署 success，别等用户发现。

---

## 8. 验收标准

1. `/today?__timing=1` 里 `feed.recall` 从 ~2300ms 明显下降；`feed.total` 与页面总时长同步下降。
2. **筛选准确性不倒退，且可证明**：
   - 用同一批用户画像，对比改前/改后的 `sections` 岗位集合；
   - 必须能给出「改后新捞到的老岗位」示例（证明不再按新截断）；
   - 覆盖率 live 验证（对照 `job-radar-filter-design-overhaul` 的教训）。
3. 四件套全绿：`node --test tests/*.test.js` / crawler unittest / `npm run build` / **`npm run lint`**。
4. 部署 success + 带对照组的线上实测。

---

## 9. 实施结果（2026-07-31 完成）

### 9.1 最终落地的方案（与第 4 节的原方案有出入，以此为准）

`lib/jobs-store/opportunities.ts` 的 `buildRecallSql`：**三层加权轮转召回，一条 SQL、一次跨区往返**。

| 层 | 命中条件 | 权重 | 层内排序 |
|---|---|---|---|
| `role` | 方向 tsquery（词库扩展） | 5 | **城市命中 → 城市未知 → 其余**，再按 `first_seen_at desc` |
| `company` | 目标公司 tsquery | 2 | 同上 |
| `cityNew` | 目标城市 tsquery ∧ 近 7 天新增 | 3 | `first_seen_at desc` |

取用顺序 = `层内序号 ÷ 层权重` 升序，取满 `RECALL_BUDGET=900` 为止。

三个关键决定：

1. **加权轮转，不是每层一个固定 cap。** 固定 cap 下某层取不满就白白浪费预算——实测有画像因此只召回
   349 行、展示岗位从 25 掉到 15。轮转让取空的层把名额自动让给其他层，总量恒等于 `min(budget, 可用量)`。
2. **层内先取城市命中的行。** `checkEligibility` 里 location mismatch 是**硬拒**，用户填了目标城市时，
   不在目标城市的岗无论方向多准都进不了看板 —— 先取它们纯属浪费名额。城市未知（location 为空）是
   degraded 放行，所以排在中间。城市 tsquery 只有几个词、逐行算很便宜。
3. **方向 tsquery 全 SQL 只出现一次。** 它是 stage-1 最贵的东西（GIN 扫一次 0.1~3.5s，与子句数正相关）。

另外两处顺带修掉的浪费：
- `roleTsquery` **子句去重 + 扩展预算 120**：多个关键词常映射到同一个词库组，不去重会把
  `(数据 & 据分 & 分析)` 原样重复三四遍。超预算的词只保留原词、不再展开词库——**一个用户词都不丢**。
  实测：某画像 29 个关键词 → 240 子句，去重+封顶后该画像召回 4.1s → 2.3s。
- **已 saved/ignored/applied 的岗下推到 SQL 排除**（`id <> all(...)`，封顶 500 个 id）：
  它们在 stage-2 必被 `already_actioned` 挡掉，留在候选里只白占名额。

### 9.2 被 live 实测**推翻**的三种写法（别再走）

| 写法 | 实测 | 结论 |
|---|---|---|
| 第 4 节建议的 `order by ts_rank(...)` | 对全部 98,009 命中行算分再排 → **3.9s**（同查询按最新只要 57ms） | ❌ 不可用 |
| 「方向×城市」单独成一层 | 等于让 GIN 把那条昂贵的方向 tsquery 扫两遍；某重画像 3.3s → **6.0s** | ❌ 改为层内排序 |
| 层与层用 `not (...)` 互斥去重 | 行数估算被打成 `rows=1`、计划翻车；且实测耗时零变化 | ❌ 改为 JS 按 id 去重 |

### 9.3 ⚠️ 第 3 节有一个数字会误导人：旧实现的 DB 耗时不是 640ms

第 3 节的 640ms 来自**单个**画像。把 15 个真实画像逐个量一遍（`explain analyze`，香港库，
旧/新交替各跑 3 次取中位数）后才看清真实分布：**10ms ~ 3.3s**，而且

- **没有任何一个画像的计划会「早停」**——全部是 Bitmap Heap Scan / Parallel Seq Scan 喂给 top-N Sort。
  所以「按最新排序 + limit 能省扫描」这个直觉在这里**不成立**，改排序键不会损失早停（本来就没有）。
- 有 4 个画像的旧查询退化成 **Parallel Seq Scan**（2.2~3.3s，纯计划失误）。共同点是它们都填了目标公司
  → OR 里有三个 tsquery 分支 → 计划器放弃 BitmapOr。拆成分层查询后各层都恢复走索引。

### 9.4 实测结果

**DB 耗时**（15 个真实画像，旧/新交替各 3 次取中位数，香港库 `explain analyze`）：

```
合计 15720ms → 8933ms  (−43%)
中位   442ms →  364ms
最重的四个画像：2976→1234 / 2958→1202 / 3331→2294 / 2249→647
```

**候选行数与最终展示**（跑**真实** stage-2 引擎：computeMatchFacts / checkEligibility /
scoreOpportunity / deriveOpportunitySignals / groupOpportunities，逐画像对比 sections 岗位集合）：

```
候选行数合计：19254 → 11347（−41%，跨区传输同比例下降）
展示岗位合计：  195 →   226（+16%）
```

「候选更少、结果更多」正是设计目标。候选存活率（eligible / 候选）普遍翻数倍：

| 画像 | 旧存活率 | 新存活率 | 展示岗位 |
|---|---|---|---|
| 781ba2ac | 1.6% | 6.3% | 20 → 20 |
| 5a64768e | 3.3% | 12.7% | 25 → 26 |
| 05333a94 | 2.6% | 11.8% | 20 → 21 |
| e3db757b | 18.5% | 47.8% | 25 → 25 |
| 850a23f4 | 6.1% | 26.5% | 20 → 20 |
| 8b447250 | 0.1% | 6.1% | **2 → 20** |
| 3540f54e | 0.2% | 1.8% | **3 → 16** |
| 36ee81f2 | 0.7% | 1.8% | 11 → 16 |

**三层都不是摆设**（统计最终展示出来的岗分别来自哪一层，说明权重没有明显跑偏）：

```
781ba2ac  role 13 / cityNew 6 / company 1
05333a94  role 15 / company 6
e3db757b  role 16 / company 7 / cityNew 2
850a23f4  role 16 / cityNew 4
80e9417e  role 30（该画像没填城市/公司，只有 role 层）
```

**「不再按新截断」的直接证据**（改后新捞到、且**不是**最近 24h 首见的岗）：

- 8b447250：新增 18 个岗，全部是 40+ 天前首见的实习岗（VLA 算法实习生 / 数据生成算法实习生 …，score 62）
- 3540f54e：新增 13 个，同样是 40+ 天前首见（渗透测试实习生 score 68 …）
- 05333a94：字节跳动/AI 产品运营实习生（2.5 天前，score 87）、腾讯/AgentRuntime 高级技术产品经理（score 87）
- 781ba2ac：字节跳动三个 23.9 天前首见的校招岗（score 75）

### 9.5 诚实记账：一个画像变差了

`298146bb`（5 个目标岗位 + **24 个关键词**）：展示 14 → 5。已排查确认**不是** bug：

- 不是子句预算造成的：把扩展上限调到无穷大，结果一模一样（14 → 5）。
- 不是预算不够：`budget` 提到 1200 结果仍是 14 → 5。
- 真因是**这个画像的分层没有区分度**：29 个原词展开后匹配了库里 38,046 行，
  「方向层」≈「全库」，存活率旧 0.9% / 新 0.7% 基本没变 —— 于是候选从 1500 降到 743，
  展示就等比例减少。换句话说，对这类「关键词写太多 → 方向等于没写」的画像，
  本次改动的相关度排序帮不上忙，只有量能帮上忙。

留给后续（**未做**）：① 产品侧引导用户收敛关键词（写 24 个关键词的画像，筛选精度必然差）；
② 或按画像自适应预算（存活率低的画像多给候选）——需要两次往返或历史统计，本轮没做。

### 9.6 线上验收（commit `31f12b6`，部署 success 后实测）

`/today?__timing=1`，测试账号，7 发；同一时间窗测 `/saved`、`/path` 作对照组（本轮完全没碰过）。

| 阶段 | 改前（第 3 节，3 发） | 改后（7 发） | |
|---|---|---|---|
| **召回** | 2432 / 2293 / 2397 ms | **662 ~ 784 ms**（中位 675） | **−71%** |
| 候选行数 | 1500 | 773 | −48% |
| 逐岗 JS 计算 | 577 ~ 623 ms | 232 ~ 270 ms | −58%（候选少了自然少算） |
| **feed 端到端** | 2875 ~ 3475 ms | **899 ~ 1244 ms** | **−70%** |
| TTFB | 2.4 ~ 4.0 s | 1.86 ~ 3.09 s | |
| 全部加载完成 | 6.2 ~ 9.0 s | 3.75 ~ 5.79 s | |

对照组同期：`/saved` TTFB 2.05~2.46s、`/path` 2.0~3.0s —— 与历史水平相当，
说明本机链路当时**不是**异常地快，上面的下降是真实的（见 6.4 的测量方法论）。

### 9.7 复现方式

评测脚本没有入仓（一次性诊断，依赖线上库与真实用户画像）。要重跑：见本文件第 6 节的连库方式，
写一个脚本用 `tests/_load-ts.js` 加载 `lib/opportunities/*` 引擎 + `buildRecallSql`，
对每个 `user_preferences` 行构造 `RadarProfile`，跑「旧 SQL / 新 SQL」两份候选进同一套引擎比对。
注意本地缺 `JOBS_DATABASE_SSL_CA` → 用 `pg` 直连时要去掉连接串里的 `sslmode` 并
`ssl: { rejectUnauthorized: false }`（**仅本地诊断**；生产路径 `lib/jobs-store/client.ts` 仍是严格 TLS）。

`tests/_load-ts.js` 本轮加了两个解析兜底（只加兜底、不改既有顺序）：`server-only` 当空模块、
`@/` 别名按仓库根还原 —— 否则 `lib/jobs-store/*` 这类文件根本没法单测。
