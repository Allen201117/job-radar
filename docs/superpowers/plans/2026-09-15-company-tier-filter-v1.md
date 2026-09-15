# 公司类型筛选 v1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 让用户在 /jobs 按「公司类型」(大厂/央国企/外企/初创独角兽/中小厂)筛选,数据来自已策展的 `lib/company-tiers.json`,走名字匹配 + SQL 下推,与「必投清单」同机制。

**Architecture:** `lib/company-tiers.ts` 从 JSON 派生 `classifyCompanyTier(company)` 与 `companyTierPatterns(tiers)`;`companyTier` 加进 `Filters` 走 **SQL_PUSHED**——正向标签 `company ilike any(patterns)`、`中小厂` = `company not ilike any(全部命名标签 patterns)`;JS 侧 `jobFilterMatch` 用同一 `classifyCompanyTier` 做权威判定,两端语义一致 → 计数仍精确。前台 `JobFilters` 加一组「公司类型」标签(多选)。

**Tech Stack:** TypeScript(lib/纯函数 + 组件)、Node `node --test`。无 schema、无 Supabase、无新表。

**Spec:** `docs/superpowers/specs/2026-09-15-company-tiering-sme-expansion-design.md`(附录 D)

## Global Constraints
- 标签数据唯一来源 = `lib/company-tiers.json`;`中小厂` 不在 JSON 里列举,= 不命中任何命名标签的兜底。
- **SQL 下推与 JS 判定必须语义一致**(同一份 patterns、同为大小写不敏感子串),否则 `filtersFullyPushedToSql` 会给错数(计数契约,CLAUDE.md 红线)。
- 新增 `companyTier` 必须在 `SQL_PUSHED_FILTER_KEYS`/`JS_ONLY_FILTER_KEYS`/`NON_FILTERING_FILTER_KEYS` 三表**显式归类**,否则 `tests/ux-hardening-contract.test.js` 直接红。
- 张冠李戴:patterns 已在库内实测零冲突;新增标签值只从 JSON 读,不在 UI 硬编码第二份。
- 不丢岗/不改 count 语义/不碰 spreadByCompany 分散逻辑。
- 执行前 `export MAIN_REPO=<主仓绝对路径>`;命令用 `"$MAIN_REPO"`,不写绝对路径。

---

### Task 1: `lib/company-tiers.ts` 派生模块 + 测试

**Files:**
- Create: `lib/company-tiers.ts`
- Create: `tests/company-tiers.test.js`

**Interfaces:**
- Produces:
  - `COMPANY_TIER_LABELS: readonly string[]` = `["大厂","央国企","外企","初创独角兽","中小厂"]`(展示顺序;前 4 个来自 JSON key,`中小厂` 末尾兜底)。
  - `classifyCompanyTier(company: string): string` —— 按 JSON 里 key 的顺序返回**第一个**命中标签(patterns 子串、大小写不敏感);都不命中 → `"中小厂"`。
  - `companyTierPatterns(tiers: string[]): { named: string[]; includeSmb: boolean }` —— 把选中的标签解析成:`named`=所有选中的**命名标签**(非中小厂)的 pattern 列表;`includeSmb`=是否选了「中小厂」。供 SQL 下推用。
  - `NAMED_TIER_PATTERNS: string[]` —— 全部命名标签的 pattern 合集(算「中小厂 = not ilike any」用)。

- [ ] **Step 1: 写失败测试**

```js
// tests/company-tiers.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const { loadTs } = require("./_load-ts");
const { classifyCompanyTier, companyTierPatterns, COMPANY_TIER_LABELS, NAMED_TIER_PATTERNS } =
  loadTs("../lib/company-tiers.ts");

test("命中命名标签", () => {
  assert.equal(classifyCompanyTier("字节跳动"), "大厂");
  assert.equal(classifyCompanyTier("中国交建 校招"), "央国企");
  assert.equal(classifyCompanyTier("Apple"), "外企");
  assert.equal(classifyCompanyTier("MiniMax 稀宇科技"), "初创独角兽");
});

test("不命中任何名单 → 中小厂兜底", () => {
  assert.equal(classifyCompanyTier("某不知名小公司有限公司"), "中小厂");
  assert.equal(classifyCompanyTier(""), "中小厂");
});

test("标签顺序:中小厂在末尾", () => {
  assert.deepEqual(COMPANY_TIER_LABELS[COMPANY_TIER_LABELS.length - 1], "中小厂");
  assert.ok(COMPANY_TIER_LABELS.includes("大厂"));
});

test("companyTierPatterns 拆解正确", () => {
  const r = companyTierPatterns(["大厂", "中小厂"]);
  assert.ok(r.includeSmb === true);
  assert.ok(r.named.some((p) => p.includes("字节")));
  const r2 = companyTierPatterns(["外企"]);
  assert.equal(r2.includeSmb, false);
  assert.ok(r2.named.length > 0);
});

test("NAMED_TIER_PATTERNS 覆盖所有命名标签、不含中小厂", () => {
  assert.ok(NAMED_TIER_PATTERNS.length >= 100); // 大厂+央国企+外企+独角兽 patterns 合计
  // 中小厂无 pattern,不应出现
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "$MAIN_REPO" && node --test tests/company-tiers.test.js`
Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现**

```ts
// lib/company-tiers.ts
// 公司类型标签:唯一数据源 lib/company-tiers.json。名字子串匹配 + 中小厂兜底。
// SQL 下推与本文件的 classify 必须语义一致(同 patterns、同大小写不敏感子串)。
import tiersData from "./company-tiers.json";

type TierEntry = { name: string; pattern: string };
const RAW = tiersData as Record<string, unknown>;
// JSON key 顺序即优先级;排除 _meta。
const NAMED_TIERS: string[] = Object.keys(RAW).filter((k) => k !== "_meta");
export const COMPANY_TIER_LABELS: readonly string[] = [...NAMED_TIERS, "中小厂"];

const patternsOf = (tier: string): string[] =>
  ((RAW[tier] as TierEntry[]) || []).map((e) => e.pattern);

// pattern("%字节%") → 核心子串 "字节"(小写)
const core = (pat: string): string => pat.replace(/%/g, "").trim().toLowerCase();

export const NAMED_TIER_PATTERNS: string[] = NAMED_TIERS.flatMap(patternsOf);

export function classifyCompanyTier(company: string): string {
  const name = (company || "").toLowerCase();
  if (name) {
    for (const tier of NAMED_TIERS) {
      for (const pat of patternsOf(tier)) {
        if (name.includes(core(pat))) return tier;
      }
    }
  }
  return "中小厂";
}

export function companyTierPatterns(tiers: string[]): { named: string[]; includeSmb: boolean } {
  const set = new Set(tiers);
  const named: string[] = [];
  for (const tier of NAMED_TIERS) {
    if (set.has(tier)) named.push(...patternsOf(tier));
  }
  return { named, includeSmb: set.has("中小厂") };
}
```

- [ ] **Step 4: 运行确认通过**
Run: `cd "$MAIN_REPO" && node --test tests/company-tiers.test.js` → PASS(5 个)

- [ ] **Step 5: Commit**
```bash
git add lib/company-tiers.ts tests/company-tiers.test.js
git commit -m "feat(tiering): company-tiers.ts 标签派生模块(classify + patterns,中小厂兜底)"
```

---

### Task 2: `companyTier` 接入 Filters + 检索层(SQL 下推 + JS 判定)

**Files:**
- Modify: `lib/job-filter.ts`(Filters 类型 / DEFAULT_FILTERS / 三张 registry 表 / jobFilterMatch)
- Modify: `lib/jobs-store/search.ts`(conds 构建处,company 过滤附近)
- Modify: `tests/ux-hardening-contract.test.js`(如需——三表并集断言会强制覆盖新 key)

**Interfaces:**
- Consumes: `classifyCompanyTier`, `companyTierPatterns`, `NAMED_TIER_PATTERNS`(Task 1)。

- [ ] **Step 1: 写失败测试(jobFilterMatch 侧)**

在 `tests/` 下已有 job-filter 测试文件里加(或新建 `tests/company-tier-filter.test.js`):
```js
const { test } = require("node:test");
const assert = require("node:assert");
const { loadTs } = require("./_load-ts");
const { jobFilterMatch, DEFAULT_FILTERS } = loadTs("../lib/job-filter.ts");

const mk = (company) => ({ id: "1", company, title: "工程师", summary: "x".repeat(80),
  jd_url: "https://e.com/1", location: "北京", recruitment_category: "社招" });

test("companyTier=大厂 只放行大厂", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "大厂" };
  assert.ok(jobFilterMatch(mk("字节跳动"), f) !== null);
  assert.ok(jobFilterMatch(mk("某小公司"), f) === null);
});
test("companyTier=中小厂 只放行兜底", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "中小厂" };
  assert.ok(jobFilterMatch(mk("某小公司"), f) !== null);
  assert.ok(jobFilterMatch(mk("字节跳动"), f) === null);
});
test("companyTier 多选=并集", () => {
  const f = { ...DEFAULT_FILTERS, companyTier: "大厂,外企" };
  assert.ok(jobFilterMatch(mk("字节跳动"), f) !== null);
  assert.ok(jobFilterMatch(mk("Apple"), f) !== null);
  assert.ok(jobFilterMatch(mk("某小公司"), f) === null);
});
```

- [ ] **Step 2: 运行确认失败** → `node --test`,报 companyTier 未定义或不筛。

- [ ] **Step 3: 改 `lib/job-filter.ts`**
  - `Filters` 加 `companyTier: string;`(逗号分隔多选,""=不限)。
  - `DEFAULT_FILTERS` 加 `companyTier: ""`。
  - 归类:加进 **`SQL_PUSHED_FILTER_KEYS`**,注释:`// 标签→公司名 patterns，SQL 与 classifyCompanyTier 同口径`。
  - `jobFilterMatch` 里加判定:`companyTier` 非空时,`splitMultiValue(filters.companyTier)` 得选中标签,`classifyCompanyTier(job.company)` 不在选中集合 → 返回 null(不匹配)。放在现有各硬过滤同一段。

- [ ] **Step 4: 改 `lib/jobs-store/search.ts`**
  在 `company ilike` 那段附近(`filters.company` 之后),加 companyTier 下推:
```ts
const tierSel = splitMultiValue(filters.companyTier);
if (tierSel.length) {
  const { named, includeSmb } = companyTierPatterns(tierSel);
  const ors: string[] = [];
  if (named.length) {
    const ph = named.map((p) => { params.push(p); return `company ilike $${params.length}`; });
    ors.push(`(${ph.join(" or ")})`);
  }
  if (includeSmb) {
    const ph = NAMED_TIER_PATTERNS.map((p) => { params.push(p); return `company not ilike $${params.length}`; });
    ors.push(ph.length ? `(${ph.join(" and ")})` : "true");
  }
  if (ors.length) conds.push(`(${ors.join(" or ")})`);
}
```
  在 search.ts 顶部 import `companyTierPatterns, NAMED_TIER_PATTERNS` from `@/lib/company-tiers`(或相对路径),`splitMultiValue` 已有。

- [ ] **Step 5: 运行 node 测试 + tsc + 契约测试** → 全绿(尤其 ux-hardening-contract 的三表并集断言)。
Run: `cd "$MAIN_REPO" && node --test tests/*.test.js && npx tsc --noEmit -p tsconfig.json 2>&1 | head`

- [ ] **Step 6: Commit**
```bash
git add lib/job-filter.ts lib/jobs-store/search.ts tests/
git commit -m "feat(tiering): companyTier 筛选(SQL 下推 named/中小厂负向 + JS 同口径判定)"
```

---

### Task 3: `JobFilters.tsx` 加「公司类型」筛选 UI

**Files:**
- Modify: `components/JobFilters.tsx`

**Interfaces:**
- Consumes: `COMPANY_TIER_LABELS`(Task 1)。

- [ ] **Step 1: 读现状** —— 看 JobFilters 里现有多选维度(如 jobFunction/education)怎么渲染 chip、怎么写回 filters,照抄同一形态。公司类型是多选逗号分隔,和 jobFunction 同构。
- [ ] **Step 2: 加 UI** —— 在筛选弹层里加一组「公司类型」标签(多选),值域 = `COMPANY_TIER_LABELS`(从 lib 读,不硬编码第二份);选中写回 `filters.companyTier`(逗号分隔)。已选 chip 行同步显示。
- [ ] **Step 3: 类型/lint/build**
Run: `cd "$MAIN_REPO" && npx tsc --noEmit -p tsconfig.json 2>&1 | head && npm run build 2>&1 | tail -5`
- [ ] **Step 4: Commit**
```bash
git add components/JobFilters.tsx
git commit -m "feat(tiering): JobFilters 加公司类型筛选(多选,值域取自 COMPANY_TIER_LABELS)"
```

---

### Task 4: Live 验证(controller)
- 匿名 curl 生产/本地 `/api/jobs/search?city=北京&companyTier=中小厂&sortBy=match` 与 `...&companyTier=大厂`,确认返回公司确实分别落在中小厂/大厂;`total` 合理;不选时行为不变。
- 对拍:同 city 下 `companyTier=大厂` 的公司应全部在 JSON 大厂名单里;`companyTier=中小厂` 的公司应全部不在任何命名名单里。

## 自检
- Spec 覆盖:实现附录 D 的「策展名单 + SQL 下推」筛选。故意不做:三轴精确字段、company_size_signals 表、工商数据源(长期方案)。
- 契约:companyTier 归 SQL_PUSHED,SQL(ilike any / not ilike any)与 JS(classifyCompanyTier)同口径 → 计数精确;三表并集断言强制覆盖新 key。
- 边界:中小厂是兜底非断言;patterns 库内实测零冲突;名单可持续补(改 JSON 一处)。
