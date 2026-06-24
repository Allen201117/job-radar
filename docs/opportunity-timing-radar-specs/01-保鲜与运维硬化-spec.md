# 01 保鲜与运维硬化 Spec（护城河实现规格）

> 日期：2026-06-24
> 地基文档：`产品方向v2-岗位保鲜雷达.md`（v3）
> 性质：把"极少死岗"从口号变成**可考核、可落地**的工程规格。这是这一版**最重要**的一份。
> 实现基线：基于 `draft/radar-pivot-0623` 分支扩展（已含 `lib/opportunities/`、新 API、迁移 160–163）。
> 适用读者：实现 agent。技术精确，禁止用 mock/估算冒充真实行为。

---

## 0. 目标与不变量

### 0.1 目标

让"**推荐给你的每个岗位都刚核验过、极少踩空**"成为可度量的事实：

1. 给用户看的岗位，按场景分层、有明确的"最近核验时限"；
2. 能算出**点击有效率**（用户点开官网后岗位仍在招的比例），目标 ≥99%；
3. 死岗检测最弱的 SPA 源（飞书/Moka/北森/自建大厂）不再有 7 天盲区；
4. 全程不破坏现有保鲜基建的关键不变量。

### 0.2 必须保留的现有不变量（破坏即回归失败）

实现 agent 必须保住下列已验证语义（来自 `crawler/jobs_db.py`、`lib/jobs-store/write.ts`）：

1. **`expired` sticky**：`status='expired'` 的岗，列表重抓不得复活（`_update_set_clause()` 里的 `CASE WHEN jobs.status='expired' THEN 'expired'`）。
2. **summary preserve-if-empty**：`_PRESERVE_IF_EMPTY`（summary/job_type/experience/education/deadline）UPDATE 时空值用 `COALESCE(NULLIF(%s,''), 列)` 保留旧值。
3. **`enrich_checked_at` 不被列表重抓覆盖**：列表 upsert 的 `_UPDATE_COLS` 不含 `enrich_checked_at`；只有富化/巡检/实时核验能写它。
4. **死岗检测只在明确撤岗信号才判 dead**：拿不准（超时、未知响应、非 404 错误）一律 `unknown` → 放行，绝不误杀活岗（`lib/liveness-client.js` 现有约定）。

---

## 1. 现状基线（实现前必读，勿重造）

已有、可直接复用的保鲜资产：

| 资产 | 文件 | 作用 |
|---|---|---|
| 撤岗信号识别 | `crawler/enrich.py`（`ENRICH_REGISTRY`、`_detail_wt/_detail_hotjob/_detail_workday/...`、`JobClosedError`） | httpx 源逐岗反推 detail，识别 wt `req_state=9501` / hotjob `state=1017` / workday-family 404 |
| 富化 + 巡检队列 | `crawler/enrich_backlog.py`（`fetch_queue`/`fetch_liveness_queue`/`enrich_row`/`drain`） | 补 summary + 按 `enrich_checked_at` 最旧轮转探活，撤岗→`expired` |
| SPA 软 404 审计 | `crawler/audit_dead_links.py`（`classify`/`mark`/`fetch_browser_liveness`，`DEAD_MARKERS`） | 无头渲染判 dead，6 分片轮转，`--apply` 才写 |
| 展示层实时核验 | `app/api/jobs/liveness-check/route.ts` + `lib/liveness-client.js`（`checkLiveness`/`livenessSupported`） | 看板加载后异步批量探活当下可见岗（wt/hotjob/workday），死的标 `expired` 并前端隐藏 |
| 写库语义 | `crawler/jobs_db.py`、`lib/jobs-store/write.ts`（`markJobExpiredById`/`touchJobCheckedById`） | upsert + 状态/字段不变量 |
| 定时任务 | `.github/workflows/`：`daily-crawl`(00:00 httpx+sweep12k)、`liveness-sweep`(08:00)、`enrich-backlog`(每3h)、`enrich-backlog-browser`(20:00 moka)、`dead-link-audit`(22:00 SPA 6分片)、`purge-expired`(02:30) | 全部已映射 `JOBS_DATABASE_URL` |

**现存缺口**（本 spec 要补）：
- A. SPA 源死岗检测靠 6 分片轮转，**新灌入的坏岗最长 7 天才首检**；自建 SPA（kuaishou/byd/bytedance/google）的死亡标记**未逐站核实**，可能漏判/误判。
- B. **没有"点击有效率"埋点**：点击时不记录岗位当时是否还活，无法度量核心承诺。
- C. **没有"展示前/点击前"对 SPA 源的兜底核验**（liveness-check 只覆盖 wt/hotjob/workday）。

---

## 2. 分层核验 SLA（核心机制）

### 2.1 SLA 定义

不同场景对"最近核验时限"要求不同，**不一刀切**（一刀切会让 SPA 源成本爆炸）：

| 场景 | 核验时限要求 | 不满足时的行为 |
|---|---|---|
| **今日机会 / 邮件推荐** | `enrich_checked_at` 必须在 **24h** 内 | 不进主推荐；可降级到"待确认"区或不展示 |
| **搜索结果 / 公司页** | `enrich_checked_at` 在 **72h** 内 | 仍可展示，但标 `待确认`，不写"最近确认仍在招" |
| **用户点官网链接前** | 若距上次核验 > 24h → **临门轻核验**（见 §4） | 可探源探，**判死则提示确认（默认仍可打开、不强拦）**；不可探源直接跳 |
| **后台 / admin 全库浏览** | 无时限 | 可展示，但**禁止**写"刚确认/仍在招"字样 |

### 2.2 实现位置

- 时限判断是纯函数，放 `lib/opportunities/freshness.ts`，新增导出：
  ```ts
  export type VerifyTier = "today" | "search" | "admin";
  // 返回该岗在该场景下是否满足核验时限 + 展示用 freshness 标签
  export function meetsVerifyTier(job: Job, tier: VerifyTier, now: Date): {
    ok: boolean;
    freshness: FreshnessState;       // verified | aging | stale | unknown
    checkedAgeHours: number | null;  // 距 enrich_checked_at 的小时数；null=从未核验
  };
  ```
- `enrich_checked_at` 为 NULL（从未核验）的岗：在 `today` tier **一律不进主推荐**（不能假装 verified）。
- 现有 `freshnessState(lastSeenAt, crawlMethod, now)`（`lib/opportunities/freshness.ts`，按 crawl_method 的 SLA + `last_seen_at` → verified/aging/stale/unknown）继续用于"源侧抓取新鲜度"；本 SLA 是叠加在它之上的"逐岗核验新鲜度"，两者都要满足。

### 2.3 与现有引擎对接

- `lib/opportunities/service.ts` 的 `buildOpportunityFeed()` 在硬门阶段增加：`today` tier 岗位必须 `meetsVerifyTier(job, "today", now).ok === true`。
- `/api/jobs/search` 返回的岗位携带 `freshness` + `checkedAgeHours`，前端按 §2.1 显示"待确认"。

---

## 3. 把死岗检测做到"极少漏"（补缺口 A）

### 3.1 新岗优先核验，消灭 7 天盲区

问题：`audit_dead_links.py` 的 `fetch_browser_liveness()` 按 `(source_id, enrich_checked_at NULLS FIRST)` 轮转，但 SPA 源岗位多、单岗 ~3s，6 分片轮转一遍约 7 天 → **刚抓进来的坏岗最长等 7 天才首检**。

要求：

1. **新岗插队优先**：SPA 源新增（`enrich_checked_at IS NULL` 且 `first_seen_at` 在近 48h）的岗，**优先于轮转队列**核验。`fetch_browser_liveness()` 增加可选 `--prioritize-new`，把近 48h 未核验岗排到队头。
2. **展示触发的按需核验**（见 §4.2）作为补充：用户真的要看某 SPA 岗时，按需核验一次，不必等轮转。
3. 调度：`dead-link-audit.yml` 增加一个**高频小批**分支（如每 3–6h 跑一次 `--prioritize-new --limit 300`），只清新岗；原 6 分片全量轮转保留做底盘。

### 3.2 核实自建 SPA 的死亡标记

问题：`audit_dead_links.py` 的 `DEAD_MARKERS` 对自建 SPA（kuaishou/byd/bytedance/google）未逐站核实，可能漏判/误判。

要求：

1. 为每个自建 SPA 源，**人工 live 核实**其"职位已关闭"页面的真实文案/DOM 特征，登记到该源专属的 marker 列表（不要用通用 `DEAD_MARKERS` 一把梭）。
2. 对标记不确定的（`classify()` 返回 `suspect`/`unsure`）**绝不自动判死**，进人工复核队列（保持现有保守行为）。
3. 验收：每个自建 SPA 源至少给出 1 个 live 确认的"已关闭"样例 + 1 个"在招"样例，证明 marker 能区分。

---

## 4. 点击前临门核验（补缺口 C）

> 重要历史教训：**禁止把核验做成阻塞点击路径的同步等待**。曾经"点击门服务端探完再 302"导致点开等 5–8s（云函数冷启动 + 跨区连港库 + 跨区探外网），已废弃。本节的临门核验必须是**短超时、可放行**的。

### 4.1 展示时核验（已存在，扩展覆盖）

- 看板加载后异步批量核验当下可见岗，沿用 `/api/jobs/liveness-check`。
- **扩展**：把 SPA 源也纳入展示时核验，但 SPA 探活走"轻量请求"（见 §4.3），不在请求里起无头浏览器（太慢）。SPA 探不动就返回 `unknown`、不隐藏，交后台审计兜底。

### 4.2 点击时核验（新增，非阻塞体验）

- 用户点"打开官网"时：
  - **可快速探的源（wt/hotjob/workday）**：发起 `checkLiveness()`，**封顶 2.5s**；2.5s 内判死 → 弹"该岗位可能已关闭，仍要打开吗？"，不强拦；判活/未知/超时 → 直接 `window.open(jd_url)`。
  - **不可快速探的源**：直接打开，不等待（后台审计兜底）。
- 实现：点击 handler 先 `livenessSupported(adapter)` 判断；支持则 race(`checkLiveness`, 2.5s timeout)。**默认行为是放行**，核验只用于"判死才提示"。

### 4.3 轻量请求探活（降低 SPA 成本）

- 对 SPA 源，先尝试**最便宜的信号**：HTTP 状态码 / 重定向 / 关键 JSON 接口（很多 SPA 的列表/详情其实有 XHR 接口，不必渲染整页）。
- 只有便宜信号判不出来的，才留给后台无头渲染审计。
- 这条同时服务 §3 和 §6（抓取重构里的"先便宜后昂贵"）。

### 4.4 点击核验 API 契约（新增，区别于批量展示核验）

现有 `/api/jobs/liveness-check` 是**批量展示核验**，只返回该批的 dead id（用于看板隐藏），**不返回单岗 alive/dead/unknown**，不能直接用于点击。点击核验需要一个**单岗**端点：

`POST /api/jobs/[jobId]/liveness`（幂等）
- 鉴权：廉价 cookie 判登录态（同批量端点，不走 getUser）；
- 服务端：取该岗 adapter，`livenessSupported(adapter)` 为真才探，调 `checkLiveness()`，**封顶 2.5s**；
- 返回：`{ ok: true, result: "alive" | "dead" | "unknown" }`；不可探源直接返回 `result:"unknown"`；
- 副作用：判死 → `markJobExpiredById` + 写 `confirmed_closed_at`；判活 → `touchJobCheckedById`；顺带打 `job_liveness_at_click` 事件（见 §5）；
- 失败/超时 → 返回 `result:"unknown"`（**绝不因为探不动就判死**），前端据此直接放行打开。

前端点击 handler：`livenessSupported(adapter)` 为真才调此端点并 race 2.5s，否则直接 `window.open`。**默认放行，判死只提示不强拦**（与 §2.1 表、方向 v3 §2.2 同口径）。

---

## 5. 点击有效率埋点（补缺口 B，核心指标的前提）

### 5.1 为什么必须做

v3 定的信任护栏指标 = "**可探源**点击有效率 ≥99%"（外加覆盖率 / unknown% / SPA 抽检三护栏，见 §5.3）。现在**量不了**（只有 `enrich_checked_at`，没有"点开那刻是否还活"的回收）。不补这个，指标无法验收。

### 5.2 埋点设计

复用现有 `events` 表（`user_id, event, payload, created_at`），新增两类事件：

```text
opportunity_official_opened   # 用户点开官网链接
  payload: { job_id, adapter, checked_age_hours, freshness, surface }
  // surface ∈ today/search/saved；checked_age_hours = 点击时距上次核验小时数

job_liveness_at_click         # 点击后即时核验结果（仅可探源，best-effort）
  payload: { job_id, adapter, result }   // result ∈ alive/dead/unknown
```

- `job_liveness_at_click` 由 §4.2 的点击时核验顺带产生（可探源才有）。
- **payload 禁止**：邮箱、简历、reason_text、完整 JD、带 token 的 URL（沿用现有 events 清洗约定）。

### 5.3 指标口径

```text
可探源点击有效率 = job_liveness_at_click(result=alive) / job_liveness_at_click(result ∈ alive+dead)
```

- 只在"可探源"上算（wt/hotjob/workday 等），分母排除 `unknown`。目标 ≥99%；低于阈值的 adapter 触发告警（见 §7）。
- ⚠️ **"可探源 ≥99%" 会偷窄分母**（最难的 SPA 死岗不进分母）。所以**必须同时报三个护栏，缺一不可**：
  - **点击核验覆盖率** = 有核验结果(alive/dead)的点击 / 总点击（太低说明 99% 没代表性）；
  - **unknown 占比** = result=unknown / 总核验（越高说明越多源探不动）；
  - **SPA 源死岗抽检率** = 定期人工/审计抽样 SPA 源岗位、实测死岗比例（盯住"不可探源"的真实健康）。
- admin/health 看板四个数一起展示 + 按 adapter 拆分。

---

## 6. 运维硬化（让它长期稳）

1. **源级失败自适应**：`enrich_backlog.py` 现按 host 限并发（`per_host=3`）。新增按 adapter 统计本轮 `miss%/expired%`，某源连续高 miss（疑似被限流）→ 自动降 workers 或跳过本轮 + 记 warning（不是默默失败）。
2. **核验覆盖率看板**：`db-report.yml` 增加"按 adapter 的 `enrich_checked_at` 年龄分布"（24h/72h/7d/从未），持续盯 `never_checked` 下降、SPA 源 7d+ 占比下降。
3. **关键提醒不被保鲜误伤**：用户已保存岗位若被判 `expired`，不是静默消失，而是进入 §产品spec 的 `CLOSED_OR_STALE`（"可能已关闭"）提示——保鲜负责发现，产品负责告知。
4. **沿用 expired→purge 回收**：`purge-expired.yml`（02:30 DELETE expired + VACUUM）保留不动。

---

## 7. 验收口径

实现完成后，必须能证明（用真实库，不用 mock）：

1. **分层 SLA 生效**：构造一个 `enrich_checked_at` 为 26h 前的 active 岗 → 不进 `today` 主推荐；同一岗在搜索结果里出现但标"待确认"。
2. **从未核验不冒充 verified**：`enrich_checked_at IS NULL` 的岗，`meetsVerifyTier(..., "today")` 返回 `ok=false`。
3. **新岗优先核验**：近 48h 新增的 SPA 岗，在下一轮 `dead-link-audit --prioritize-new` 中被排到队头（给出 SQL 读回证明）。
4. **点击有效率可算**：触发若干 `opportunity_official_opened` + `job_liveness_at_click`，能从 `events` 聚合出有效率数字，并在 admin/health 显示。
5. **点击不被卡**：点击官网链接，可探源死岗弹提示但仍可点开、活岗/未知秒开（无 5–8s 阻塞）。
6. **不变量未破**：跑现有回归证明 expired sticky / preserve-if-empty / enrich_checked_at 不被列表覆盖 仍成立。

必跑：

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npm run build
git diff --check
```

新增/更新测试（至少）：

```text
tests/freshness-verify-tier.test.js     # meetsVerifyTier 分层 + 从未核验不算 verified
crawler/test_audit_prioritize_new.py    # 新岗插队优先
tests/click-validity-metric.test.js     # 点击有效率聚合口径
```

---

## 8. 明确不做

- 不把核验做成阻塞点击的同步长等待（>2.5s）；
- 不为追求"零死岗"而误杀活岗（拿不准一律放行）；
- 不在本轮重写整个无头渲染框架（先做"新岗优先 + 轻量信号 + 自建源 marker 核实"，渲染框架保持）；
- 不破坏 §0.2 任一不变量。
