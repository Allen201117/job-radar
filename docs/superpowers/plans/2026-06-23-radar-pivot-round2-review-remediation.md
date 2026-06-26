# 个人机会雷达 A–E 第二轮复验阻断修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第二轮复验仍存在的性能、撤销埋点和事件隐私阻断项，并在独立测试 Supabase 上完成 C/E/越权/PII 写类验收。

**Architecture:** 保持 Opportunity Engine 的硬门、4000 候选上限和确定性排序不变。性能修复只减少 4000 行召回结果的跨区载荷，最终入选的少量岗位再按 id 批量回填完整行；动作与事件修复统一遵守“业务写成功后才记录成功事件”和“events 入库前剔除禁用字段”。

**Tech Stack:** Next.js 14、TypeScript、Node test runner、PostgreSQL `pg`、Supabase Auth/PostgREST/RLS。

---

## 1. 审核结论

复验对象：

- Worktree：`/Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623`
- Branch：`draft/radar-pivot-0623`
- HEAD：`405f446`
- 复验日期：`2026-06-23`

结论：**不通过**。

本轮亲测阻断证据：

1. `npx tsx scripts/verify-opportunity-recall.ts` 在第一条正式查询超过 15 秒后退出：

   ```text
   FATAL: canceling statement due to statement timeout
   ```

   未产生三次样本和中位数，已明确不满足合并召回中位 `<=5000ms`。

2. 同 SQL 的服务端诊断：

   ```text
   CLIENT_EXPLAIN_ROUNDTRIP_MS=518
   BitmapOr + jobs_search_doc_gin
   rows=4000
   Planning Time: 1.863 ms
   Execution Time: 230.800 ms
   ```

   SQL plan 正常，当前慢点在 4000 行结果的跨区传输/链路，不得通过提高 timeout 假装关闭。

3. `app/today-client.tsx` 的 `undo()` 在撤销 API 前调用 `track("opportunity_undo")`。本轮顺序检查实际输出：

   ```text
   TRACK_BEFORE_FETCH=true
   TRACK_BEFORE_RESPONSE_CHECK=true
   ```

   检查命令退出码为 1。撤销 API 失败时仍可能写入成功撤销事件。

4. 当前 `.env.local` 没有独立 `TEST_`/`STAGING_` Supabase 变量，且与主仓库环境完全相同。只读 schema 探测：

   ```text
   HAS_RADAR_STATE=false
   HAS_COMPANY_WATCH=false
   HAS_REASON_CODE=false
   HAS_JOB_SNAPSHOT=false
   HAS_ACTION_RPC=false
   ```

   因无法证明现有直连串是测试库，本轮未应用迁移、未写数据。写类 live 仍未验。

5. 事件隐私还有代码级缺口：

   ```text
   components/JobCard.tsx:
   track("job_click", { job_id: job.id, company: job.company })

   components/CompanyInsightDrawer.tsx:
   track("insight_drawer_open", { company })
   ```

   `sanitizePayload()` 当前只保证 JSON 可序列化和大小限制，不会剔除 Spec §13.1 禁止的 `company` 等字段。即使修复调用方，`POST /api/events` 仍接受任意禁用 key。

## 2. 已关闭项：不要重复改写

以下项目已有本轮亲测证据，除非新增测试暴露回归，否则不要重构：

- 行业门：`lib/opportunities/eligibility.ts` 的 `industryState()` 已直接调用 `jobIndustryAllowed()`。
- schema 错误：preferences/radar/job-actions 已复用 `lib/opportunities/schema-errors.ts`；`tests/schema-errors.test.js` 为 `5/5`。
- 截断诚实：jobs store 和 Supabase fallback 均使用“命中 limit 即 capped”的口径。
- 自动化门：Node `453/0`、crawler `409 OK`、tsc 0、build 成功、迁移检查 168、`git diff --check` 通过。

## 3. 硬约束

- 不 push，不 merge main。
- 不打印、复制到报告或提交任何 `.env` 值。
- 未取得明确的独立测试 Supabase 凭据前，不运行 `scripts/db-migrate.sh`，不创建测试用户，不写任何库。
- 不修改 4000 candidate cap，不增加无关 `first_seen_at` 硬窗，不放宽硬门，不用低相关岗位填满。
- 不提高 `statement_timeout`、连接 timeout 或验收阈值来制造 PASS。
- 性能脚本必须继续量取真实结果行，不能改成只跑 `COUNT(*)` 或只贴 EXPLAIN。

## 4. 文件范围

计划修改：

- `app/today-client.tsx`
- `components/JobCard.tsx`
- `components/CompanyInsightDrawer.tsx`
- `lib/track.ts`
- `lib/jobs-store/opportunities.ts`
- `lib/opportunities/service.ts`
- `scripts/verify-opportunity-recall.ts`
- `tests/track.test.js`

计划新增：

- `lib/opportunities/hydration.ts`
- `tests/opportunity-hydration.test.js`
- `tests/opportunity-recall-payload.test.js`
- `tests/today-action-tracking.test.js`

不要修改：

- `lib/opportunities/eligibility.ts`
- `lib/opportunities/schema-errors.ts`
- 迁移 161/162/163
- crawler adapters
- jobs 数据库 schema

---

### Task 1: 修复撤销失败仍记录成功事件

**Files:**

- Modify: `app/today-client.tsx:198-217`
- Create: `tests/today-action-tracking.test.js`

- [ ] **Step 1: 写失败回归测试**

创建 `tests/today-action-tracking.test.js`：

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../app/today-client.tsx"),
  "utf8",
);

test("undo success event is emitted only after the action API succeeds", () => {
  const start = source.indexOf("async function undo()");
  const end = source.indexOf("\n  const order:", start);
  const block = source.slice(start, end);
  const responseCheck = block.indexOf("if (!resp.ok)");
  const successTrack = block.indexOf('track("opportunity_undo"');
  const catchStart = block.indexOf("} catch");

  assert.ok(start >= 0, "undo function missing");
  assert.ok(responseCheck >= 0, "undo response check missing");
  assert.ok(successTrack > responseCheck, "undo event must be after the response success check");
  assert.ok(successTrack < catchStart, "undo event must stay in the success branch");
});
```

- [ ] **Step 2: 验证测试先失败**

Run:

```bash
node --test tests/today-action-tracking.test.js
```

Expected: FAIL，提示 `undo event must be after the response success check`。

- [ ] **Step 3: 最小修改撤销成功分支**

将 `undo()` 调整为：

```ts
async function undo() {
  const t = state.toast;
  if (!t || t.undoFailed) return;
  const jobId = t.jobId;
  clearTimer(jobId);
  dispatch({ type: "undoOptimistic", jobId });
  try {
    const resp = await fetch(`/api/job-actions/${jobId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: null }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    dispatch({ type: "undoCommit", jobId });
    track("opportunity_undo", { previous_action: t.action, surface: "today" });
  } catch {
    dispatch({ type: "undoRollback", jobId });
    setTimeout(() => dispatch({ type: "dismissToast" }), TOAST_MS);
  }
}
```

- [ ] **Step 4: 验证专项测试**

Run:

```bash
node --test tests/today-action-tracking.test.js tests/opportunity-today-reducer.test.js
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交本任务**

```bash
git add app/today-client.tsx tests/today-action-tracking.test.js
git commit -m "fix(radar): track undo only after action succeeds"
```

不要 push。

---

### Task 2: 在 events 入库边界剔除禁用字段

**Files:**

- Modify: `lib/track.ts:59-75`
- Modify: `components/JobCard.tsx:279-285`
- Modify: `components/CompanyInsightDrawer.tsx:119-123`
- Modify: `tests/track.test.js`

- [ ] **Step 1: 给 `sanitizePayload` 增加失败测试**

在 `tests/track.test.js` 增加：

```js
test("sanitizePayload strips forbidden event fields recursively", () => {
  assert.deepEqual(
    T.sanitizePayload({
      job_id: "job-1",
      company: "敏感公司名",
      title: "敏感岗位名",
      jd_url: "https://example.com/job/1",
      reason_text: "自由文本",
      email: "person@example.com",
      user_email: "person@example.com",
      skills: ["secret"],
      nested: {
        resume_text: "resume body",
        job_title: "nested title",
        safe_count: 2,
      },
    }),
    {
      job_id: "job-1",
      nested: { safe_count: 2 },
    },
  );
});
```

- [ ] **Step 2: 验证测试先失败**

Run:

```bash
node --test tests/track.test.js
```

Expected: 新增用例 FAIL，实际 payload 仍包含禁用字段。

- [ ] **Step 3: 在统一 sanitize 边界递归剔除禁用 key**

在 `lib/track.ts` 的 `sanitizePayload()` 前增加：

```ts
const FORBIDDEN_EVENT_PAYLOAD_KEYS = new Set([
  "email",
  "user_email",
  "contact_email",
  "resume",
  "resume_text",
  "raw_resume",
  "reason_text",
  "title",
  "job_title",
  "company",
  "company_name",
  "jd_url",
  "skills",
]);

function stripForbiddenPayloadFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripForbiddenPayloadFields);
  }
  if (value == null || typeof value !== "object") {
    return value;
  }

  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    const normalized = key.trim().toLowerCase().replace(/[\s-]+/g, "_");
    if (FORBIDDEN_EVENT_PAYLOAD_KEYS.has(normalized)) continue;
    out[key] = stripForbiddenPayloadFields(item);
  }
  return out;
}
```

将 `sanitizePayload()` 中的 JSON 处理改为先解析、再剔除、最后做大小检查：

```ts
export function sanitizePayload(payload: unknown): Record<string, unknown> {
  if (payload == null || typeof payload !== "object" || Array.isArray(payload)) {
    return {};
  }
  try {
    const serializable = JSON.parse(JSON.stringify(payload));
    const safe = stripForbiddenPayloadFields(serializable);
    if (safe == null || typeof safe !== "object" || Array.isArray(safe)) return {};
    if (JSON.stringify(safe).length > MAX_PAYLOAD_BYTES) return {};
    return safe as Record<string, unknown>;
  } catch {
    return {};
  }
}
```

- [ ] **Step 4: 删除已知调用方的公司名传输**

`components/JobCard.tsx`：

```ts
else track("job_click", { job_id: job.id });
```

`components/CompanyInsightDrawer.tsx`：

```ts
track("insight_drawer_open");
```

- [ ] **Step 5: 验证事件专项测试**

Run:

```bash
node --test tests/track.test.js tests/resume-tracking.test.js
```

Expected: 全部 PASS；resume diagnostics 的允许字段保持不变。

- [ ] **Step 6: 提交本任务**

```bash
git add lib/track.ts components/JobCard.tsx components/CompanyInsightDrawer.tsx tests/track.test.js
git commit -m "fix(events): strip forbidden payload fields"
```

不要 push。

---

### Task 3: 缩小 4000 行召回载荷并回填完整岗位

**Files:**

- Create: `lib/opportunities/hydration.ts`
- Create: `tests/opportunity-hydration.test.js`
- Create: `tests/opportunity-recall-payload.test.js`
- Modify: `lib/jobs-store/opportunities.ts:27-32`
- Modify: `lib/opportunities/service.ts:57-74`
- Modify: `scripts/verify-opportunity-recall.ts:37-42`

- [ ] **Step 1: 为最终岗位完整回填写失败测试**

创建 `lib/opportunities/hydration.ts` 的测试 `tests/opportunity-hydration.test.js`：

```js
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { hydrateOpportunityJobs } = loadOpp("hydration");

function opportunity(id, summary = "short") {
  return {
    job: { id, summary, jd_url: "", salary_text: null },
    score: 80,
    tier: "high",
    reasons: [],
    freshness: "verified",
    firstSeenAt: null,
    lastSeenAt: null,
    userAction: null,
    viewed: false,
    isNew: false,
    exploreEligible: false,
  };
}

test("hydrateOpportunityJobs replaces selected recall rows with complete jobs", () => {
  const selected = opportunity("job-1");
  const sections = { new: [selected], priority: [], explore: [], aging: [] };
  const full = {
    id: "job-1",
    summary: "完整岗位正文",
    jd_url: "https://official.example/job-1",
    salary_text: "30-40K",
    deadline: "2026-07-01",
  };

  hydrateOpportunityJobs(sections, [full]);

  assert.equal(selected.job.summary, "完整岗位正文");
  assert.equal(selected.job.jd_url, "https://official.example/job-1");
  assert.equal(selected.job.salary_text, "30-40K");
  assert.equal(selected.job.deadline, "2026-07-01");
});

test("hydrateOpportunityJobs leaves a candidate unchanged when the full row is absent", () => {
  const selected = opportunity("missing", "candidate summary");
  const sections = { new: [selected], priority: [], explore: [], aging: [] };

  hydrateOpportunityJobs(sections, []);

  assert.equal(selected.job.summary, "candidate summary");
});
```

- [ ] **Step 2: 验证测试先失败**

Run:

```bash
node --test tests/opportunity-hydration.test.js
```

Expected: FAIL，模块或导出不存在。

- [ ] **Step 3: 实现纯回填函数**

创建 `lib/opportunities/hydration.ts`：

```ts
import type { FeedSections, Job } from "./types";

export function hydrateOpportunityJobs(sections: FeedSections, rows: Job[]): void {
  const fullById = new Map(rows.map((row) => [row.id, row]));
  const opportunities = [
    ...sections.new,
    ...sections.priority,
    ...sections.explore,
    ...sections.aging,
  ];

  for (const opportunity of opportunities) {
    const full = fullById.get(opportunity.job.id);
    if (full) opportunity.job = full;
  }
}
```

- [ ] **Step 4: 把 service 改为完整行回填**

在 `lib/opportunities/service.ts` 引入：

```ts
import { hydrateOpportunityJobs } from "./hydration";
```

将 `hydrateFullSummaries()` 改为：

```ts
async function hydrateDisplayJobs(sections: FeedSections): Promise<void> {
  if (!jobsStoreEnabled()) return;
  const all = [...sections.new, ...sections.priority, ...sections.explore, ...sections.aging];
  const ids = all.map((o) => o.job.id).filter(Boolean);
  if (!ids.length) return;
  try {
    const rows = await jobsByIds(ids, false);
    hydrateOpportunityJobs(sections, rows);
  } catch (e) {
    console.warn("[opportunities] display-job hydrate failed:", (e as Error).message);
  }
}
```

并将调用改为：

```ts
await hydrateDisplayJobs(sections);
```

- [ ] **Step 5: 为召回列写契约测试**

创建 `tests/opportunity-recall-payload.test.js`：

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../lib/jobs-store/opportunities.ts"),
  "utf8",
);

test("opportunity recall transfers only engine-required candidate fields", () => {
  const start = source.indexOf("const RECALL_COLUMNS");
  const end = source.indexOf("\n\nfunction roleTsquery", start);
  const columns = source.slice(start, end);

  for (const required of [
    "id",
    "source_id",
    "company",
    "title",
    "location",
    "job_type",
    "summary",
    "jd_url",
    "salary_text",
    "first_seen_at",
    "last_seen_at",
    "status",
    "education",
  ]) {
    assert.ok(columns.includes(required), `missing engine field: ${required}`);
  }

  for (const displayOnly of [
    "apply_url",
    "posted_at",
    "content_hash",
    "created_at",
    "experience",
    "deadline",
    "enrich_fail_count",
    "enrich_checked_at",
    "canonical_jd_url",
  ]) {
    assert.ok(!columns.includes(displayOnly), `recall still transfers display field: ${displayOnly}`);
  }
});
```

- [ ] **Step 6: 缩小 recall projection**

将 `lib/jobs-store/opportunities.ts` 的 `RECALL_COLUMNS` 改为：

```ts
const RECALL_COLUMNS =
  "id, source_id, company, title, location, job_type, " +
  `left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, salary_text, first_seen_at, last_seen_at, status, education";
```

这些字段覆盖当前硬门和打分所需数据；展示用 `apply_url/posted_at/deadline/...` 由 Step 4 对最终少量卡片回填。

- [ ] **Step 7: 同步真实性能脚本**

将 `scripts/verify-opportunity-recall.ts` 的 `COLS` 改为相同 projection：

```ts
const COLS =
  `id, source_id, company, title, location, job_type, left(btrim(summary), ${SUMMARY_TRUNC}) as summary, ` +
  "jd_url, salary_text, first_seen_at, last_seen_at, status, education";
```

在每次查询后记录实际 payload 大小，但不要打印行内容：

```ts
let lastPayloadBytes = 0;
// ...
lastPayloadBytes = Buffer.byteLength(JSON.stringify(r.rows), "utf8");
// ...
console.log(`payload_bytes=${lastPayloadBytes}`);
```

- [ ] **Step 8: 跑纯代码专项测试**

Run:

```bash
node --test tests/opportunity-hydration.test.js tests/opportunity-recall-payload.test.js tests/opportunity-eligibility.test.js tests/opportunity-scoring.test.js tests/opportunity-grouping.test.js
npx tsc --noEmit
```

Expected: 全部 PASS，tsc 退出码 0。

- [ ] **Step 9: 跑真实性能门**

Run:

```bash
set -a
source .env.local
set +a
npx tsx scripts/verify-opportunity-recall.ts
```

Expected:

```text
三次耗时(ms)：...
中位 ...ms
rows=4000
candidate_capped=true
合并召回 <=5000ms：PASS
```

如果仍 FAIL：

1. 贴同 SQL 的 `EXPLAIN (ANALYZE, BUFFERS)`；
2. 若服务端仍约数百毫秒而完整取数 `>5000ms`，停止继续改匹配代码；
3. 将剩余问题归为部署区与数据库跨区链路，要求决定 Vercel region 或 PostgreSQL pooler；
4. 不得提高 timeout，不得降低 4000 cap，不得声称性能项关闭。

- [ ] **Step 10: 仅在性能脚本真实 PASS 后提交**

```bash
git add lib/jobs-store/opportunities.ts lib/opportunities/service.ts lib/opportunities/hydration.ts scripts/verify-opportunity-recall.ts tests/opportunity-hydration.test.js tests/opportunity-recall-payload.test.js
git commit -m "perf(radar): reduce recall payload and hydrate selected jobs"
```

不要 push。

---

### Task 4: 完整回归门

**Files:**

- Verify only

- [ ] **Step 1: 按顺序运行全部门**

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npx tsc --noEmit
npm run build
bash scripts/check-migrations.sh
git diff --check
```

Expected:

- Node：新总数应大于 453，`fail 0`
- crawler：`Ran 409 tests`、`OK`
- tsc：退出码 0
- build：`Compiled successfully`
- migrations：`168 个迁移文件`
- diff check：无输出、退出码 0

- [ ] **Step 2: 检查代码范围**

```bash
git status --short
git diff --stat 405f446
git log --oneline -10
```

Expected: 只出现本报告 §4 列出的文件和新增测试，不出现 `.env*`、迁移、crawler 或 jobs schema 改动。

---

### Task 5: 使用独立测试 Supabase 完成写类 live

**Files:**

- Test environment only
- Do not commit `.env.local`

- [ ] **Step 1: 确认独立测试变量齐全**

只允许使用以下独立变量：

```bash
test -n "$TEST_SUPABASE_DB_URL"
test -n "$TEST_SUPABASE_URL"
test -n "$TEST_SUPABASE_ANON_KEY"
test -n "$TEST_SUPABASE_SERVICE_ROLE_KEY"
```

任一缺失立即停止，报告“写类未验”；不得回退使用当前 `.env.local` 的通用 Supabase 凭据。

- [ ] **Step 2: 向测试库应用全部迁移**

```bash
SUPABASE_DB_URL="$TEST_SUPABASE_DB_URL" bash scripts/db-migrate.sh
```

Expected: 001–163 按序完成，无迁移错误。

- [ ] **Step 3: 使用 shell 覆盖启动测试环境**

保持 `.env.local` 不变：

```bash
NEXT_PUBLIC_SUPABASE_URL="$TEST_SUPABASE_URL" \
NEXT_PUBLIC_SUPABASE_ANON_KEY="$TEST_SUPABASE_ANON_KEY" \
SUPABASE_URL="$TEST_SUPABASE_URL" \
SUPABASE_SERVICE_ROLE_KEY="$TEST_SUPABASE_SERVICE_ROLE_KEY" \
npm run dev
```

`JOBS_DATABASE_URL` 继续来自 `.env.local`，只读香港真实岗位。

- [ ] **Step 4: 完成基线手册写类流程**

逐条取得真实 DB read-back：

1. 值得投、已投递、不适合、撤销、失败回滚；
2. 同岗快速连点只产生一次动作请求；
3. 撤销 API 失败时 UI 重新移出，且 events 无 `opportunity_undo` 成功行；
4. 已覆盖公司写入 `covered` 且 `matched_source_ids` 非空；
5. 未覆盖公司写入 `queued`；
6. 管理员无 enabled source 时不能标 covered；
7. 用户 A 无法读取或修改用户 B 的请求和动作；
8. 极宽画像命中 4000 行时 `candidate_capped=true`；
9. 缺表/缺 RPC 环境分别返回 `coverage_schema_unavailable`、`radar_schema_unavailable`、`action_schema_unavailable`。

- [ ] **Step 5: 查询新写 events 的禁用字段**

在测试库只读执行：

```sql
select id, event, payload
from public.events
where created_at >= now() - interval '1 hour'
  and payload::text ~* '"(email|user_email|contact_email|resume|resume_text|raw_resume|reason_text|title|job_title|company|company_name|jd_url|skills)"[[:space:]]*:';
```

Expected: `0 rows`。

再确认撤销失败没有成功事件：

```sql
select count(*) as false_success_undo_events
from public.events
where event = 'opportunity_undo'
  and created_at >= now() - interval '10 minutes';
```

该计数必须与实际成功撤销次数完全一致；人为失败的撤销不能增加计数。

---

## 5. 最终复验回报模板

修复 agent 不得只回“已完成”。必须提供：

1. 每条自动化门的实际测试数、退出码和关键输出；
2. 性能三次样本、中位数、rows、payload bytes、PASS/FAIL；
3. FAIL 时的 EXPLAIN planning/execution time 与 plan 节点；
4. 测试库迁移是否应用、测试项目标识的非敏感说明；
5. C/E/越权/events PII 每项真实 read-back；
6. `git status --short` 与 `git log --oneline -10`；
7. 明确声明未 push、未 merge、未修改或提交 `.env`。

只有性能真实 PASS、撤销失败不记成功事件、events 禁用字段查询为 0 行、写类 live 全部完成，才可申请下一轮通过判定。
