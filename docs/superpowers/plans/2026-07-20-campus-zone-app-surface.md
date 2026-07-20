# 校招专区 · 应用层（P1 Surface）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一个新一级页面 `/campus`「校招专区」，按用户行业锁定必投清单公司，聚合其"已接入官方校招源且持续验证"的校招岗，用诚实的窗口徽章呈现。

**Architecture:** 纯函数 `lib/campus-zone.ts`（准入门/窗口态/排序/归组，node 可测、无 LLM/DB/网络）→ 读查询 `getCampusZone`（香港库聚合校招岗）+ `getCampusSourceCoverage`（Supabase 源覆盖）→ SSR 页 `app/campus/` 装配渲染 → client 组件做筛选/展开/展示时探活。分类复用现成 `recruitmentCategory`（精度优先，弱词不判校招）。

**Tech Stack:** Next.js 15 App Router + React 18 + TypeScript；jobs 在自建香港 Postgres（`lib/jobs-store`）；sources 在 Supabase；node --test（纯函数）。

## Global Constraints

- Node `^18.18.0 || ^19.8.0 || >=20.0.0`；前端 npm，不引重型依赖。
- jobs 读一律走 `lib/jobs-store`（gated：配 `JOBS_DATABASE_URL` 用香港库，否则回退 Supabase）；sources 永远走 Supabase。
- force-dynamic 数据页**必须**配 `loading.tsx`（冷启动规范），互不依赖的服务端 `await` 用 `Promise.all` 并行。
- 页面取当前用户走 `lib/auth.getRequestUser()`，不在页面里调 `supabase.auth.getUser()`。
- 纯函数被 node --test 测试时 import 用**相对路径**（不能 `@/`）。
- **`.ts` lib 的测试机制（项目既定）**：`.ts` lib（如 `insight-derive.ts`）不能被 `node --test` 原生 `require`；必须走转译 shim `tests/_load-ts.js`：`const { loadTs } = require("./_load-ts"); const M = loadTs(path.join(__dirname, "..", "lib", "campus-zone.ts"));`。`campus-zone.ts` 本身用纯 ESM `export`/`export type`（**不写 `module.exports`**）；它 `import { recruitmentCategory } from "./china-keyword-expansion"`（shim 的 customRequire 会把 `.js` 依赖走原生 require）。
- 诚实文案红线：页面统一口径"**已接入官方校招源并持续验证的岗位**"，禁止出现"全部校招岗"。窗口态只陈述事实，不推断"提前批"。
- P1 徽章**不用 LLM、不做 first_seen 突增判断**（🔥 留 P2）。

---

### Task 1: 校招准入门 `campusAdmission`

**Files:**
- Create: `lib/campus-zone.ts`
- Test: `tests/campus-zone.test.js`

**Interfaces:**
- Consumes: `recruitmentCategory(job)` from `lib/china-keyword-expansion.js`（返回 `"校招" | "实习" | "社招"`，精度优先）。
- Produces: `campusAdmission(job): "campus" | "intern" | "reject"` —— 专区准入判定。`"campus"` 进默认列表，`"intern"` 单独可筛桶，`"reject"` 不进专区。

- [ ] **Step 1: 写失败测试**

```javascript
// tests/campus-zone.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
// 一次性 loadTs 加载 campus-zone.ts；后续任务只需在本行解构补上新函数名。
const { campusAdmission, windowStatus, compareCampusJobs, compareCompanyCards, groupCampusJobs } =
  loadTs(path.join(__dirname, "..", "lib", "campus-zone.ts"));

test("campusAdmission: 强校招信号 → campus", () => {
  assert.equal(campusAdmission({ title: "2027届校园招聘-后端工程师", job_type: "校招" }), "campus");
  assert.equal(campusAdmission({ title: "管培生", jd_url: "https://x.com/campus/1" }), "campus");
});

test("campusAdmission: 实习单独成桶，不混校招", () => {
  assert.equal(campusAdmission({ title: "暑期实习-数据分析", job_type: "实习" }), "intern");
});

test("campusAdmission: 社招/弱词/无信号 → reject（精度优先，宁漏勿误）", () => {
  assert.equal(campusAdmission({ title: "高级后端工程师", job_type: "社招" }), "reject");
  assert.equal(campusAdmission({ title: "后端工程师（毕业生优先）" }), "reject"); // 弱词不判校招
  assert.equal(campusAdmission({ title: "资深架构师", summary: "8年经验", job_type: "校招" }), "reject"); // ≥2年经验强制社招
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/campus-zone.test.js`
Expected: FAIL（`campusAdmission is not a function` / Cannot find module）

- [ ] **Step 3: 写最小实现**

```typescript
// lib/campus-zone.ts
// 校招专区纯函数：准入门 / 窗口态 / 排序 / 归组。无 LLM、无网络、无 DB —— 纯输入输出，独立可测。
// 纯 ESM export（不写 module.exports）；测试经 tests/_load-ts.js 转译加载（见 Global Constraints）。
import { recruitmentCategory } from "./china-keyword-expansion";

export type CampusAdmission = "campus" | "intern" | "reject";

// 专区准入门：直接复用 recruitmentCategory（已精度优先，弱词不判校招）。
// campus = 进默认列表；intern = 单独可筛桶；reject = 不进专区（社招/无信号）。
export function campusAdmission(job: any = {}): CampusAdmission {
  const cat = recruitmentCategory(job);
  if (cat === "实习") return "intern";
  if (cat === "校招") return "campus";
  return "reject";
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/campus-zone.test.js`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add lib/campus-zone.ts tests/campus-zone.test.js
git commit -m "feat(campus): 校招准入门 campusAdmission（复用 recruitmentCategory 精度优先）"
```

---

### Task 2: 窗口状态 `windowStatus`（诚实三态 + 新鲜度降级 + 子原因）

**Files:**
- Modify: `lib/campus-zone.ts`
- Test: `tests/campus-zone.test.js`

**Interfaces:**
- Produces: `windowStatus(input): WindowState`，其中
  ```ts
  type WindowState = { state: "hiring" | "no_campus_now" | "not_ingested" | "stale"; subReason?: "no_source" | "source_only_social" | "crawl_error" };
  interface WindowInput {
    campusJobCount: number;      // 通过准入门的在招校招岗数
    hasCampusSource: boolean;    // Supabase 里是否有该公司校招板块源
    hasAnySource: boolean;       // 是否有该公司任意源
    lastSeenAtMs: number | null; // 该公司岗位最近 last_seen_at（毫秒），null=从无
    nowMs: number;               // 当前时间（调用方传入，纯函数不取 Date.now）
    freshnessThresholdMs?: number; // 默认 72h
  }
  ```

- [ ] **Step 1: 写失败测试**

```javascript
// windowStatus 已在文件头 loadTs 解构导入（见 Task 1 测试头）。
const H = 3600 * 1000;

test("windowStatus: 有在招校招岗且新鲜 → hiring", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 12, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 2 * H }),
    { state: "hiring" }
  );
});

test("windowStatus: 有源但当前无校招岗 → no_campus_now（不等于没开）", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 2 * H }),
    { state: "no_campus_now" }
  );
});

test("windowStatus: 无源 → not_ingested + 子原因", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: false, hasAnySource: false, lastSeenAtMs: null, nowMs: 1000 * H }),
    { state: "not_ingested", subReason: "no_source" }
  );
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: false, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H }),
    { state: "not_ingested", subReason: "source_only_social" }
  );
});

test("windowStatus: 有校招岗但源太久没抓 → stale（不冒充 hiring）", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 5, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 100 * H }),
    { state: "stale" }
  );
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/campus-zone.test.js`
Expected: FAIL（`windowStatus is not a function`）

- [ ] **Step 3: 写实现**

```javascript
// 追加到 lib/campus-zone.ts
export type WindowState = {
  state: "hiring" | "no_campus_now" | "not_ingested" | "stale";
  subReason?: "no_source" | "source_only_social" | "crawl_error";
};

const DEFAULT_FRESHNESS_MS = 72 * 3600 * 1000;

export function windowStatus(input: any): WindowState {
  const { campusJobCount, hasCampusSource, hasAnySource, lastSeenAtMs, nowMs } = input;
  const threshold = input.freshnessThresholdMs || DEFAULT_FRESHNESS_MS;

  // 无校招源 → 诚实告知待接入（区分尚未接入 / 只接了社招）。
  if (!hasCampusSource) {
    return { state: "not_ingested", subReason: hasAnySource ? "source_only_social" : "no_source" };
  }
  // 有校招源但数据太旧 → 降级，不拿旧数据冒充在招。
  if (lastSeenAtMs != null && nowMs - lastSeenAtMs > threshold) {
    return { state: "stale" };
  }
  if (campusJobCount > 0) return { state: "hiring" };
  return { state: "no_campus_now" };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/campus-zone.test.js`
Expected: PASS（7 tests）

- [ ] **Step 5: 提交**

```bash
git add lib/campus-zone.ts tests/campus-zone.test.js
git commit -m "feat(campus): windowStatus 诚实三态+新鲜度降级+待接入子原因"
```

---

### Task 3: 排序 `compareCampusJobs` + `compareCompanyCards`（按"别错过"）

**Files:**
- Modify: `lib/campus-zone.ts`
- Test: `tests/campus-zone.test.js`

**Interfaces:**
- Produces:
  - `compareCampusJobs(a, b): number` —— 有明确截止的按截止升序在前，无截止的按 first_seen 降序在后。
  - `compareCompanyCards(a, b): number` —— 卡排序：hiring 优先（按最临近已知截止升序）→ no_campus_now → stale → not_ingested。
  - `WINDOW_ORDER: Record<WindowState["state"], number>`

- [ ] **Step 1: 写失败测试**

```javascript
// compareCampusJobs / compareCompanyCards 已在文件头 loadTs 解构导入。
test("compareCampusJobs: 有截止的排前（临近优先），无截止的按新增降序在后", () => {
  const soon = { deadline: "2026-08-01", first_seen_at: "2026-07-01" };
  const later = { deadline: "2026-09-01", first_seen_at: "2026-07-10" };
  const noDeadlineNew = { deadline: null, first_seen_at: "2026-07-18" };
  const noDeadlineOld = { deadline: null, first_seen_at: "2026-07-02" };
  const sorted = [noDeadlineOld, later, noDeadlineNew, soon].sort(compareCampusJobs);
  assert.deepEqual(sorted.map((j) => j.deadline || j.first_seen_at),
    ["2026-08-01", "2026-09-01", "2026-07-18", "2026-07-02"]);
});

test("compareCompanyCards: hiring 在 no_campus_now / not_ingested 之前", () => {
  const hiring = { window: { state: "hiring" }, nearestDeadlineMs: 100 };
  const noCampus = { window: { state: "no_campus_now" }, nearestDeadlineMs: null };
  const notIngested = { window: { state: "not_ingested" }, nearestDeadlineMs: null };
  const sorted = [notIngested, noCampus, hiring].sort(compareCompanyCards);
  assert.deepEqual(sorted.map((c) => c.window.state), ["hiring", "no_campus_now", "not_ingested"]);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/campus-zone.test.js`
Expected: FAIL

- [ ] **Step 3: 写实现**

```javascript
// 追加到 lib/campus-zone.ts
function ms(x: any): number | null {
  if (!x) return null;
  const t = Date.parse(x);
  return Number.isNaN(t) ? null : t;
}

export function compareCampusJobs(a: any, b: any): number {
  const da = ms(a.deadline), db = ms(b.deadline);
  if (da != null && db != null) return da - db;   // 都有截止 → 临近优先
  if (da != null) return -1;                       // 有截止的排前
  if (db != null) return 1;
  const fa = ms(a.first_seen_at) || 0, fb = ms(b.first_seen_at) || 0;
  return fb - fa;                                   // 都无截止 → 新增降序
}

export const WINDOW_ORDER: Record<string, number> = {
  hiring: 0, no_campus_now: 1, stale: 2, not_ingested: 3,
};

export function compareCompanyCards(a: any, b: any): number {
  const oa = WINDOW_ORDER[a.window.state], ob = WINDOW_ORDER[b.window.state];
  if (oa !== ob) return oa - ob;
  const na = a.nearestDeadlineMs, nb = b.nearestDeadlineMs;
  if (na != null && nb != null) return na - nb;
  if (na != null) return -1;
  if (nb != null) return 1;
  return 0;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/campus-zone.test.js`
Expected: PASS（9 tests）

- [ ] **Step 5: 提交**

```bash
git add lib/campus-zone.ts tests/campus-zone.test.js
git commit -m "feat(campus): 排序 compareCampusJobs/compareCompanyCards（临近截止优先）"
```

---

### Task 4: 同公司多批次/城市归组 `groupCampusJobs`

**Files:**
- Modify: `lib/campus-zone.ts`
- Test: `tests/campus-zone.test.js`

**Interfaces:**
- Produces: `groupCampusJobs(jobs): { key: string; label: string; jobs: any[] }[]` —— 按城市分组（无城市归"不限/其他"），组内用 `compareCampusJobs` 排序，组按岗位数降序。

- [ ] **Step 1: 写失败测试**

```javascript
// groupCampusJobs 已在文件头 loadTs 解构导入。
test("groupCampusJobs: 按城市归组，组内排序，组按岗位数降序", () => {
  const jobs = [
    { title: "A", city: "北京", deadline: "2026-08-10", first_seen_at: "2026-07-01" },
    { title: "B", city: "上海", deadline: null, first_seen_at: "2026-07-05" },
    { title: "C", city: "北京", deadline: "2026-08-01", first_seen_at: "2026-07-02" },
  ];
  const groups = groupCampusJobs(jobs);
  assert.equal(groups[0].label, "北京");
  assert.deepEqual(groups[0].jobs.map((j) => j.title), ["C", "A"]); // 8-01 早于 8-10
  assert.equal(groups[1].label, "上海");
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/campus-zone.test.js`
Expected: FAIL

- [ ] **Step 3: 写实现**

```javascript
// 追加到 lib/campus-zone.ts
export function groupCampusJobs(jobs: any[]): any[] {
  const buckets = new Map<string, any[]>();
  for (const j of jobs || []) {
    const key = (j.city || "").trim() || "其他";
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(j);
  }
  const groups = Array.from(buckets.entries()).map(([key, gj]) => ({
    key, label: key, jobs: gj.slice().sort(compareCampusJobs),
  }));
  groups.sort((a, b) => b.jobs.length - a.jobs.length);
  return groups;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/campus-zone.test.js`
Expected: PASS（10 tests）

- [ ] **Step 5: 提交**

```bash
git add lib/campus-zone.ts tests/campus-zone.test.js
git commit -m "feat(campus): groupCampusJobs 同公司按城市归组"
```

---

### Task 5: 香港库读查询 `getCampusZone`

**Files:**
- Modify: `lib/jobs-store/read.ts`
- Test: 手动 live 验证（连香港库，见步骤）

**Interfaces:**
- Consumes: `jobsQuery`（已有）、`campusAdmission`（Task 1）。
- Produces:
  ```ts
  export type CampusCompanyRow = {
    company: string;          // 必投清单展示名
    pattern: string;
    campusJobs: any[];        // 通过准入门 campus 的在招岗（含 id/title/job_type/jd_url/apply_url/summary/deadline/first_seen_at/last_seen_at/city/education）
    internJobs: any[];        // intern 桶
    hasAnyActiveJob: boolean; // 该公司任意在招岗（判 source_only_social）
    lastSeenAtMs: number | null;
  };
  export async function getCampusZone(list: Array<{ name: string; pattern: string }>): Promise<CampusCompanyRow[]>;
  ```

- [ ] **Step 1: 写实现**

```ts
// 追加到 lib/jobs-store/read.ts（import 处加 campusAdmission）
import { campusAdmission } from "@/lib/campus-zone";

export type CampusCompanyRow = {
  company: string; pattern: string;
  campusJobs: any[]; internJobs: any[];
  hasAnyActiveJob: boolean; lastSeenAtMs: number | null;
};

/**
 * 校招专区：按必投清单公司聚合校招/实习岗。
 * SQL 先按 pattern 粗筛校招相关岗（缩小行数），JS 用 campusAdmission 精筛入桶。
 * 一次 unnest join 覆盖该行业 ~30 家；行数=这些公司的校招相关岗，实测数百，秒级。
 */
export async function getCampusZone(list: Array<{ name: string; pattern: string }>): Promise<CampusCompanyRow[]> {
  const names = list.map((c) => c.name);
  const pats = list.map((c) => c.pattern);
  const rows = await jobsQuery<any>(
    `
    select t.name as company_key, t.pat,
      j.id, j.company, j.title, j.job_type, j.jd_url, j.apply_url, j.summary,
      j.deadline, j.first_seen_at, j.last_seen_at, j.city, j.education, j.status
    from unnest($1::text[], $2::text[]) as t(name, pat)
    left join jobs j on j.status = 'active' and j.company ilike t.pat
      and (
        coalesce(j.job_type,'') ~ '校|campus|应届|管培|培训生|graduate|new.?grad|实习|intern'
        or coalesce(j.title,'') ~ '校|应届|届|管培|培训生|graduate|campus|new.?grad|实习|intern'
        or coalesce(j.jd_url,'') ~ '/(xiaozhao|campus|shixi|intern)(/|\\?|$)'
      )
    `,
    [names, pats],
  );
  const byName = new Map<string, CampusCompanyRow>();
  for (const c of list) byName.set(c.name, {
    company: c.name, pattern: c.pattern, campusJobs: [], internJobs: [], hasAnyActiveJob: false, lastSeenAtMs: null,
  });
  for (const r of rows) {
    const agg = byName.get(r.company_key);
    if (!agg || !r.id) continue;
    agg.hasAnyActiveJob = true;
    const seen = r.last_seen_at ? Date.parse(r.last_seen_at) : NaN;
    if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs || 0, seen);
    const bucket = campusAdmission(r);
    if (bucket === "campus") agg.campusJobs.push(r);
    else if (bucket === "intern") agg.internJobs.push(r);
  }
  return list.map((c) => byName.get(c.name)!);
}
```

> 注：`hasAnyActiveJob` 只反映"校招相关粗筛"里有没有岗；纯社招公司在此为 false，其"有社招无校招"由 Task 6 的 source 覆盖判 `source_only_social`。若需严格"任意在招岗"，可复用 `getCompanyActiveAggregates()` 的 activeTotal 合并（Task 7 装配时用它兜底 `hasAnySource` 的判断）。

- [ ] **Step 2: Live 验证（连香港库）**

先起一个临时脚本验证返回结构（需 `.env.local` 的 `JOBS_DATABASE_URL`；沙箱连库见 [[job-radar-live-db-access-from-sandbox]]）：

```bash
# 用互联网/科技行业的 pattern 测（该行业校招覆盖最好）
node -e "require('ts-node/register'); const {getCampusZone}=require('./lib/jobs-store/read.ts'); const {MUST_APPLY_BY_INDUSTRY}=require('./lib/must-apply-list.ts'); getCampusZone(MUST_APPLY_BY_INDUSTRY['互联网/科技']).then(r=>console.log(r.map(c=>[c.company,c.campusJobs.length,c.internJobs.length])));"
```
Expected: 打印 ~30 家 [公司, 校招岗数, 实习岗数]，字节/腾讯/阿里等 campus 数 >0。

> 若项目无 ts-node，改在 Task 7 页面接好后用 preview 验证；此步可跳过并在 Task 7 一并验证。

- [ ] **Step 3: 提交**

```bash
git add lib/jobs-store/read.ts
git commit -m "feat(campus): getCampusZone 香港库聚合校招/实习岗（SQL 粗筛+JS精筛）"
```

---

### Task 6: 校招源覆盖 `getCampusSourceCoverage`（Supabase）

**Files:**
- Create: `lib/campus-sources.ts`
- Test: 手动 live 验证

**Interfaces:**
- Produces:
  ```ts
  export type CampusSourceInfo = { hasAnySource: boolean; hasCampusSource: boolean };
  // 返回 pattern → CampusSourceInfo；hasCampusSource = 有该公司且 URL/notes 命中校招板块特征。
  export async function getCampusSourceCoverage(list: Array<{ name: string; pattern: string }>): Promise<Map<string, CampusSourceInfo>>;
  ```

- [ ] **Step 1: 写实现**

```ts
// lib/campus-sources.ts
import { createServiceClient } from "@/lib/supabaseService";

export type CampusSourceInfo = { hasAnySource: boolean; hasCampusSource: boolean };

const CAMPUS_URL_RE = /campus|xiaozhao|校招|校园|campus_apply|\/campus/i;

// 判一条源是否是"校招板块"源：URL 命中 campus 特征，或 notes/source_url 标注校招。
function isCampusSource(url: string, notes: string): boolean {
  return CAMPUS_URL_RE.test(url) || CAMPUS_URL_RE.test(notes);
}

export async function getCampusSourceCoverage(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, CampusSourceInfo>> {
  const { data, error } = await createServiceClient().from("sources").select("company, source_url, notes, enabled");
  if (error) throw new Error(error.message);
  const sources = (data || []) as Array<{ company: string | null; source_url: string | null; notes: string | null; enabled: boolean }>;
  const out = new Map<string, CampusSourceInfo>();
  for (const c of list) {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    const matched = sources.filter((s) => (s.company || "").toLowerCase().includes(needle) && s.enabled);
    const hasAnySource = matched.length > 0;
    const hasCampusSource = matched.some((s) => isCampusSource(s.source_url || "", s.notes || ""));
    out.set(c.pattern, { hasAnySource, hasCampusSource });
  }
  return out;
}
```

> ⚠️ `sources` 表 >1000 行会被 PostgREST 单次查询截断（见 [[job-radar-must-apply-multi-industry]]）。若上线时 sources 已过千，改用 `.range()` 分页拉全，与 `app/admin/health/page.tsx` 现有拉法对齐。实现时先 `select count` 确认行数决定是否分页。

- [ ] **Step 2: Live 验证行数与命中**

```bash
# 确认 sources 行数（决定是否要分页）
psql "$SUPABASE_DB_URL" -A -t -c "select count(*) from sources;"
# 抽查校招源命中：字节应有 campus 源
psql "$SUPABASE_DB_URL" -A -t -c "select company, source_url from sources where source_url ~ 'campus|xiaozhao' limit 5;"
```
Expected: 行数已知（若 >1000 按注释改分页）；campus 源抽查有结果。

- [ ] **Step 3: 提交**

```bash
git add lib/campus-sources.ts
git commit -m "feat(campus): getCampusSourceCoverage 判各公司校招板块源覆盖"
```

---

### Task 7: `/campus` SSR 页 + loading 骨架 + 装配

**Files:**
- Create: `app/campus/page.tsx`, `app/campus/loading.tsx`
- Reference: `app/path/page.tsx`, `app/path/loading.tsx`（照抄结构）

**Interfaces:**
- Consumes: `getRequestUser`、`resolveMustApplyIndustries`、`MUST_APPLY_BY_INDUSTRY`、`getCampusZone`、`getCampusSourceCoverage`、`windowStatus`、`compareCompanyCards`。
- Produces: 传给 client 的 `CampusCardData[]`（含 window、campusJobs、internJobs、nearestDeadlineMs）。

- [ ] **Step 1: 写 loading 骨架**（照抄 `app/path/loading.tsx`，复用 `components/Skeletons.tsx` + 真实页头，标题改"校招专区"）

- [ ] **Step 2: 写 page.tsx**

```tsx
// app/campus/page.tsx
export const dynamic = "force-dynamic";
import { getRequestUser } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import { resolveMustApplyIndustries, MUST_APPLY_BY_INDUSTRY } from "@/lib/must-apply-list";
import { getCampusZone } from "@/lib/jobs-store/read";
import { getCampusSourceCoverage } from "@/lib/campus-sources";
import { windowStatus, compareCompanyCards } from "@/lib/campus-zone";
import CampusClient from "./campus-client";

export default async function CampusPage() {
  const user = await getRequestUser();
  // 读用户行业（candidate_profiles 优先，回退 user_preferences）
  const service = createServiceClient();
  const { data: prof } = await service.from("candidate_profiles").select("target_industries").eq("user_id", user?.id ?? "").maybeSingle();
  const { data: pref } = await service.from("user_preferences").select("target_industries").eq("user_id", user?.id ?? "").maybeSingle();
  const rawIndustries = (prof?.target_industries as string[] | null) || (pref?.target_industries as string[] | null) || [];
  const industries = resolveMustApplyIndustries(rawIndustries); // 空→兜底"互联网/科技"

  const companies = Array.from(new Set(industries.flatMap((ind) => MUST_APPLY_BY_INDUSTRY[ind] || [])
    .map((c) => JSON.stringify(c)))).map((s) => JSON.parse(s) as { name: string; pattern: string });

  const [zone, sourceCov] = await Promise.all([
    getCampusZone(companies),
    getCampusSourceCoverage(companies),
  ]);

  const nowMs = Date.now();
  const cards = zone.map((z) => {
    const src = sourceCov.get(z.pattern) || { hasAnySource: z.hasAnyActiveJob, hasCampusSource: false };
    const window = windowStatus({
      campusJobCount: z.campusJobs.length,
      hasCampusSource: src.hasCampusSource,
      hasAnySource: src.hasAnySource || z.hasAnyActiveJob,
      lastSeenAtMs: z.lastSeenAtMs,
      nowMs,
    });
    const deadlines = z.campusJobs.map((j) => (j.deadline ? Date.parse(j.deadline) : NaN)).filter((t) => !Number.isNaN(t));
    const nearestDeadlineMs = deadlines.length ? Math.min(...deadlines) : null;
    return { ...z, window, nearestDeadlineMs };
  });
  cards.sort(compareCompanyCards);

  return <CampusClient cards={cards} industries={industries} hasIndustry={rawIndustries.length > 0} />;
}
```

- [ ] **Step 3: 起 preview 验证页可渲染**

用 preview_start 起 dev server（`.claude/launch.json` 的 dev 配置），登录测试账号（`test@jobradar.local`），访问 `/campus`。读 console/network 无报错，read_page 确认公司卡渲染、徽章出现。

- [ ] **Step 4: 提交**

```bash
git add app/campus/page.tsx app/campus/loading.tsx
git commit -m "feat(campus): /campus SSR 页装配（行业锁定+窗口态+卡排序）"
```

---

### Task 8: `campus-client.tsx` 公司卡 + 徽章 + 筛选 + 展开 + 展示时探活

**Files:**
- Create: `app/campus/campus-client.tsx`
- Reference: `components/JobCard.tsx`（复用渲染岗位）、`lib/liveness-client.js`（展示时探活）、`app/path/path-client.tsx`（徽章样式范式）

**Interfaces:**
- Consumes: `CampusCardData[]`、`groupCampusJobs`、`JobCard`、liveness client。

- [ ] **Step 1: 写 client 组件**（要点，非全量占位——实现按此清单逐项写实代码）：
  - 徽章映射：`hiring`→🟢招聘中（绿）/ `no_campus_now`→⚪当前未观测到在招校招岗（灰）/ `stale`→⏳数据待更新（黄）/ `not_ingested`→⚙️待接入（灰，tooltip 不暴露子原因给用户，仅"该公司校招源接入中"）。
  - 每张公司卡：公司名 + 徽章 + 校招岗数；点击展开用 `groupCampusJobs(card.campusJobs)` 分组渲染 `JobCard`。
  - 顶部筛选条：届别 / 学历 / 专业职能 / 城市 + "校招 / 实习"切换（切实习时渲染 `internJobs`）。筛选是**客户端过滤**已下发数据（P1 不做服务端往返）。
  - 展开公司时对其校招岗调 `lib/liveness-client.js` 批量探活，死岗当场隐藏（复刻 JobCard/看板用法）。
  - 空行业提示：`hasIndustry=false` 时顶部提示"完善简历行业以精准锁定目标公司"。
  - 诚实文案：列表头写"已接入官方校招源并持续验证的岗位"，绝不写"全部校招岗"。

- [ ] **Step 2: preview 走查**：resize mobile/desktop、切校招/实习、展开一家 hiring 公司确认岗位可见且链接指向官网、确认 ⚙️/⚪ 卡诚实展示不误导。截图存证。

- [ ] **Step 3: build 验证**

Run: `npm run build`
Expected: 编译通过、无类型错误（跑 build 前先停 dev server，见 CLAUDE.md 项目注意事项 3）。

- [ ] **Step 4: 提交**

```bash
git add app/campus/campus-client.tsx
git commit -m "feat(campus): 公司卡+徽章+校招/实习筛选+展开分组+展示时探活"
```

---

### Task 9: Navbar 一级入口

**Files:**
- Modify: `components/Navbar.tsx`（`LINKS` 数组）
- Modify: i18n 导航文案处（`LINKS` 的 `key` 对应中文，查 Navbar 内文案映射）

**Interfaces:** 无新接口。

- [ ] **Step 1: 加入口**

在 `components/Navbar.tsx` 的 `LINKS` 数组 `/path` 之后插入（图标复用已 import 的 phosphor 图标，选 `GraduationCap`，需在顶部 import 补上）：

```tsx
{ href: "/campus", key: "campus", icon: GraduationCap },
```
并在导航 `key→中文` 文案映射处加 `campus: "校招专区"`（查 Navbar 内 label 逻辑，与 today/jobs/path 同处补一行）。

- [ ] **Step 2: preview 验证入口出现且高亮**：访问 `/campus`，Navbar "校招专区" 高亮（active 态）。

- [ ] **Step 3: 提交**

```bash
git add components/Navbar.tsx
git commit -m "feat(campus): Navbar 加校招专区一级入口"
```

---

### Task 10: 用户纠错入口 + 复核队列

**Files:**
- Create: `app/api/campus-zone/dispute/route.ts`
- Modify: `app/campus/campus-client.tsx`（岗位/卡上加纠错入口）
- Reference: `app/api/insights/dispute/route.ts`（复用申诉写入范式）

**Interfaces:**
- Produces: `POST /api/campus-zone/dispute { job_id, reason: "not_campus" | "dead_link" | "closed" }` → 写入复核记录（复用 events 表或 insight_disputes 同款轻量表；实现时选已有表，勿新建表除非必要）。

- [ ] **Step 1: 写 route**（鉴权走 `requireUser`，service-role 写；reason 白名单校验；失败不吞错记录日志）。参照 `app/api/insights/dispute/route.ts` 的鉴权+写入结构，写实代码。

- [ ] **Step 2: client 加入口**：JobCard 旁或卡菜单一个轻量"反馈"按钮，POST 上述端点，成功 toast"已收到，感谢反馈"。

- [ ] **Step 3: 验证**：preview 点纠错 → read_network_requests 确认 200；`psql` 查复核记录落库。

- [ ] **Step 4: 提交**

```bash
git add app/api/campus-zone/dispute/route.ts app/campus/campus-client.tsx
git commit -m "feat(campus): 用户纠错入口（这不是校招/链接失效/已结束）→ 复核队列"
```

---

### Task 11: 回归四件套

- [ ] **Step 1: 跑全回归**

```bash
node --test tests/*.test.js && \
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
  npm run build && git diff --check
```
Expected: 全绿。

- [ ] **Step 2: 若 campus-zone.ts 的 TS 语法在 node --test 下需转译 shim**，确认走的是项目现有的 TS lib 测试机制（见 [[job-radar-ts-lib-test-constraint]]：被测文件 import 用相对路径、不能 @/）。Task 5 的 `getCampusZone` import 了 `@/lib/campus-zone` 属应用侧代码（不被 node --test 直接测），campus-zone.ts 本身被测时用相对 require（Task 1 已按此写）。

- [ ] **Step 3: 提交（如有修正）**

```bash
git add -A && git commit -m "test(campus): 回归四件套全绿"
```

---

## Self-Review（已执行）

- **Spec coverage**：4.1 准入门→T1；4.2 窗口态→T2；4.3 排序/归组/页/筛选→T3/T4/T7/T8；4.1 读查询→T5；⚙️子原因所需 source 覆盖→T6；入口→T9；4.6 纠错→T10；可靠性三件套里"展示时探活"→T8、"新鲜度降级"→T2、"外跳抽检"复用现有 sweep（非本计划新代码，spec §4.4 已注明复用）；供给补源→**独立运营轨，不在本计划**（spec §4.5，见下）。
- **Placeholder scan**：纯函数任务均含完整测试+实现代码；UI 任务（T8）给出逐项实现清单而非"TODO"，因 UI 走 build+preview 验证而非单测——清单每项是具体可执行动作。
- **Type consistency**：`WindowState`/`CampusCompanyRow`/`CampusSourceInfo` 在 T2/T5/T6 定义，T7 装配处引用一致（`window.state`、`campusJobs`、`hasCampusSource`、`lastSeenAtMs`、`nearestDeadlineMs` 全对齐）。
- **供给轨说明**：spec §4.5 定向补校招源是运营活（复用 discover_domestic + 浏览器 confirm + 探活入库工艺），不套 TDD，单独作为并行轨推进——它让 ⚙️ 卡逐步变 🟢，与本应用层计划解耦。
