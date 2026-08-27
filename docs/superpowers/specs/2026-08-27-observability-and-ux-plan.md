# 方案：可观测性主线 + 前端体验欠账

日期：2026-08-27
上游：`2026-08-27-observability-and-ux-handoff.md`（交接单）
性质：**方案，待拍板**。本文所有根因结论都有 live 实测数字，不是推测；§4 是需要创始人拍板的决策项，拍完再按 §5 分批开工。

---

## 0. 一句话

两条主线的病根都定位到了，而且都比交接单猜的更具体：

- **可观测性**：判据只问「跑没跑」，不问「产出了什么」。同一个页面里热力图和模块卡用的是**方向相反**的两套判据，所以必然自相矛盾。
- **前端 7.7 秒**：跟水合、跟前端一点关系都没有。首字节 162ms 就到了，页面之所以「没加载完」，是因为 HTML 流一直不关，在等召回；而召回**光在数据库里就要跑 4.7–5.9 秒**。

召回慢的真因已定位到单条 SQL：方向词被词库扩展成 112 个子句、命中 **14.7 万行**。剪掉 35 个通用扩展词后实测 **14.7 万 → 2.3 万行，整条召回 5.9s → 1.2–1.8s**。

---

## 1. 实测证据

所有数字为 2026-08-27 实测。前端在生产站已登录态实测，数据库为香港 jobs 库 `EXPLAIN (ANALYZE, BUFFERS)`。

### 1.1 `/today` 端到端分解（生产，已登录，`?__timing=1`）

页面里本来就有诊断探针（`app/today/page.tsx` 的 `TimingProbe`），直接读到了服务端分段耗时：

| 阶段 | 实测 | 归因 |
|---|---|---|
| 请求 → 首字节 | **162ms** | 正常，边缘 + 函数启动没问题 |
| shell 前的 4 条 Supabase 查询 | **1,169ms** | `user_preferences`/`candidate_profiles`/`job_actions`/`user_radar_state`，全在悉尼；载荷合计仅 24KB，纯跨洋 RTT |
| 首屏 JS/CSS | ~1,000ms | 最慢单文件 `_next/static/chunks/7275-*.js` 1,079ms / 30KB |
| → 首屏可见（FCP） | ~3.4s | 与交接单的 3,452ms 吻合 |
| feed 流（DOMContentLoaded 挂在这里） | **8,819ms** | 见下表 |
| → `responseEnd` 11,871ms / `DCL` 11,876ms / `load` 11,889ms | **11.9s** | 本次实测比交接单的 7.7s 更慢 |

**关键结论：`DOMContentLoaded` 不是水合慢，是流式 SSR 的响应体一直没关。** `responseEnd`(11,871ms) 与 `DCL`(11,876ms) 只差 5ms —— 文档一关闭 DCL 立刻就触发了。所以「FCP 之后那 4–7 秒」= 服务端还在算 feed，浏览器无事可做。

feed 内部（`buildOpportunityFeed` 自带的 `FeedTiming`）：

| 段 | 实测 | 说明 |
|---|---|---|
| `recall` | **6,764ms** | 香港库候选召回，**大头** |
| `compute` | 1,461ms | 1,216 个候选逐岗打分（JS） |
| `sourcemeta` | 574ms | 按 id 取 source 元信息（悉尼） |
| `critical` / `group` / `hydrate` | 79 / 2 / 18ms | 可忽略 |
| `total` | 8,819ms | 候选 1,216 → 展示 30 |

### 1.2 召回那 6.76 秒拆到 SQL 里

用**真实用户画像**（校招·产品方向，5 个方向词 + 23 个关键词 + 3 个目标城市 + 3 个目标公司）生成的**真实 SQL**，在香港库跑 `EXPLAIN ANALYZE`：

| 层 | 耗时 | 命中 |
|---|---|---|
| T1 方向层 | **4,195ms** | GIN 索引扫 1,526ms 命中 **163,136 行** → 堆扫到 7,456 行 → 排序 → limit 1800 |
| T2 目标公司层 | 1,352ms | 30,309 行 |
| T3 目标城市近 7 天层 | 260ms | 81,851 行 |
| **Execution Time** | **4,673 – 5,906ms**（交替多轮，控冷热缓存） | app 侧测得 6,764ms，差的约 1.8s 是连接 + 传输 + node-pg 解析 |

**所以召回是「库里算得慢」，不是「传得慢」。** 交接单里引用的报告结论「后端召回 SQL 仅 0.5–3.1s」在这个画像上不成立 —— 那多半是在较轻的画像上测的。

**方向层为什么命中 16 万行**：`ftsCandidateTerms` 的词库扩展把具体技能短语展成了裸通用词。从生产执行计划里原样摘出来的片段：

```
''mvp'' & ''定义'' | ''mvp'' | ''定义''
''figma'' & ''原型'' | ''figma'' | ''原型''
''kano'' & ''优先'' & ''先级'' | ''kano'' | ''优先'' & ''先级''
''agent'' & ''loop'' | ''loop''
''spec'' & ''全栈'' | ''spec'' | ''全栈''
… 以及 ''产品'' / ''数据'' / ''设计'' / ''研发'' / ''工程'' & ''程师'' / ''架构''
```

用户写的是「MVP 定义」「Figma 原型」「Kano 优先级」，进 SQL 时**额外**多出了 `定义`、`原型`、`优先级`、`产品`、`数据`、`设计`、`研发`、`工程师`、`架构`、`全栈`、`loop` 这些谁都能命中的裸词。这是**已上线的「匹配器精度包」修过的同一类病**（短词撞正文），只是那次修的是 stage-2 打分，stage-1 召回这条漏了。

**剪枝实验**（同一画像、同一 SQL，只把扩展产出里的裸通用词剔掉，用户原词一个不动，112 词 → 77 词）：

| | 命中行数 | Execution Time（交替 3 轮） |
|---|---|---|
| 现状 | 147,111 | 5,906 / 5,451 / 4,673 ms |
| 剪枝后 | **23,469（−84%）** | 1,785 / 1,188 / 1,577 ms（**−70%**） |

三层各自仍取满 1,800 行预算（T1 1800 / T2 1800 / T3 1494），**没有出现候选饿死**。

⚠️ 诚实边界：行数取满不等于取的是同一批行。上线前必须做真实数据对拍（见 §5 批 3 验收）。

### 1.3 F-2「满屏字节」不是软 cap 没兜住，是 cap 兜住后又被自己撤销

线上 feed 的 30 张卡按顺序读出来：

```
字节×9  →  携程×6  →  传音×3 / 汉得×1 / 哈啰×5  →  字节×6
```

`lib/opportunities/grouping.ts:120` 的 `perCompanyCap = max(2, ceil(30*0.3)) = 9`。前 24 张严格守住了配额（字节正好 9 个封顶），**然后最后 6 张又是字节** —— 那就是同一个函数里的回填分支：

```ts
if (picked.length < limit) {
  for (const opportunity of overflow) {   // ← overflow 就是刚被配额拒掉的那些
    if (picked.length >= limit) break;
    picked.push(opportunity);
  }
}
```

候选池里够格的公司只有 5 家（字节 / 携程 / 哈啰 / 传音 / 汉得），凑不满 30 张 → 回填把刚拒掉的字节原样放回来 → 9 + 6 = 15。

**配额和回填是同一个函数里互相抵消的两段代码。** 另外 `critical` 区在代码注释里明写「不截断、不受公司配额影响」，是同一个坑的第二处，目前没暴露只是因为该区当前为空。

### 1.4 F-3 看板自相矛盾：两套判据方向相反

| 位置 | 判据 | 代码 |
|---|---|---|
| 30 天热力图 | **任一任务失败 → 红（"处理"）** | `app/admin/health/page.tsx:1221` 的 `processTrackerItems(dailySeries,'ops')` |
| 模块卡 | **全部 run 都失败才算失败** | `lib/admin-health.ts` 的 `reportStatus` |

```ts
function reportStatus(runs: number, failed: number): DailyReportStatus {
  if (runs <= 0) return "idle";
  if (failed >= runs) return "failed";   // 10 个挂 9 个 → 仍然 success
  return "success";                       // 产出多少完全不参与判断
}
```

同一天、同一份 `ops_runs` 数据，一个判红一个判绿 —— 不是「判据没查」，是**两个判据方向相反**。而且 `reportStatus` 只有 `runs` 和 `failed` 两个入参，**产出量根本没进函数**，所以「刷新/发现 · 产出岗位 0 · ● 正常」是必然结果，不是偶发。

概览卡「系统运行 6/6 · 全部正常」来自 `app/admin/health/page.tsx:1100`，口径是「6 个模块今天都有运行记录、且没有一个是全挂」—— 与产出无关。

### 1.5 后台任务的静默清单（实测）

| 事实 | 实测 |
|---|---|
| `db-report.yml` 最后一次运行 | **2026-07-11**（47 天前）。CLAUDE.md 明写「诊断先跑 db-report」，但它**没有 schedule** |
| `production-smoke.yml` 最后一次运行 | **2026-07-11**（47 天前）。同样没有 schedule —— 有冒烟测试，但是死的 |
| 洞察现查台账 | `discovery_runs(mode='insight_enrich')` **7 条全部 queued**，最早 2026-07-07、最新 2026-08-27。**52 天没有一条被回写成完成或失败** |
| run 级会骗人 | `dead-link-audit` 某次 run 级 `cancelled`，job 级却是 `success,success,cancelled,success,success,cancelled,skipped`；近 9 次里 3 次被杀 |
| 台账有、看板不看 | `ops_runs` 近 7 天有 14 个模块在写；`buildDailyReports` 只归集了 9 个。**漏掉的 5 个里正好有一个在大面积失败**：`gap_funnel` 失败 11 / 成功 2 / 部分 1，`gap_funnel_browser` 失败 6 / 成功 7 —— 看板上完全看不到 |
| 告警出口 | **一个都没有**。29 个 workflow 里零 issue / webhook / 通知调用 |

---

## 2. 主线一方案：可观测性

原则：**不引入任何监控套件**（项目边界禁止 Redis / K8s / 监控大套件）。全部落在已有的三样东西上 —— GitHub Actions、`ops_runs` 台账、看板本身。

### 2.1 层 1：让看板说真话

**核心改法 = 一个判据、两个信号。**

**(a) 判据收敛成唯一一个纯函数**，热力图和模块卡都调它，从结构上杜绝互相矛盾：

```ts
// lib/admin-health.ts 新增
export type ModuleVerdict = "healthy" | "attention" | "broken" | "idle";
export function moduleVerdict(input: {
  runs: number; failed: number; produced: number | null; expectsOutput: boolean;
}): ModuleVerdict
```

判据（三条，按优先级）：
1. `runs === 0` → `idle`（今天没记录，**不是正常也不是失败**）
2. `failed > 0` → `attention`；`failed >= runs` → `broken`（**不再是「全挂才算挂」**）
3. `expectsOutput && produced === 0` → `broken`（**产出为 0 一律不许判正常**）

**(b) 每个模块声明自己的「产出口径」**，让 `produced` 有明确来源：

| 模块 | 产出口径 |
|---|---|
| 抓取 | 今日入库岗位数 |
| 富化 | `enriched` |
| 死岗治理 | `checked` |
| 职业洞察 | `today_created` |
| 自动扩源 | 今日新增源数 |
| 刷新/发现 | 产出岗位数 |
| 缺口漏斗（新增卡） | `source_added` |
| 校招供给（新增卡） | 校招岗入库数 |

**(c) 卡片显示两个独立信号，不合并成一个词**：
`今天跑了 N 次 · 失败 M 次` 和 `今日产出 X` 分开展示，各自带自己的颜色。现在是一个「● 正常」把两件事糊在一起。

**(d) 概览卡改口径**：「系统运行 6/6 · 全部正常」→「**产出正常 X/N**」，与热力图同源。

**(e) 补齐漏掉的 5 个模块**：`gap_funnel` / `gap_funnel_browser` / `campus_lane` / `campus_cycle_backlog` / `campus_official_backlog` 加进 `buildDailyReports`，凑成两张新卡（缺口漏斗、校招供给）。

**改动文件**：`lib/admin-health.ts`（判据 + 模块表）、`app/admin/health/page.tsx`（概览卡文案 + 两张新卡 + 热力图改调同一判据）、`tests/admin-health*.test.js`（补「产出 0 必须判 broken」「挂 9/10 必须判 attention」「热力图与模块卡对同一天结论一致」三条断言）。

### 2.2 层 2：真产出告警

**出口 = 本仓库的 GitHub Issue**（`gh issue create`）。理由：零新依赖、零新账号、创始人手机上有 GitHub 通知、issue 天然可关闭可追溯。防刷屏：每类告警固定标题前缀，已有同标题的 open issue 就追加评论、不新开。

**新增 `crawler/ops_watchdog.py` + `.github/workflows/ops-watchdog.yml`**（每日 UTC 01:00，排在所有夜间任务之后）。五条规则：

| 规则 | 判据 | 为什么 |
|---|---|---|
| A 连续零产出 | 某模块连续 **2 天** `produced === 0` | 交接单第一条：产出 0 一直被当正常 |
| B 被超时杀掉 | **按 job 级判**：`gh api .../runs/{id}/jobs`，任一 job `conclusion=cancelled` 且 run 时长 ≥ 声明 timeout 的 95% | 死链审计连续 13 晚被杀、27 天没人发现，就是因为只看 run 级 |
| C 台账不回写 | `discovery_runs` 里 `queued` 超过 **6 小时** 的行 | 洞察现查 7/7 卡了 52 天 |
| D 账户级错误 | provider 返回 **401 / 402 / 403**，或 429 且响应体含 `quota`/`insufficient` | 欠费返 402 而判据只认 401/403 → CI 全绿烧了两天额度 |
| E 关键任务超期未跑 | 声明周期 × 2 仍无运行记录 | `db-report` / `production-smoke` 各自死了 47 天 |

**顺带修的两处**：
- `db-report.yml` 补 `schedule`（每日 UTC 03:30，抓取之后）—— CLAUDE.md 要求「诊断先跑 db-report」，它必须是活的。
- `production-smoke.yml` 补 `schedule`（每日 UTC 04:00）。
- 账户级错误判据从 401/403 扩到 401/402/403（规则 D 的代码侧同款修复，在 provider 调用处）。

### 2.3 层 3：用户视角指标

把「用户实际体验」变成每天自动记录的数字，而不是等人偶然打开页面才发现。

**新增 `.github/workflows/ux-probe.yml`**（每日一次），用探测账号请求 `/today?__timing=1`，把探针 JSON 落进 `ops_runs(module='ux_probe')`：

| 指标 | 口径 | 红线 |
|---|---|---|
| `server_total_ms` | 页面函数端到端 | > 4,000ms 告警 |
| `recall_ms` | 召回 | > 2,000ms 告警 |
| `displayed` | 展示岗位数 | < 10 告警 |
| `distinct_companies` | 展示岗位去重公司数 | < 5 告警（直接盯 F-2 这类问题） |
| `dead_click_rate` | 复用现有 `/api/jobs/liveness-check`，当日探活判死比例 | > 5% 告警 |

⚠️ 探测账号需要一个可编程登录态 —— 见 §4 决策项 2。

---

## 3. 主线二方案：前端体验欠账

### F-1 首屏 7.7 秒 → 目标 2.5 秒内可用

三段独立、按收益排序，**可以分开上、分开验**：

**F-1-a 召回方向层剪枝（省 3–4 秒，主菜）**

- 修法：在 `lib/jobs-store/opportunities.ts` 的 `roleTsquery()` 里，对**词库扩展产出**过一道停用词门 —— 剔除本身就是通用泛词的裸 token（`产品`/`数据`/`设计`/`研发`/`工程师`/`定义`/`原型`/`优先级`/`架构`/`全栈`/`loop`/`engineer` 等）。
- **用户原词一律保留**：写「产品经理」仍然精确召回「产品经理」；砍掉的只是词库替他多加的裸通用词。
- 停用词表放 `lib/china-keyword-expansion.js` 旁边，与 stage-2 匹配器共用同一份，避免两端漂移。
- 实测预期：命中 147,111 → 23,469 行，Execution 5.9s → 1.2–1.8s。

**F-1-b shell 不再等悉尼（省 ~1.2 秒 FCP）**

- 现状：`app/today/page.tsx` 在返回任何 JSX **之前** `await` 了 4 条悉尼查询（1,169ms），导致 Navbar + 页头 + 骨架全被拖住。
- 修法：把「onboarding 还是 feed」的判断整体挪进一个 Suspense 边界，页头/导航先出。页面已经是流式架构，这是同一套写法的延伸，不引入新机制。
- 注意：`getRequestUser()` 读的是 middleware 注入的请求头、零网络，**不要动它**。

**F-1-c `compute` 1,461ms / `sourcemeta` 574ms**

- 本轮**不动**。等 a、b 上线后复测 —— 候选集变了，这两个数字会跟着变，现在优化等于对着旧数据调参。

### F-2 满屏一家公司

真因是回填分支撤销了配额（§1.3）。三个方案，**需要拍板**（§4 决策项 1）：

| 方案 | 做法 | 代价 |
|---|---|---|
| **A（推荐）** | 回填也守配额，只把上限放宽到 `cap + ceil(cap/2)`（9 → 13） | 该画像 30 → 28 张卡，字节从 15 降到 13 |
| B | 不回填，短就短 | 该画像 30 → 24 张卡，字节 9 |
| C | 在召回层加 per-company cap | 架构级改动，影响所有下游；**但能治本**（候选池本身就只有 5 家公司） |

⚠️ 无论选哪个，**都治不了「候选池只有 5 家公司」这个更深的问题** —— 那是供给侧的事，属于必投缺口那条线。配额只决定「把 5 家怎么摆」。
另：`critical` 区同样不受配额约束（同一个坑的第二处），一并加守卫。

### F-3 看板说谎

并入 §2.1，不单独开工。

### F-4 滚 14 屏

现状实测：30 张卡、单卡塞 3 行 JD 正文 + 右侧 5 个竖排按钮。建议：

1. JD 正文默认 1 行，「展开」再出（现在是默认 3 行）
2. 右侧 5 个竖排按钮 → 2 个主动作（值得投 / 忽略）+「更多」
3. 30 张卡分段：先出 10 张，「继续看」再出

⚠️ 这块是纯视觉判断，**建议先出一张改前改后对比图给创始人看再动手**（§4 决策项 4）—— 上一轮的教训就是自说自话不看页面。

### 两个小视觉

- 落地页主标题「机／会。」孤字：`text-wrap: balance` 或在断点处手动断行
- 卡片「展开全文」与匹配标签的蓝色 → 换成全站墨绿 token

---

## 4. 需要创始人拍板的决策项

| # | 事 | 选项 | 我的建议 |
|---|---|---|---|
| 1 | F-2 用哪个方案 | A 回填守配额 / B 不回填 / C 召回层加 cap | **A**。改动最小、立刻见效；C 留到供给侧公司数上来之后再评估 |
| 2 | UX 探测账号怎么来 | ① 建一个专用测试账号存 GitHub Secret ② 只探不需要登录的接口、放弃端到端 ③ 暂不做层 3 | **①**。否则层 3「用户视角指标」落不了地 |
| 3 | 告警发到 GitHub Issue 行不行 | GitHub Issue / 邮件 / 其他 | **GitHub Issue**。零新依赖、手机有推送、可追溯 |
| 4 | F-4 卡片瘦身要不要先看设计稿 | 先看稿 / 直接改 | **先看稿**。纯视觉取舍，我不该替你定 |
| 5 | `summary_doc` 全文检索本轮做不做 | 做 / 不做 | **不做**。主漏因已修完、收益递减，代价是生产库加列 + 38 万行回填 + 爬虫写入变慢 |

---

## 5. 批次与验收

每批都是：**四件套全绿**（`node --test tests/*.test.js`、`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`、`npm run build`、`npx next lint --dir lib --dir app --dir components`）→ push → **打开线上页面复看 + 截图/实测数字进验收** → 更新记忆。

| 批 | 内容 | 验收判据（可证伪） |
|---|---|---|
| **批 1** | §2.1 看板说真话（判据统一 + 产出进判据 + 补 5 个模块） | 线上 `/admin/health`：热力图判红的那一天，模块卡不得同时判绿；「产出 0」不得出现「正常」；缺口漏斗卡显示 `gap_funnel` 当前的失败状态 |
| **批 2** | §2.2 告警 + `db-report`/`production-smoke` 复活 + 402 判据 | 手动触发 watchdog，能对当前真实存在的问题（`gap_funnel` 连日失败、7 条 queued 台账）开出 issue；`db-report` 次日自动跑出一次 |
| **批 3** | F-1-a 召回剪枝 + F-1-b shell 不等悉尼 | ① 同画像 `EXPLAIN ANALYZE` Execution < 2s；② **真实数据对拍**：剪枝前后各跑一遍 feed，展示岗位数不下降、报告点名的 93 分岗仍在第一屏；③ 线上 `?__timing=1` 复测 `server_total_ms` < 4s、`DCL` < 5s |
| **批 4** | F-2（按拍板方案）+ 两个小视觉 | 线上 feed 单公司占比 ≤ 45%；落地页标题无孤字；卡片无蓝色 |
| **批 5** | F-4 卡片瘦身（看稿后） | 页面高度较现状下降 ≥ 40%，且首屏能看到 ≥ 2 张完整卡 |
| **批 6** | §2.3 UX 探测（依赖决策项 2） | `ops_runs` 出现 `ux_probe` 记录，看板能显示昨日首屏耗时与公司多样性 |

**批 3 的对拍是硬要求**：本项目三个最严重的 bug 全是真实数据对拍抓到的、单测一个都没发现。剪枝改的是「哪 1800 行进候选池」，单测证明不了它没伤召回。

---

## 6. 本轮明确不做

- `summary_doc` 全文检索（决策项 5，建议单独立项）
- `compute` / `sourcemeta` 优化（F-1-c，等召回改完再测）
- 候选池只有 5 家公司这个供给侧问题（属必投缺口那条线）
- 任何监控套件 / 新中间件（项目边界）

---

## 附：本方案用到的诊断手法（可复用）

1. **页面里的 `?__timing=1` 探针**（`app/today/page.tsx`）—— 已经存在，不用重新造，直接读 `#jr-timing` 的 JSON。
2. **判断「慢在库里还是慢在路上」**：app 侧计时 − `EXPLAIN ANALYZE` 的 `Execution Time` = 连接 + 传输 + 解析开销。本次 6,764 − 5,900 ≈ 1.8s。
3. **`buildRecallSql` 是导出的纯函数** —— 可以在 node 里用真实画像生成真实 SQL，把 `$N` 内联成字面量后直接丢给 `psql` EXPLAIN。这是本次能精确定位到「方向层 4.2 秒」的关键。
4. **测 DB 耗时必须交替跑控冷热缓存**：本次现状/剪枝交替 3 轮才敢下「−70%」的结论。
5. **判 workflow 死活必须看 job 级**：`gh run view <id> --json jobs`，run 级 `success` 里可能混着 `cancelled` 的 job。
