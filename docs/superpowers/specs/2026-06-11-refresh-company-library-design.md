# 设计：on-demand「刷新公司库」（全异步 · 流式）

> 状态：已与用户脑暴定稿（2026-06-11），进入实现。
> 规则优先级：本 spec < 用户当前指令 < 项目 CLAUDE.md。冲突以更高优先级为准。

## 1. 问题 / 动机

现状的「刷新公司库」(`/api/search`) 名不副实：用户点一下，**真正当场去爬的只有 ~11 个源**（baidu / jd / apple + 最多 8 个相关 greenhouse/lever），而全库 868 个源里 **~733 个浏览器源（飞书/北森/Moka 等，恰是中国用户的绝大多数目标公司）根本不会被点击刷新触达**——它们只能等后台 1/7 轮转。这是产品雷点：一个承诺"刷新我的公司库"的按钮，实际覆盖率 < 2%。

**目标**：用户点「刷新公司库」，能**真的**把自己关注的全部公司都刷一遍、拿到新岗位。

**硬约束**：Vercel serverless 无浏览器、寿命数秒，浏览器源（SPA，需 Playwright 渲染+拦截）**物理上无法在点击瞬间同步抓取**。因此"秒回全部"不可能；窄秒回（只覆盖少数 httpx 公司）对中国用户无意义。结论：**放弃同步秒回，改为全异步 + 实时流式进度**。

## 2. 方案总览

点击 → 一次**诚实的后台刷新**，覆盖用户**当前筛选 + 偏好兜底、cap 前 N** 家公司；CI 用**真 Python 爬虫**跑（httpx 先、浏览器后），结果**实时流式**回灌前端。**一套代码、零 JS 适配器重写**——全程复用既有的 discovery 异步轨道 + crawler 并发机制。

```
用户点击「刷新公司库」
  → /api/refresh: 解析 scope(当前筛选+偏好兜底, cap N) → 节流检查 → 插 discovery_runs(mode=company_refresh, 存 source_ids+click_time) → workflow_dispatch → 返回 run_id
  → GitHub Actions: CompanyRefreshRecipe 按 source_ids 选源 → httpx 先并发 / browser 后串行 → 逐批 upsert + 增量写 discovery_runs.diagnostics
  → 前端: 复用 discovery 轮询(6s/8min) → 进度条 X/N + 新岗位实时冒 + 完成 badge「本次新增 M」
```

## 3. 非目标（v1 YAGNI）

- ❌ 不把 ~17 个 httpx 适配器移植成 JS（即时秒回）——靠 CI 统一跑，避免双语言漂移（用户已拍板「都走 CI」）。
- ❌ 不做撤岗/expired 检测——刷新只「加新」，下架仍走现有 per-source enrich fetcher。
- ❌ 不做邮件/飞书/微信 push 通知（Phase-1 边界）——靠在页轮询 + 回访 badge。
- ❌ 不做"全部与用户背景相关的源(上百家)"一次刷完——cap N 控总量，超出的不在单次范围。

## 4. 组件（按职责隔离）

### 4.1 scope 解析 — `lib/refresh-scope.js`（新，纯函数）
- **做什么**：输入用户当前筛选项（city/jobType/keyword/company）+ 用户偏好（target_companies/target_roles/target_locations）+ enabled sources 列表，输出按相关性排序、cap 到 N 的 source_id 列表。
- **覆盖规则**（CLAUDE.md 原则#2）：用户手动配了某项按该项；未配的项用偏好兜底。
- **接口**：`resolveRefreshScope({ filters, preferences, sources }, { cap }) -> { sourceIds: string[], matchedCount, droppedCount }`
- **依赖**：复用 `lib/live-search.js` 的 `selectRelevantSources` 打分逻辑（避免重造相关性排序）。
- **可测**：纯函数，覆盖 手动优先 / 偏好兜底 / cap 截断 / exclude_keywords 命中剔除。

### 4.2 dispatch — `app/api/refresh/route.ts`（新）
- **做什么**：POST 触发一次刷新。鉴权 → 解析 scope → **节流检查** → 插 `discovery_runs` → `workflow_dispatch` → 返回 `{ run_id, statusUrl, queued: N }`。
- **复用**：`lib/discovery-dispatch.js`（`resolveDispatchConfig`/`buildWorkflowDispatchRequest`/`isDispatchAccepted`）；mode 串用 `company_refresh`。
- **节流**：见 §6。冷却期内再点 → 不重复 dispatch，返回当前 in-flight run 的 status（`reused: true`）。
- **依赖**：service-role Supabase（写 discovery_runs）；GitHub workflow_dispatch token（与 discovery 同一套）。

### 4.3 status — 复用 `app/api/discovery/status/route.ts`
- **做什么**：前端轮询，RLS 校验 user_id → 汇总 run 状态 + 产出岗位。
- **改动**：支持 `mode=company_refresh` 的 run；读 `diagnostics.progress`（X/N）+ `diagnostics.produced_jd_urls`（增量），batch-fetch jobs。基本零改或极小改（现有 `summarizeDiscoveryRunStatus` + `extractProducedJdUrls` 已通用）。

### 4.4 引擎 — `crawler/discovery.py: CompanyRefreshRecipe`（新）
- **做什么**：CI 内按 `discovery_runs.diagnostics.source_ids` 取源 → **httpx 源先、browser 源后** → 用 `run.py` 的 `_partition_by_tier`/`_group_by_host`/`_get_thread_supabase` 并发跑 httpx、串行跑 browser → 复用 `db.upsert_jobs_batch` → **每完成一批就 `db.update_discovery_run` 增量写 progress + produced_jd_urls**（撑流式）。
- **接口**：与现有 `SpaKeywordRecipe` 同形（`recipe.run() -> produced`），但**按 company/source_id 选源**而非 keyword。
- **扩 `DISCOVERY_ADAPTERS`**（`crawler/discovery.py:225`，今天仅 8 个）：补 beisen / moka / feishu-generic / google 等浏览器源 adapter，使其能被按需调度。
- **依赖**：`run.py` 并发机制、`db.py` upsert + update_discovery_run、各 adapter。

### 4.5 CI 工作流 — 复用 `daily-crawl.yml` 或新增 mode
- **做什么**：`workflow_dispatch` 带 `mode=company_refresh` + `run_id` → 装依赖（**仅当 scope 含 browser 源才装 chromium**，省启动时间）→ `python crawler/run.py`（DISCOVERY_* 环境变量驱动 → `run_discovery` → `CompanyRefreshRecipe`）。
- **httpx-first**：recipe 内部排序，让 httpx 批先产出（~1min），browser 批后产出（2–5min）。

### 4.6 前端 — `app/jobs/jobs-client.tsx`（改）
- **做什么**：「刷新公司库」按钮 → POST `/api/refresh` → 拿 run_id → **复用现有 `BrowserDiscoveryState` 轮询/超时/localStorage 持久化/merge**：进度条 `刷新中 X/N 家…` + 新岗位实时并入列表 + 完成 `本次新增 M 个岗位`。
- **诚实文案**：不再显示"已知源刷新"的误导口径；明确"正在后台刷新你的 N 家公司"。

## 5. 数据模型

复用 `discovery_runs`（009 迁移，已有 `user_id / mode / started_at / finished_at / diagnostics jsonb / idx(user_id,created_at)`）。**无需新表**。

- `mode = 'company_refresh'`
- `diagnostics` 约定字段：
  - `source_ids: string[]` —— scope 解析结果（CI 照此选源）
  - `click_time: timestamptz` —— 用于 "new since"（新岗位 = `jobs.first_seen_at > click_time`，`idx_jobs_first_seen` 已存在）
  - `progress: { done: N, total: N }` —— 增量进度
  - `produced_jd_urls: string[]` —— 增量产出（流式）
- 若 `diagnostics` 放不下 source_ids（极少见）→ 退化为存 company 名数组，recipe 按 company 选源。

**迁移**：预计**零 schema 迁移**（全用 diagnostics jsonb）。若节流需要额外索引再加；`idx(user_id,created_at)` 已够查"该用户最近一次 run"。

## 6. 节流（abuse / 成本）

- 公开仓库 Actions 分钟无限 → 节流主要防**刷爆 Actions 队列 / 重复无谓 job**，非防钱。
- **策略**：每用户冷却 **10min**（env `REFRESH_COOLDOWN_MIN` 可调）。dispatch 前查 `discovery_runs WHERE user_id=? AND mode='company_refresh' AND created_at > now()-cooldown`：
  - 命中且仍 running/queued → 返回该 run 的 status（`reused: true`），不重复 dispatch。
  - 命中但已 finished < cooldown → 返回 `cooldown_active`，前端提示"X 分钟内刚刷过，N 分钟后可再刷"。
  - 未命中 → 正常 dispatch。
- 复用 discovery 的 cooldown 思路（official-discovery 45min 缓存 + Baidu Qianfan cooldown 模板）。

## 7. 错误处理

- dispatch 失败（GitHub API 非 2xx）→ run 标 `failed`，返回 500 + 文案"触发失败，请重试"。
- CI job 超时/崩溃 → run 留在 running，前端 8min 超时 → 提示"部分完成，已入库 X 个；可稍后重试"。已增量写入的岗位不丢。
- 单源抓取失败 → recipe 内 catch 记录（`run.py` 既有"永不抛异常"约定），不炸整批；该源计入 progress 但 produced 为 0。
- scope 解析空（用户无筛选无偏好）→ 返回 `empty_scope`，前端提示"先设置目标公司或筛选项"。
- 节流命中 → §6，非错误，正常返回 reused/cooldown 态。

## 8. 测试

- **纯函数优先**（项目规范）：
  - `lib/refresh-scope.js`：手动优先 / 偏好兜底 / cap 截断 / exclude_keywords 剔除 / 空 scope。
  - 节流判定函数（给定最近 run 列表 + now → dispatch/reuse/cooldown）。
- **crawler unittest**（不打真实网络）：`CompanyRefreshRecipe` 按 source_ids 选源、httpx-first 排序、增量 update_discovery_run 调用次数；mock adapter。
- **不做** live E2E 单测（沙箱无法真跑 CI / serverless / Supabase）——live 验证在用户部署环境完成。
- 回归四件套：`node --test tests/*.test.js && python3 -m unittest discover -s crawler ... && npm run build && git diff --check`。

## 9. 工作分解（落地顺序）

1. `lib/refresh-scope.js` + 单测（纯函数，先行可测）。
2. `crawler/discovery.py: CompanyRefreshRecipe` + 扩 `DISCOVERY_ADAPTERS` + httpx-first + 增量 progress 写入 + crawler 单测。
3. `crawler/run.py` / `run_discovery` 接 `company_refresh` mode 的环境变量入口。
4. `app/api/refresh/route.ts`（dispatch + 节流，复用 discovery-dispatch）+ 节流单测。
5. `app/api/discovery/status` 兼容 `company_refresh`（读 progress/produced）。
6. `daily-crawl.yml` 接 `mode=company_refresh`（条件装 chromium）。
7. 前端 `jobs-client.tsx` 刷新按钮接全异步 + 进度 + badge + 诚实文案。
8. 回归四件套 + 自审。

## 10. 主要风险（已认）

| 风险 | 缓解 |
|---|---|
| CI 排队+启动 ~30–60s floor；browser 源 +chromium 1–2min | httpx-first 排序先出结果；仅含 browser 源才装 chromium |
| 单主机串行（moka 251/host、hotjob 68/host）刷新慢 | cap N 控总量；进度条让等待可见 |
| 流式需 recipe 边跑边写 discovery_runs（现 discovery 可能末尾写一次） | recipe 内逐批 `update_discovery_run`（小增强，已纳入 §4.4） |
| CI job 失败/超时 | run 标 failed；已增量入库的不丢；前端可重试 |
| 沙箱无法 live 验证 | 实现 + 单测 + build 充分；live E2E 交用户部署环境 |

## 11.5 硬化修订（对抗式审查后定稿，2026-06-11）

5 路对抗式审查（concurrency/security/failure/streaming/scope）结论：设计 green-light，但揪出 4 个 blocker——**「流式」在三层都没实现**、**无节流/幂等**、**前端 8min 超时 vs CI 55min**、**CI 崩溃 run 永卡 running**。逐条定稿：

- **流式 = 必须 BUILD（三层）**，不是现成假设：
  - (A) crawler：recipe 串行循环，**每抓完一个源就增量回写** `diagnostics={produced_jd_urls(set 去重), progress:{done,total}, last_update_at}` + 计数。
  - (B) status route：把 jobs 解析**移出 `isTerminal` 门**，每次轮询都按 `produced_jd_urls` 回查 jobs + 返回 progress。
  - (C) 前端：每 tick `mergeJobsByUrl` 去重并入 + 用真实 `progress` 驱动进度条（删掉硬编码 18/64）。
- **避开原子写 RPC 的关键**：recipe **串行单 worker** + **状态认领守卫**（queued→running 条件更新，`where status='queued'`，0 行=已被认领则退出）+ dispatch 幂等 → **同一 run 不存在并发写**，故沿用「内存累加器整体写 diagnostics」即可，**无需 SECURITY DEFINER jsonb-append RPC、无需 schema 迁移**（`last_update_at` 放进 diagnostics jsonb）。
- **节流/幂等（一次 pre-insert 查询）**：查该用户 10min 内最近的 `company_refresh` run →
  - 有 queued/running 在飞 → 返回该 run_id（`reused`，挡住快速连点/重复 dispatch）；
  - 否则 10min 内有 run（已结束）→ `429 + Retry-After`（冷却中）；
  - 否则 → insert + dispatch。前端再加 **2s debounce**。
- **超时不丢数据**：前端**超时不清状态**——转持久 banner + 继续轮询（run_id 已存 localStorage）；cap **N=25** 让单次目标 1–5min 完成；前端轮询超时上限抬到 > CI 天花板。
- **卡死 run 兜底（读时 staleness，免 cron）**：status route 读时若 `status=running` 且 `diagnostics.last_update_at` 距今 > 15min → 当 `failed/stale` 返回。
- **scope 解析做对**（新 `lib/refresh-scope.js` 自己控）：偏好兜底（manual 优先，未配用 `target_companies/keywords/roles/locations`）+ `expandSearchTerms` 扩词 + **每 adapter/host 多样性 cap（1–2 个）**防 25 槽被单主机 Moka 占满 + 公司零命中时回退关键词-only。crawler 端 `filter_raw_jobs` 已 honor exclude/city/type → 异步结果天然过滤正确。
- **minors**：dispatch 失败日志**抹掉 Bearer token**；env 统一 `GITHUB_DISPATCH_TOKEN`（弃 fallback）；`update_discovery_run` 写失败**抛错**（不静默把 run 搁浅）；status 端 user_id 手查是 load-bearing（注释标注）。
- **另案（不在本feature，单独跟进）**：现有同步 `/api/search` 内联路径**不 honor exclude_keywords**（CLAUDE.md #2 违规，pre-existing）→ 单开任务修；`upsert_jobs_batch` 23505 fallback 计数不精确（幂等无损坏，接受）。

## 11.6 数据流（流式版终稿）

```
点击(debounce 2s) → POST /api/refresh
  → 鉴权 → resolveRefreshScope(filters+pref兜底, cap25, host多样性) → source_ids
  → evaluateRefreshThrottle(该用户近10min run): reuse / 429+RetryAfter / dispatch
  → insert discovery_runs(mode=company_refresh, diagnostics={source_ids, click_time}) → workflow_dispatch(mode,run_id) → 回 run_id
GitHub Actions: claim_discovery_run(queued→running, guard) → CompanyRefreshRecipe:
  for src in [httpx 源... , browser 源...]:        # httpx 先
     抓→质量门→upsert→累加 produced(set)/counts/done
     update_discovery_run(running, diagnostics={produced_jd_urls, progress, last_update_at})   # 增量心跳
  → 终态 success/partial/failed
前端轮询(6s, 超时转banner不清状态): GET /api/discovery/status
  → 读时 staleness(running且last_update>15min→failed) → 每次按 produced_jd_urls 回查 jobs + progress
  → mergeJobsByUrl 增量并入列表 + 进度条 X/N → 终态 badge「本次新增 M」
```

## 11. 复用清单（不要重造）

- 异步轨道：`/api/discovery/dispatch` + `/api/discovery/status` + `lib/discovery-dispatch.js` + `discovery_runs`(009)。
- 前端轮询：`jobs-client.tsx` `BrowserDiscoveryState` + localStorage + 6s/8min。
- crawler 并发：`run.py` `_partition_by_tier`/`_group_by_host`/`_get_thread_supabase`；`db.upsert_jobs_batch` / `db.update_discovery_run`。
- 相关性排序：`lib/live-search.js` `selectRelevantSources`。
- recipe 生命周期：`crawler/discovery.py` `run_discovery`（queued→running→terminal）+ `SpaKeywordRecipe` 形态。
