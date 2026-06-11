# 职业洞察 P1「派生层」实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Commits:** 按本仓库 git 习惯——用户说「提交」时自动 commit+push 到 main。各任务末尾的 commit 步骤照常执行；执行者按此节奏落盘。

**Goal:** 让任何「有岗位」的公司，点开洞察抽屉立刻看到从自有 `jobs` 数据派生的事实级洞察（招聘节奏 / 招聘动态 / 薪资带），一上线即 100% 覆盖、永远新鲜、零 LLM、零成本、零新迁移。

**Architecture:** 纯函数 `lib/insight-derive.ts` 在请求时（read-time）从 `jobs` 行算出 `InsightItemView[]`，在 `/api/insights` 与存储型洞察合并后返回；抽屉复用既有 `InsightCard` 渲染（派生项加「本平台岗位聚合」芯片）。**刻意偏离设计文档 §4.3 的「物化」选择**——P1 用 read-time 派生：更新鲜（实时而非每日批）、零迁移、零 crawler/CI 改动、零成本；若日后 drawer 打开的聚合查询成为性能瓶颈，再于 P2 物化。

**Tech Stack:** TypeScript 纯函数（仿 `lib/scoring.ts` / `lib/insight-verification.ts`）；`node --test` + `typescript.transpileModule` 单测（仿 `tests/insight-verification.test.js`）；Next.js App Router API（`app/api/insights/route.ts`）；React 抽屉（`components/CompanyInsightDrawer.tsx`）。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `lib/types.ts` | 类型：`InsightDimension` 加 `hiring`；`InsightItemView` 加 `derived?` | Modify |
| `lib/insight-bundle.ts` | `INSIGHT_DIMENSIONS` / `emptyDimensions` 加 `hiring` | Modify |
| `lib/insight-derive.ts` | **派生纯函数**（分类 / 薪资解析 / timing / hiring / salary-band / 聚合）| Create |
| `tests/insight-derive.test.js` | 派生纯函数单测 | Create |
| `app/api/insights/route.ts` | GET 加：取 jobs → 派生 → 合并 → failure_reason | Modify |
| `components/CompanyInsightDrawer.tsx` | `hiring` 维度元数据/顺序 + 派生芯片 + 隐藏派生项申诉 + banner 措辞 | Modify |

---

### Task 1: 类型扩展 — `InsightDimension` 加 `hiring`、`InsightItemView` 加 `derived`

**Files:**
- Modify: `lib/types.ts:157-162`, `lib/types.ts:217-220`

纯类型改动，无行为可单测；由 Task 11 的 `npm run build` 守门。

- [ ] **Step 1: 给 `InsightDimension` 加 `hiring`**

把 `lib/types.ts:157-162`：

```ts
export type InsightDimension =
  | "timing"
  | "listing"
  | "compensation_intensity"
  | "path"
  | "culture";
```

改为：

```ts
export type InsightDimension =
  | "timing"
  | "hiring"
  | "listing"
  | "compensation_intensity"
  | "path"
  | "culture";
```

- [ ] **Step 2: 给 `InsightItemView` 加 `derived` 标记**

把 `lib/types.ts:216-220`：

```ts
// 带溯源 + 时效标记的展示态条目
export interface InsightItemView extends InsightItem {
  sources: InsightSource[];
  outdated: boolean;
}
```

改为：

```ts
// 带溯源 + 时效标记的展示态条目
export interface InsightItemView extends InsightItem {
  sources: InsightSource[];
  outdated: boolean;
  // T1 派生层标记：true = 由自有 jobs 数据算出的事实聚合（非策展/非社区），前端用不同芯片呈现
  derived?: boolean;
}
```

- [ ] **Step 3: Commit**

```bash
git add lib/types.ts
git commit -m "feat(insights): 类型加 hiring 维度 + InsightItemView.derived 标记（P1 派生层）"
```

---

### Task 2: 分组门加 `hiring` 维度

**Files:**
- Modify: `lib/insight-bundle.ts:17-30`

- [ ] **Step 1: `INSIGHT_DIMENSIONS` 与 `emptyDimensions` 加 `hiring`**

把 `lib/insight-bundle.ts:17-30`：

```ts
export const INSIGHT_DIMENSIONS: InsightDimension[] = [
  "timing",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];

export const ITEM_COLUMNS =
  "id, company_id, dimension, grade, title, content, sample_size, payload, time_window, valid_from, valid_until, last_verified_at, deidentified, status, created_at, updated_at";

export function emptyDimensions(): Record<InsightDimension, InsightItemView[]> {
  return { timing: [], listing: [], compensation_intensity: [], path: [], culture: [] };
}
```

改为：

```ts
export const INSIGHT_DIMENSIONS: InsightDimension[] = [
  "timing",
  "hiring",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];

export const ITEM_COLUMNS =
  "id, company_id, dimension, grade, title, content, sample_size, payload, time_window, valid_from, valid_until, last_verified_at, deidentified, status, created_at, updated_at";

export function emptyDimensions(): Record<InsightDimension, InsightItemView[]> {
  return { timing: [], hiring: [], listing: [], compensation_intensity: [], path: [], culture: [] };
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/insight-bundle.ts
git commit -m "feat(insights): 分组门加 hiring 维度（P1）"
```

---

### Task 3: 派生模块骨架 + `classifyRecruitment` 分类器（TDD）

**Files:**
- Create: `lib/insight-derive.ts`
- Create: `tests/insight-derive.test.js`

- [ ] **Step 1: 写失败测试**

创建 `tests/insight-derive.test.js`：

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

// 仿 tests/insight-verification.test.js：读 .ts 源码即时转译为 CommonJS 再执行（import type 被擦除）
function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", compiled);
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const D = loadTsModule(path.join("lib", "insight-derive.ts"));

const NOW = new Date("2026-06-15T00:00:00.000Z");
const NOW_ISO = NOW.toISOString();

// 构造一行最小 Job（按 lib/types.ts Job 形状），用 over 覆盖关心的字段
function j(over = {}) {
  return {
    id: "x", source_id: null, company: "测试公司", title: "工程师",
    location: "北京", job_type: "社招", summary: null, jd_url: "https://e.com/1",
    apply_url: null, salary_text: null, posted_at: null, experience: null,
    education: null, deadline: null, first_seen_at: "2026-06-01T00:00:00.000Z",
    last_seen_at: "2026-06-01T00:00:00.000Z", status: "active",
    content_hash: null, created_at: "2026-06-01T00:00:00.000Z", ...over,
  };
}

test("classifyRecruitment 按关键词归三桶（保守：无明确关键词 = unknown）", () => {
  assert.equal(D.classifyRecruitment("实习", "数据分析实习生"), "intern");
  assert.equal(D.classifyRecruitment("校招", "2026届校园招聘-后端"), "campus");
  assert.equal(D.classifyRecruitment("应届", "应届生-算法"), "campus");
  assert.equal(D.classifyRecruitment("社招", "高级后端工程师"), "social");
  assert.equal(D.classifyRecruitment(null, "Software Engineer Intern"), "intern");
  assert.equal(D.classifyRecruitment(null, "资深产品经理"), "unknown");
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`Cannot find module ... lib/insight-derive.ts` 或 `D.classifyRecruitment is not a function`）

- [ ] **Step 3: 写最小实现（骨架 + 工具 + 分类器）**

创建 `lib/insight-derive.ts`：

```ts
// ============================================================
// 模块 B 职业洞察 — Tier 1 派生层（纯函数：无 LLM / 无网络 / 无 DB）
// 从自有 jobs 行直接算出事实级洞察：招聘节奏 timing / 招聘动态 hiring / 薪资带 compensation。
// 读时在 /api/insights 调用，产出 InsightItemView[]，与存储型洞察同形展示。
// 设计见 docs/superpowers/specs/2026-06-12-career-insights-overhaul-design.md §4。
// ============================================================
import type { InsightDimension, InsightItemView, Job } from "./types";

export type RecruitBucket = "campus" | "intern" | "social" | "unknown";

// 阈值：样本太少不出洞察（宁缺毋滥，避免拿 2 个岗位编节奏）
const TIMING_MIN_SAMPLE = 5;
const HIRING_MIN_SAMPLE = 3;
const SALARY_MIN_SAMPLE = 5;

// 与 crawler/normalizer.py 三桶同口径：实习 → 校招/应届 → 社招；都不命中 = unknown（不臆测）
export function classifyRecruitment(jobType: string | null, title: string | null): RecruitBucket {
  const t = `${jobType || ""} ${title || ""}`.toLowerCase();
  if (/实习|intern|internship/.test(t)) return "intern";
  if (/校招|校园招聘|应届|campus|graduate|new\s?grad/.test(t)) return "campus";
  if (/社招|社会招聘|experienced|professional/.test(t)) return "social";
  return "unknown";
}

// ---- 内部工具（不导出，由派生函数复用） ----

function monthOf(iso: string | null): number | null {
  if (!iso) return null;
  const m = new Date(iso).getUTCMonth() + 1;
  return Number.isNaN(m) ? null : m;
}

function yyyymm(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
}

// 构造派生展示态条目：固定 grade=fact、deidentified=true、status=active、derived=true、无溯源链接
function makeDerivedView(o: {
  dimension: InsightDimension;
  title: string;
  content: string;
  time_window: string;
  payload?: Record<string, unknown>;
  sample_size?: number | null;
  nowIso: string;
}): InsightItemView {
  return {
    id: `derived-${o.dimension}`,
    company_id: "derived",
    dimension: o.dimension,
    grade: "fact",
    title: o.title,
    content: o.content,
    sample_size: o.sample_size ?? null,
    payload: o.payload ?? {},
    time_window: o.time_window,
    valid_from: null,
    valid_until: null,
    last_verified_at: o.nowIso,
    deidentified: true,
    status: "active",
    created_at: o.nowIso,
    updated_at: o.nowIso,
    sources: [],
    outdated: false,
    derived: true,
  };
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（1 test）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): 派生层骨架 + classifyRecruitment 分类器（P1 T1）"
```

---

### Task 4: `parseSalaryText` 薪资文本解析器（TDD）

**Files:**
- Modify: `lib/insight-derive.ts`
- Modify: `tests/insight-derive.test.js`

- [ ] **Step 1: 追加失败测试**

在 `tests/insight-derive.test.js` 末尾追加：

```js
test("parseSalaryText 只解析明示月薪区间；歧义/无值返回 null", () => {
  assert.deepEqual(D.parseSalaryText("15-30K"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("15k-30k"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("20-40千/月"), { minK: 20, maxK: 40 });
  assert.deepEqual(D.parseSalaryText("15000-30000"), { minK: 15, maxK: 30 });
  assert.equal(D.parseSalaryText("面议"), null);
  assert.equal(D.parseSalaryText("官网未披露"), null);
  assert.equal(D.parseSalaryText(null), null);
  assert.equal(D.parseSalaryText("15-30万"), null); // 年/月歧义，保守跳过
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`D.parseSalaryText is not a function`）

- [ ] **Step 3: 实现 `parseSalaryText`**

在 `lib/insight-derive.ts` 的 `classifyRecruitment` 函数下方追加：

```ts
// 解析岗位薪资文本为「月薪 K」区间。仅解析明示区间（k/千 或 4–6 位元）；
// 「万」存在年/月歧义 → 保守返回 null（不进垃圾）。无法解析返回 null。
export function parseSalaryText(raw: string | null): { minK: number; maxK: number } | null {
  if (!raw) return null;
  const s = raw.replace(/\s/g, "").toLowerCase();
  // 形如 15-30k / 15k-30k / 20-40千（单位可出现在首数字后或尾数字后）
  let m = s.match(/(\d+(?:\.\d+)?)(?:k|千)?[-~至到](\d+(?:\.\d+)?)(?:k|千)/);
  if (m) {
    const lo = parseFloat(m[1]);
    const hi = parseFloat(m[2]);
    if (lo > 0 && hi >= lo && hi < 1000) return { minK: Math.round(lo), maxK: Math.round(hi) };
    return null;
  }
  // 形如 15000-30000（元/月）→ /1000 取 K
  m = s.match(/(\d{4,6})[-~至到](\d{4,6})/);
  if (m) {
    const lo = parseInt(m[1], 10) / 1000;
    const hi = parseInt(m[2], 10) / 1000;
    if (lo > 0 && hi >= lo && hi < 1000) return { minK: Math.round(lo), maxK: Math.round(hi) };
    return null;
  }
  return null;
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（2 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): parseSalaryText 薪资带解析（保守跳过万/歧义）（P1 T1）"
```

---

### Task 5: `deriveSalaryBand` 薪资带派生（TDD）

**Files:**
- Modify: `lib/insight-derive.ts`
- Modify: `tests/insight-derive.test.js`

- [ ] **Step 1: 追加失败测试**

在 `tests/insight-derive.test.js` 末尾追加：

```js
test("deriveSalaryBand 聚合明示薪资（>=5 才出，否则 null）", () => {
  const jobs = [
    j({ salary_text: "15-25K" }), j({ salary_text: "20-30K" }),
    j({ salary_text: "18-28K" }), j({ salary_text: "25-35K" }),
    j({ salary_text: "面议" }), j({ salary_text: "22000-32000" }),
  ];
  const v = D.deriveSalaryBand(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "compensation_intensity");
  assert.equal(v.grade, "fact");
  assert.equal(v.derived, true);
  assert.equal(v.payload.sample, 5);
  assert.match(v.content, /K/);
});

test("deriveSalaryBand 不足阈值返回 null", () => {
  assert.equal(D.deriveSalaryBand([j({ salary_text: "15-25K" })], NOW_ISO), null);
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`D.deriveSalaryBand is not a function`）

- [ ] **Step 3: 实现 `deriveSalaryBand`**

在 `lib/insight-derive.ts` 末尾追加：

```ts
// 薪资带（compensation_intensity, fact）：聚合 active 岗位中「明示薪资」的月薪带中位区间。
export function deriveSalaryBand(jobs: Job[], nowIso: string): InsightItemView | null {
  const bands = jobs
    .filter((jb) => jb.status === "active")
    .map((jb) => parseSalaryText(jb.salary_text))
    .filter((b): b is { minK: number; maxK: number } => Boolean(b));
  if (bands.length < SALARY_MIN_SAMPLE) return null;
  const lo = median(bands.map((b) => b.minK));
  const hi = median(bands.map((b) => b.maxK));
  const content = `公开在招岗位中明示薪资的约 ${bands.length} 个，月薪带集中在约 ${lo}–${hi}K（中位区间，仅供参考）。`;
  return makeDerivedView({
    dimension: "compensation_intensity",
    title: "薪资带 · 据在招岗位",
    content,
    payload: { min_k: lo, max_k: hi, sample: bands.length },
    time_window: `截至 ${yyyymm(nowIso)}`,
    sample_size: bands.length,
    nowIso,
  });
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): deriveSalaryBand 从在招岗位派生 fact 级薪资带（P1 T1）"
```

---

### Task 6: `deriveTiming` 招聘节奏派生（TDD）

**Files:**
- Modify: `lib/insight-derive.ts`
- Modify: `tests/insight-derive.test.js`

- [ ] **Step 1: 追加失败测试**

在 `tests/insight-derive.test.js` 末尾追加：

```js
test("deriveTiming 概括校招峰值月 + 社招全年滚动", () => {
  const jobs = [
    j({ job_type: "校招", posted_at: "2026-08-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-09-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-08-20T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-01-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-03-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-04-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-07-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-10-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-12-05T00:00:00Z" }),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "timing");
  assert.match(v.content, /校招集中在 8、9 月/);
  assert.match(v.content, /社招全年滚动/);
});

test("deriveTiming 不足阈值返回 null", () => {
  assert.equal(D.deriveTiming([j({ posted_at: "2026-08-01T00:00:00Z" })], NOW_ISO), null);
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`D.deriveTiming is not a function`）

- [ ] **Step 3: 实现 `deriveTiming`（含内部 `peakMonths`）**

在 `lib/insight-derive.ts` 末尾追加：

```ts
// 出现频次最高的 1–2 个月（升序返回），用于「校招集中在 X、Y 月」
function peakMonths(months: number[]): number[] {
  const freq = new Map<number, number>();
  for (const m of months) freq.set(m, (freq.get(m) || 0) + 1);
  return [...freq.entries()]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .slice(0, 2)
    .map((e) => e[0])
    .sort((a, b) => a - b);
}

// 招聘节奏（timing, fact）：按三桶聚合发布月份（posted_at 缺则用 first_seen_at 代理）。
export function deriveTiming(jobs: Job[], nowIso: string): InsightItemView | null {
  const dated = jobs.filter((jb) => jb.posted_at || jb.first_seen_at);
  if (dated.length < TIMING_MIN_SAMPLE) return null;

  const byBucket: Record<"campus" | "intern" | "social", number[]> = {
    campus: [], intern: [], social: [],
  };
  for (const jb of dated) {
    const b = classifyRecruitment(jb.job_type, jb.title);
    if (b === "unknown") continue;
    const mo = monthOf(jb.posted_at || jb.first_seen_at);
    if (mo) byBucket[b].push(mo);
  }

  const LABEL: Record<"campus" | "intern" | "social", string> = {
    campus: "校招", intern: "实习", social: "社招",
  };
  const parts: string[] = [];
  (["campus", "intern", "social"] as const).forEach((b) => {
    const months = byBucket[b];
    if (months.length < 3) return; // 单桶样本不足不下结论
    if (b === "social" && new Set(months).size >= 6) {
      parts.push("社招全年滚动");
      return;
    }
    parts.push(`${LABEL[b]}集中在 ${peakMonths(months).join("、")} 月`);
  });
  if (parts.length === 0) return null;

  const content = `据本平台 ${dated.length} 个在招岗位的发布时间聚合：${parts.join("；")}。`;
  return makeDerivedView({
    dimension: "timing",
    title: "招聘节奏 · 据在招岗位",
    content,
    time_window: `截至 ${yyyymm(nowIso)}`,
    nowIso,
  });
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（6 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): deriveTiming 从发布时间派生招聘节奏（P1 T1）"
```

---

### Task 7: `deriveHiring` 招聘动态派生（TDD）

**Files:**
- Modify: `lib/insight-derive.ts`
- Modify: `tests/insight-derive.test.js`

- [ ] **Step 1: 追加失败测试**

在 `tests/insight-derive.test.js` 末尾追加：

```js
test("deriveHiring 概括在招规模/城市/方向（排除非 active）", () => {
  const jobs = [
    j({ status: "active", location: "北京", title: "后端工程师" }),
    j({ status: "active", location: "北京·海淀", title: "前端工程师" }),
    j({ status: "active", location: "上海", title: "产品经理" }),
    j({ status: "expired", location: "深圳", title: "测试" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "hiring");
  assert.equal(v.derived, true);
  assert.equal(v.payload.active_count, 3);
  assert.match(v.content, /当前在招约 3 个岗位/);
  assert.match(v.content, /北京/);
});

test("deriveHiring 不足阈值返回 null", () => {
  assert.equal(D.deriveHiring([j(), j()], NOW_ISO), null);
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`D.deriveHiring is not a function`）

- [ ] **Step 3: 实现 `deriveHiring`（含内部 `topN` / `cityOf` / `coarseFunction` / `trendPct`）**

在 `lib/insight-derive.ts` 末尾追加：

```ts
// 频次 Top-n（key→count），用于热门城市/方向
function topN(keys: string[], n: number): Array<{ key: string; count: number }> {
  const freq = new Map<string, number>();
  for (const k of keys) freq.set(k, (freq.get(k) || 0) + 1);
  return [...freq.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

// 取城市主名：按常见分隔切第一段，去「市/地区」后缀
function cityOf(location: string | null): string | null {
  if (!location) return null;
  const first = location.split(/[·、,，/\s-]+/).filter(Boolean)[0] || "";
  const city = first.replace(/(市|地区)$/, "").trim();
  return city || null;
}

// 粗粒度职能归类（算法在「研发」之前判，避免「算法工程师」落到研发）
const FUNCTION_RULES: Array<[RegExp, string]> = [
  [/算法|machine\s?learning|\bml\b|\bai\b|nlp|\bcv\b|数据科学|data\s?scien/i, "算法/AI"],
  [/前端|后端|全栈|开发|工程师|研发|software|engineer|backend|frontend|测试|\bqa\b|运维|\bsre\b|devops/i, "研发"],
  [/产品经理|产品|product\s?manager|\bpm\b/i, "产品"],
  [/设计|design|\bux\b|\bui\b|交互/i, "设计"],
  [/运营|operation/i, "运营"],
  [/市场|marketing|品牌|公关|增长|growth/i, "市场"],
  [/销售|sales|商务|\bbd\b/i, "销售"],
  [/人力|\bhr\b|招聘|财务|法务|行政|finance|legal/i, "职能"],
];
function coarseFunction(title: string | null): string | null {
  if (!title) return null;
  for (const [re, label] of FUNCTION_RULES) if (re.test(title)) return label;
  return "其他";
}

// 近 30 天新增岗位环比（first_seen_at）；前一窗口样本 <3 不报趋势（null）
function trendPct(jobs: Job[], nowIso: string): number | null {
  const now = new Date(nowIso).getTime();
  const D30 = 30 * 86_400_000;
  let recent = 0;
  let prior = 0;
  for (const jb of jobs) {
    if (!jb.first_seen_at) continue;
    const t = new Date(jb.first_seen_at).getTime();
    if (Number.isNaN(t)) continue;
    if (t >= now - D30) recent++;
    else if (t >= now - 2 * D30) prior++;
  }
  if (prior < 3) return null;
  return Math.round(((recent - prior) / prior) * 100);
}

// 招聘动态（hiring, fact）：在招规模 + 热门城市/方向 + 校社占比 + 新增趋势。
export function deriveHiring(jobs: Job[], nowIso: string): InsightItemView | null {
  const active = jobs.filter((jb) => jb.status === "active");
  if (active.length < HIRING_MIN_SAMPLE) return null;

  const cities = topN(
    active.map((jb) => cityOf(jb.location)).filter((x): x is string => Boolean(x)),
    3,
  );
  const functions = topN(
    active.map((jb) => coarseFunction(jb.title)).filter((x): x is string => Boolean(x)),
    3,
  );
  const mix = { campus: 0, intern: 0, social: 0, unknown: 0 };
  for (const jb of active) mix[classifyRecruitment(jb.job_type, jb.title)]++;
  const trend = trendPct(active, nowIso);

  const cityStr = cities.length ? `主要在 ${cities.map((c) => c.key).join("、")}` : "";
  const fnStr = functions.length ? `热门方向 ${functions.map((f) => f.key).join("、")}` : "";
  const trendStr = trend !== null ? `近一月新增岗位环比 ${trend > 0 ? "+" : ""}${trend}%` : "";
  const tail = [cityStr, fnStr, trendStr].filter(Boolean).join("，");
  const content = `当前在招约 ${active.length} 个岗位${tail ? "，" + tail : ""}。`;

  return makeDerivedView({
    dimension: "hiring",
    title: "招聘动态 · 据在招岗位",
    content,
    payload: { active_count: active.length, top_cities: cities, top_functions: functions, mix, trend },
    time_window: `截至 ${yyyymm(nowIso)}`,
    nowIso,
  });
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（8 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): deriveHiring 从在招岗位派生招聘动态（规模/城市/方向/趋势）（P1 T1）"
```

---

### Task 8: `deriveCompanyInsights` 聚合入口（TDD）

**Files:**
- Modify: `lib/insight-derive.ts`
- Modify: `tests/insight-derive.test.js`

- [ ] **Step 1: 追加失败测试**

在 `tests/insight-derive.test.js` 末尾追加：

```js
test("deriveCompanyInsights 只返回算得出的维度", () => {
  const jobs = [1, 2, 3, 4, 5, 6].map((i) =>
    j({ status: "active", salary_text: "15-25K", job_type: "社招", title: "后端工程师",
        location: "北京", posted_at: `2026-0${i}-05T00:00:00Z` }),
  );
  const out = D.deriveCompanyInsights(jobs, NOW);
  assert.ok(out.compensation_intensity, "应有薪资带");
  assert.ok(out.hiring, "应有招聘动态");
  assert.ok(out.timing, "社招覆盖 1–6 月（6 个不同月）→ 全年滚动");
  assert.equal(out.compensation_intensity[0].derived, true);
});

test("deriveCompanyInsights 空数据返回空对象", () => {
  assert.deepEqual(D.deriveCompanyInsights([], NOW), {});
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `node --test tests/insight-derive.test.js`
Expected: FAIL（`D.deriveCompanyInsights is not a function`）

- [ ] **Step 3: 实现 `deriveCompanyInsights`**

在 `lib/insight-derive.ts` 末尾追加：

```ts
// 聚合入口：从某公司的 jobs 行算出所有可派生维度（算不出的维度不出现在结果里）。
// 返回形如 { timing?: [view], hiring?: [view], compensation_intensity?: [view] }。
export function deriveCompanyInsights(
  jobs: Job[],
  now: Date = new Date(),
): Partial<Record<InsightDimension, InsightItemView[]>> {
  const nowIso = now.toISOString();
  const out: Partial<Record<InsightDimension, InsightItemView[]>> = {};
  const timing = deriveTiming(jobs, nowIso);
  if (timing) out.timing = [timing];
  const hiring = deriveHiring(jobs, nowIso);
  if (hiring) out.hiring = [hiring];
  const salary = deriveSalaryBand(jobs, nowIso);
  if (salary) out.compensation_intensity = [salary];
  return out;
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（10 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/insight-derive.ts tests/insight-derive.test.js
git commit -m "feat(insights): deriveCompanyInsights 聚合入口（P1 T1）"
```

---

### Task 9: `/api/insights` 接入 read-time 派生 + 合并

**Files:**
- Modify: `app/api/insights/route.ts:1-85`

把存储型洞察与派生洞察合并；**对无 company_profile 的公司也派生**（实现 100% 覆盖）。集成层不走 `node --test`，由 Task 11 `npm run build` + 用户本机 live 验证。

- [ ] **Step 1: 加导入**

在 `app/api/insights/route.ts` 顶部 import 区（第 11 行 `} from "@/lib/insight-bundle";` 之后）追加：

```ts
import { deriveCompanyInsights } from "@/lib/insight-derive";
```

并把 `lib/types` 的 import（第 12-17 行）加上 `Job`：

```ts
import type {
  CompanyProfile,
  InsightDimension,
  InsightItem,
  InsightSource,
  Job,
} from "@/lib/types";
```

- [ ] **Step 2: 重写 GET 数据流（行 38-85）**

把 `app/api/insights/route.ts` 第 38 行（`// 1) 取全部公司画像…`）到第 85 行（GET 函数结束 `}`）整段替换为：

```ts
  // 1) 取全部公司画像，归一化匹配（苹果↔Apple、字节↔ByteDance）。可能无画像（95% 公司）。
  const { data: profiles, error: profileError } = await supabase
    .from("company_profiles")
    .select("*");
  if (profileError) {
    console.error("[insights] 读取 company_profiles 失败", profileError.message);
    return NextResponse.json(
      { ok: false, error: profileError.message },
      { status: 500 },
    );
  }
  const profile = findCompanyProfile((profiles || []) as CompanyProfile[], company);

  // 2) Tier1 派生：从自有 jobs 直接算事实洞察（无需画像，保证 100% 覆盖）。
  //    匹配候选 = 查询词 + 画像 company/aliases；限 active，cap 3000 行足够代表性聚合。
  const candidates = Array.from(
    new Set(
      profile ? [profile.company, ...(profile.aliases || []), company] : [company],
    ),
  );
  const { data: jobRows, error: jobError } = await supabase
    .from("jobs")
    .select(
      "company,title,location,job_type,salary_text,posted_at,first_seen_at,last_seen_at,status",
    )
    .in("company", candidates)
    .eq("status", "active")
    .limit(3000);
  if (jobError) {
    console.error("[insights] 读取 jobs（派生）失败", jobError.message);
  }
  const derived = deriveCompanyInsights((jobRows || []) as Job[], new Date());

  // 3) 存储型洞察（仅当有画像）：过校验门 + 分组（共享 insight-bundle）。
  let storedDims = emptyDimensions();
  let evaluations: ReturnType<typeof groupGatedInsights>["evaluations"] = [];
  if (profile) {
    const { data: items, error: itemError } = await supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .eq("company_id", profile.id)
      .eq("status", "active");
    if (itemError) {
      console.error("[insights] 读取 insight_items 失败", itemError.message);
      return NextResponse.json(
        { ok: false, error: itemError.message },
        { status: 500 },
      );
    }
    const grouped = groupGatedInsights((items || []) as any[], new Date());
    storedDims = grouped.dimensions;
    evaluations = grouped.evaluations;
  }

  // 4) 合并：每维度「派生在前、存储在后」。
  const dimensions = emptyDimensions();
  for (const dim of INSIGHT_DIMENSIONS) {
    dimensions[dim] = [...(derived[dim] || []), ...storedDims[dim]];
  }
  const hasAny = INSIGHT_DIMENSIONS.some((dim) => dimensions[dim].length > 0);

  return NextResponse.json({
    ok: true,
    company: profile,
    query: company,
    dimensions,
    // 有任何可展示条目（含派生）→ 无失败；否则沿用存储项的 bundle 级判定
    failure_reason: hasAny ? null : resolveInsightFailure(evaluations),
  });
}
```

> 说明：`InsightDimension` 的 import 仍被 POST 分支使用，保留；`InsightItem` 同理。

- [ ] **Step 3: 类型检查（局部）**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -i "api/insights\|insight-derive" || echo "no insight type errors"`
Expected: `no insight type errors`（若有报错按提示修正字段名/类型）

- [ ] **Step 4: Commit**

```bash
git add app/api/insights/route.ts
git commit -m "feat(insights): /api/insights 接入 read-time 派生层（100% 覆盖，无画像也派生）（P1 T1）"
```

---

### Task 10: 抽屉渲染 `hiring` 维度 + 派生芯片 + banner 措辞

**Files:**
- Modify: `components/CompanyInsightDrawer.tsx`（import 行 5-17、`DIMENSION_META` 45-80、`DIMENSION_ORDER` 82-88、banner 185-190、`InsightCard` chip 321 + 申诉块 404）

- [ ] **Step 1: 加图标 import**

把 `components/CompanyInsightDrawer.tsx` 第 5-17 行的 phosphor import 中加入 `Buildings`（按字母位置插在 `ArrowSquareOut` 之后）：

```tsx
import {
  ArrowSquareOut,
  Buildings,
  CalendarBlank,
  ChartLineUp,
  ClockCounterClockwise,
  Flag,
  Path,
  Scales,
  ShieldCheck,
  Sparkle,
  UsersThree,
  X,
} from "@phosphor-icons/react";
```

- [ ] **Step 2: `DIMENSION_META` 加 `hiring`**

在 `components/CompanyInsightDrawer.tsx` 的 `DIMENSION_META` 对象里、`timing` 条目（第 49-54 行）之后插入：

```tsx
  hiring: {
    label: "招聘动态",
    icon: Buildings,
    accent: "border-[#b7d2ee] bg-[#dceafa]",
    iconText: "text-[#2f6299]",
  },
```

- [ ] **Step 3: `DIMENSION_ORDER` 加 `hiring`**

把 `DIMENSION_ORDER`（第 82-88 行）改为：

```tsx
const DIMENSION_ORDER: InsightDimension[] = [
  "timing",
  "hiring",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];
```

- [ ] **Step 4: banner 措辞兼顾「平台派生」与「社区聚合」**

把第 185-190 行的 banner `<p>…</p>` 正文（`<span>下列内容…自行判断。</span>`）替换为：

```tsx
            <span>
              下列内容部分来自<strong>本平台在招岗位的聚合统计</strong>（带「本平台岗位聚合」标记，属事实数据），部分来自<strong>公开报道与网络讨论的聚合</strong>并经<strong>去标识化</strong>处理（属社区参考、非官方，也不针对任何个人）。每条结论的依据见卡片下方，<strong>仅供参考</strong>，请结合官方岗位信息与面试沟通自行判断。
            </span>
```

- [ ] **Step 5: `InsightCard` — 派生项用专属芯片**

把 `InsightCard` 内第 321 行：

```tsx
  const chip = gradeChip(item.grade, item.sample_size);
```

替换为：

```tsx
  const chip = item.derived
    ? { text: "本平台岗位聚合", cls: "border border-[#b7d2ee] bg-[#dceafa] text-[#2f6299]" }
    : gradeChip(item.grade, item.sample_size);
```

- [ ] **Step 6: `InsightCard` — 派生项隐藏「这条有误?」申诉块**

派生项是确定性聚合、无可申诉的溯源条目。把第 404 行起的申诉容器：

```tsx
      <div className="mt-3.5 border-t border-black/[0.06] pt-2.5">
        {sent ? (
```

替换为（加 `{!item.derived && (` 包裹，并在该容器闭合 `</div>` 后补 `)}`）：

```tsx
      {!item.derived && (
      <div className="mt-3.5 border-t border-black/[0.06] pt-2.5">
        {sent ? (
```

并把该容器的结束标签（原第 444 行 `</div>`，紧接 `</article>` 之前）改为：

```tsx
      </div>
      )}
```

- [ ] **Step 7: 验证编译**

Run: `npm run build`
Expected: 编译通过（无 TS 报错）。若报 `hiring` 相关类型错，回查 Task 1/2 是否落实。

- [ ] **Step 8: Commit**

```bash
git add components/CompanyInsightDrawer.tsx
git commit -m "feat(insights): 抽屉渲染 hiring 维度 + 派生芯片 + banner 兼顾平台/社区（P1 T1）"
```

---

### Task 11: 回归四件套 + 收尾

**Files:** 无（仅验证）

- [ ] **Step 1: 派生单测全绿**

Run: `node --test tests/insight-derive.test.js`
Expected: PASS（10 tests）

- [ ] **Step 2: 全量单测（确认未碰坏既有洞察测试）**

Run: `node --test tests/*.test.js`
Expected: 全 PASS（含 insight-verification / insight-match）

- [ ] **Step 3: crawler 单测（应不受影响）**

Run: `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`
Expected: OK（P1 未动 crawler）

- [ ] **Step 4: 构建**

Run: `npm run build`
Expected: 构建成功

- [ ] **Step 5: 空白检查**

Run: `git diff --check`
Expected: 无输出

- [ ] **Step 6: 最终 commit（若前序已分别 commit，此步可空）**

```bash
git status
# 若有遗留改动：
git add -A && git commit -m "chore(insights): P1 派生层回归通过"
```

---

## Self-Review

**1. Spec coverage（对照设计文档 §4 Tier1）：**
- §4.2 timing 派生 → Task 6 ✅
- §4.2 hiring（规模/热门/城市/趋势）→ Task 7 ✅
- §4.2 compensation 薪资带 from `salary_text` → Task 4/5 ✅
- §4「100% 覆盖、无画像也派生」→ Task 9（对无 profile 公司仍派生）✅
- §4「永远新鲜」→ read-time 派生，`last_verified_at=now`，每次请求重算 ✅
- 展示「与岗位层分离 + 派生区分」→ Task 10 派生芯片 + banner ✅
- 偏离记录：read-time 替代物化 → 已在 Architecture 段标注理由 ✅

**2. Placeholder scan：** 无 TBD/TODO；每个代码步骤含完整代码；每个测试步骤含真实断言；命令含预期输出。✅

**3. Type consistency：**
- `classifyRecruitment` / `parseSalaryText` / `deriveSalaryBand` / `deriveTiming` / `deriveHiring` / `deriveCompanyInsights` 命名在 plan 内与测试调用一致 ✅
- `makeDerivedView` 产出满足 `InsightItemView`（Task 1 加 `derived?`）✅
- `RecruitBucket` 四值与 `mix` 键一致（campus/intern/social/unknown）✅
- `InsightDimension` 加 `hiring` 后，`emptyDimensions`/`DIMENSION_META`/`DIMENSION_ORDER` 同步（Task 2/10）——三处都覆盖 ✅
- `/api/insights` 用到的 `deriveCompanyInsights`、`Job`、`emptyDimensions`、`INSIGHT_DIMENSIONS` 均已导入 ✅

**4. 边界确认：** P1 不动 DB（无迁移）、不动 crawler、不动 GH Actions、零 LLM、零外部请求、零付费——符合成本红线。✅
