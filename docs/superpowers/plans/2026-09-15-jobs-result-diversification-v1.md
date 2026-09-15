# /jobs 结果分散(公司维度)v1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /jobs 默认(match)排序做**公司维度分散**,让每城已在库的几百家中小公司在前几页露出,不再被 ~90 家大厂的岗位刷屏——**不丢任何岗、不改 total/分页契约**。

**Architecture:** 新增纯函数 `spreadByCompany(ranked, opts)`:对排序后数组的**头部**(前 ~200 条,用户真正翻的范围)做滑窗贪心稳定重排(单公司在任一 `window` 窗口内 ≤ `cap`,超出的下压;尾部原样保留),**保长度、确定性**。在 `lib/jobs-store/search.ts` 的 FTS 与 scan 两条路径、`filterAndRankJobs`(及 `collapseBulkStoreJobs`)之后、`slice(offset,limit)` 之前注入,**仅当 `sortBy !== 'newest'`**(newest 用户要严格时序,不动)。

**Tech Stack:** TypeScript(lib 纯函数)、Node `node --test`(契约测试,经 `tests/_load-ts.js` 加载 .ts)、香港 PG(只读 live 验证)。无前端改动、无 schema 改动。

**Spec:** `docs/superpowers/specs/2026-09-15-company-tiering-sme-expansion-design.md`(§5.2 结果分散)

## Global Constraints

- **不丢岗**:分散是**纯重排**(同一多集,长度不变)——`total = ranked.length` 与 `hasMore` 因此不受影响。绝不删元素(spec §5.2 + CLAUDE.md「total 语义=可翻页条数」红线)。
- **确定性**:`spreadByCompany` 必须是纯函数(同输入→同输出),否则跨页 `slice` 会错位、「加载更多」重复/漏条。
- **perf**:/jobs 冷路径已 14~16s(CLAUDE.md),分散只处理头部 `headOnly`(默认 200),成本 O(headOnly×window) 与候选总量(可达 28000)无关。
- **不碰 newest**:`sortBy==='newest'` 时跳过分散(用户要严格时序)。
- **不改 count 逻辑**:`countExact`/`formatMatchTotal`/`exactTotal` 都是对数组计数,与顺序无关,重排后自动仍正确——但不得改它们。
- 执行前先设 `export MAIN_REPO=<你的主仓绝对路径>`(`.env.local` 所在);本仓公开,命令用 `"$MAIN_REPO"` 引用它,文档不写绝对路径。

---

### Task 1: `spreadByCompany` 纯函数 + 契约测试

**Files:**
- Create: `lib/job-diversify.ts`
- Create: `tests/job-diversify.test.js`

**Interfaces:**
- Produces: `spreadByCompany<T extends { company?: string | null; id?: string; jd_url?: string | null }>(ranked: T[], opts?: { cap?: number; window?: number; headOnly?: number }): T[]` —— 返回与输入**同长、同多集**的新数组;头部 `headOnly` 内单公司在任一 `window` 连续窗口 ≤ `cap`(除非剩余全是该公司);尾部原序不变;`ranked.length <= window` 时原样返回。默认 `cap=3, window=10, headOnly=200`。

- [ ] **Step 1: 写失败测试**

```js
// tests/job-diversify.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const { loadTs } = require("./_load-ts");
const { spreadByCompany } = loadTs("../lib/job-diversify.ts");

const J = (company, id) => ({ company, id: String(id) });
const multiset = (arr) => arr.map((j) => j.id).sort().join(",");

test("保多集:重排前后同一批 job(长度+成员不变)", () => {
  const ranked = [];
  for (let i = 0; i < 300; i++) ranked.push(J(i < 200 ? "字节跳动" : "小公司" + i, i));
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  assert.equal(out.length, ranked.length);
  assert.equal(multiset(out), multiset(ranked)); // 一个都没丢、没多
});

test("头部窗口内单公司不超 cap(有别家可换时)", () => {
  // 100 个字节 + 穿插 100 个不同小公司,交替喂入
  const ranked = [];
  for (let i = 0; i < 100; i++) { ranked.push(J("字节跳动", "b" + i)); ranked.push(J("小" + i, "s" + i)); }
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  // 检查头部每个长度 10 的滑窗里字节 ≤ 3
  for (let k = 0; k + 10 <= 200 && k + 10 <= out.length; k++) {
    const win = out.slice(k, k + 10).filter((j) => j.company === "字节跳动").length;
    assert.ok(win <= 3, `窗口[${k},${k + 10}) 字节=${win} 超过 cap`);
  }
});

test("确定性:同输入同输出", () => {
  const ranked = [];
  for (let i = 0; i < 250; i++) ranked.push(J("c" + (i % 7), i));
  assert.equal(multiset(spreadByCompany(ranked)), multiset(spreadByCompany(ranked)));
  assert.deepEqual(spreadByCompany(ranked).map((j) => j.id), spreadByCompany(ranked).map((j) => j.id));
});

test("尾部(headOnly 之后)原序不动", () => {
  const ranked = [];
  for (let i = 0; i < 300; i++) ranked.push(J("字节跳动", i)); // 全同一家
  const out = spreadByCompany(ranked, { cap: 3, window: 10, headOnly: 200 });
  const tailIn = ranked.slice(200).map((j) => j.id);
  const tailOut = out.slice(out.length - 100).map((j) => j.id);
  assert.deepEqual(tailOut, tailIn); // 尾部 100 条顺序不变
});

test("短结果集(<=window)原样返回", () => {
  const ranked = [J("a", 1), J("a", 2), J("b", 3)];
  assert.deepEqual(spreadByCompany(ranked, { window: 10 }).map((j) => j.id), ["1", "2", "3"]);
});

test("全是一家公司:不死循环,长度守恒", () => {
  const ranked = [];
  for (let i = 0; i < 500; i++) ranked.push(J("独苗", i));
  const out = spreadByCompany(ranked);
  assert.equal(out.length, 500);
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "$MAIN_REPO" && node --test tests/job-diversify.test.js`
Expected: FAIL(`Cannot find module '../lib/job-diversify.ts'` 或 `spreadByCompany is not a function`)

- [ ] **Step 3: 实现纯函数**

```ts
// lib/job-diversify.ts
// /jobs 结果分散:头部滑窗贪心稳定重排,单公司在任一 window 内 ≤ cap,超出下压。
// 纯重排:同长、同多集、确定性 → 不影响 total/分页。只处理头部,perf 与候选总量无关。

type Diversifiable = { company?: string | null; id?: string; jd_url?: string | null };

const companyKey = (j: Diversifiable): string =>
  (j.company || `id:${j.id ?? j.jd_url ?? ""}`).trim().toLowerCase();

export function spreadByCompany<T extends Diversifiable>(
  ranked: T[],
  opts: { cap?: number; window?: number; headOnly?: number } = {},
): T[] {
  const cap = opts.cap ?? 3;
  const window = opts.window ?? 10;
  const headOnly = opts.headOnly ?? 200;
  if (ranked.length <= window) return ranked;

  const head = ranked.slice(0, headOnly);
  const tail = ranked.slice(headOnly);

  const out: T[] = [];
  const deferred: T[] = []; // 被下压的,保持相对 rank 顺序
  // 当前窗口(out 末尾 window 条)内各公司计数;增量维护,O(1) 每步。
  const winCount = new Map<string, number>();
  const bump = (co: string, d: number) => {
    const n = (winCount.get(co) ?? 0) + d;
    if (n <= 0) winCount.delete(co); else winCount.set(co, n);
  };
  const emit = (item: T) => {
    out.push(item);
    bump(companyKey(item), 1);
    if (out.length > window) bump(companyKey(out[out.length - 1 - window]), -1);
  };

  let i = 0;
  while (out.length < head.length) {
    // 1) 优先从 deferred 里找一个当前窗口未超 cap 的(rank 顺序,取最靠前那个)
    let placed = -1;
    for (let d = 0; d < deferred.length; d++) {
      if ((winCount.get(companyKey(deferred[d])) ?? 0) < cap) { placed = d; break; }
    }
    if (placed >= 0) { emit(deferred.splice(placed, 1)[0]); continue; }
    // 2) 否则取 head 下一个:未超 cap 就放,超了就压入 deferred
    if (i < head.length) {
      const next = head[i++];
      if ((winCount.get(companyKey(next)) ?? 0) < cap) emit(next);
      else deferred.push(next);
      continue;
    }
    // 3) head 取尽且 deferred 全超 cap → 只能违反 cap,按 rank 顺序放(避免死循环)
    emit(deferred.shift() as T);
  }
  return out.concat(tail);
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "$MAIN_REPO" && node --test tests/job-diversify.test.js`
Expected: PASS(全部 6 个)

- [ ] **Step 5: Commit**

```bash
git add lib/job-diversify.ts tests/job-diversify.test.js
git commit -m "feat(jobs): spreadByCompany 结果分散纯函数(头部滑窗,保多集不丢岗)"
```

---

### Task 2: 接入 search.ts 两条检索路径(仅 match 排序)

**Files:**
- Modify: `lib/jobs-store/search.ts`(FTS 路径 `~line 425` 前、scan 路径 `line 539-541` 处)
- Modify: `lib/jobs-store/search.ts` 顶部 import

**Interfaces:**
- Consumes: `spreadByCompany`(Task 1)。

- [ ] **Step 1: 读现状锚点**

Run: `cd "$MAIN_REPO" && grep -n "filterAndRankJobs\|collapseBulkStoreJobs\|const page = ranked.slice\|ranked.length" lib/jobs-store/search.ts`
Expected: 看到 FTS 路径与 scan 路径各有一处 `filterAndRankJobs(...)` → `ranked` → `ranked.slice(offset, offset+limit)` → `total: ranked.length`。确认两处注入点。

- [ ] **Step 2: 加 import**

在 `lib/jobs-store/search.ts` 顶部已有 `filterAndRankJobs` 的 import 附近加:
```ts
import { spreadByCompany } from "../job-diversify";
```
(路径按该文件现有相对 import 风格调整;search.ts 在 `lib/jobs-store/`,job-diversify 在 `lib/` → `../job-diversify`。)

- [ ] **Step 3: scan 路径注入(line 539 附近)**

把:
```ts
const ranked = collapseBulkStoreJobs(filterAndRankJobs(matched, filters));
```
改为:
```ts
const rankedRaw = collapseBulkStoreJobs(filterAndRankJobs(matched, filters));
const ranked = filters.sortBy === "newest" ? rankedRaw : spreadByCompany(rankedRaw);
```
`total: ranked.length` 与 `ranked.slice(offset, offset + limit)` 不变(重排保长度)。

- [ ] **Step 4: FTS 路径注入(line 425 附近)**

找到 FTS 路径里生成 `ranked`(`filterAndRankJobs(...)` 的返回)那一行,同样包一层:
```ts
// 原:const ranked = <filterAndRankJobs 表达式>;
const rankedRaw = <filterAndRankJobs 表达式>;   // 保持原表达式不变
const ranked = filters.sortBy === "newest" ? rankedRaw : spreadByCompany(rankedRaw);
```
(若 FTS 路径也用了 `collapseBulkStoreJobs` 包裹,一并保留在 `rankedRaw` 里。)

- [ ] **Step 5: 类型/构建校验 + lint(worktree 用 --dir)**

Run:
```bash
cd "$MAIN_REPO" && npx tsc --noEmit -p tsconfig.json 2>&1 | head -20
cd "$MAIN_REPO" && npx next lint --dir lib 2>&1 | tail -15
```
Expected: 无 type error;lint 无新增 error。(worktree 里直接 `next lint` 会 plugin 冲突,故用 `--dir lib`。)

- [ ] **Step 6: 回归四件套里跑 node 单测 + build**

Run:
```bash
cd "$MAIN_REPO" && node --test tests/*.test.js 2>&1 | tail -15 && npm run build 2>&1 | tail -8
```
Expected: 所有 node 测试 PASS(尤其 `tests/ux-hardening-contract.test.js` / match-total 相关不红);build 成功。

- [ ] **Step 7: Commit**

```bash
git add lib/jobs-store/search.ts
git commit -m "feat(jobs): match 排序接入公司分散(FTS+scan 两路,newest 不动,保 total)"
```

---

### Task 3: Live 前后对拍(确认露出改善 + total 不变)

**Files:**
- 无(只读验证 + 记录)。

**Interfaces:**
- Consumes: 已部署或本地 dev 的 `/api/jobs/search`(允许匿名 curl)。

- [ ] **Step 1: 本地起 dev(用改后的代码)**

Run: `cd "$MAIN_REPO" && npm run dev`(后台),等待就绪。
> 注:`npm run build` 与 `npm run dev` 不要同时;若刚 build 过要重启 dev。

- [ ] **Step 2: 对拍「前 20 条不同公司数」(北京 社招 match)**

Run:
```bash
curl -s 'http://localhost:3000/api/jobs/search?city=北京&recruitmentCategory=社招&sortBy=match&limit=20' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); jobs=d.get('jobs',d.get('results',[])); import collections; c=collections.Counter(j.get('company') for j in jobs); print('前20不同公司数:', len(c)); print('最大一家占:', c.most_common(1)); print('total:', d.get('total'))"
```
Expected: **不同公司数明显高于接入前**(接入前该位置常被单家占 8~16 条);`total` 与接入前同一请求一致(重排不改 total)。

- [ ] **Step 3: 对拍 total 守恒(关键回归)**

同一 city/category,分别请求 `sortBy=match` 与 `sortBy=newest`,确认两者 `total` 与接入前记录一致(分散没吃掉任何条数)。newest 的结果顺序应与接入前**完全一致**(未被分散触碰)。

- [ ] **Step 4: 记录数字到 spec 附录**

把「北京/上海/深圳 前 20 不同公司数 接入前 vs 接入后」「total 守恒确认」写进 spec 附录 B。**双向报**:既报「不同公司数↑多少」,也确认「total、单页条数没掉」。

- [ ] **Step 5: 停 dev**

Run: 停掉后台 dev server。

---

## 自检(对着 spec §5.2 复查)

- **Spec 覆盖**:实现 §5.2「结果分散……按页面处理……不能把溢出岗位永久丢弃」——`spreadByCompany` 纯重排不丢岗(Task 1 多集测试钉死),仅 match 排序、newest 不动(Task 2)。
- **占位符扫描**:无 TBD;`filterAndRankJobs 表达式` 在 Task 2 Step 4 明确要求「保持原表达式不变、只包一层」,不是占位。
- **类型一致**:`spreadByCompany<T>` 泛型接受 `filterAndRankJobs` 返回的 `ScoredJob & {__tier,__match}`(结构含 company/id/jd_url,满足 `Diversifiable` 约束);Task 2 传入的 `rankedRaw` 正是该类型,一致。
- **红线复核**:`total = ranked.length` 在重排后不变(长度守恒),`countExact`/`formatMatchTotal` 与顺序无关 → match-total 契约不破(Task 2 Step 6 的 ux-hardening 契约测试兜底)。
- **诚实边界**:分散只治「曝光」——它让已在库的中小公司露出,不新增供给;若某城真库存薄,分散无岗可分。这与「先做结果分散」的定位一致,规模标签/扩源是后续 plan。
