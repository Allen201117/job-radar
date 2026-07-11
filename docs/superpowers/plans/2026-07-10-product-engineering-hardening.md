# Product and Engineering Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复求职雷达当前最影响用户信任和生产安全的缺陷，并建立可以自动验收的回归门。

**Architecture:** 鉴权统一复用 `requireUser()`；推荐质量规则保持在纯函数 `lib/opportunities/grouping.ts`；统计缓存由 Route Handler 响应头与客户端轮询共同控制；依赖升级放在所有行为改动之后，便于定位兼容问题。数据库 TLS/灾备本轮只增加明确的运维门，不在缺少生产 CA 和云平台权限时改变线上连接行为。

**Tech Stack:** Next.js App Router、React 18、TypeScript、Node `node:test`、PostgreSQL、Supabase、Python unittest。

---

### Task 1: Harden liveness API authentication

**Files:**
- Create: `tests/liveness-api-security.test.js`
- Modify: `app/api/jobs/liveness-check/route.ts`
- Modify: `app/api/jobs/[jobId]/liveness/route.ts`

- [ ] **Step 1: Write failing route tests**

Create tests using `tests/route-test-utils.js::loadRoute` that provide a mocked `requireUser()` returning a 401 `Response`, counters for `createServiceClient`, `jobsByIds`, `checkLiveness`, `markJobExpiredById`, `touchJobCheckedById`, and a request whose `json()` increments a counter. Assert both route handlers return 401 and every counter remains zero.

Add an authenticated single-job case with this contract:

```js
const USER = { id: "verified-user", email: "verified@example.com" };
const tracked = [];
// requireUser returns USER; service/read/liveness mocks return one active supported job.
// trackServerEvent pushes [userId, event, payload] into tracked.
assert.equal(response.status, 200);
assert.equal(tracked.length, 1);
assert.equal(tracked[0][0], USER.id);
assert.equal(tracked[0][1], "job_liveness_at_click");
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
node --test tests/liveness-api-security.test.js
```

Expected: FAIL because the routes import/use `hasSessionCookie`, the unauthenticated path does not return 401, and the single-job event reads `getRequestUser()`.

- [ ] **Step 3: Implement the minimal authentication change**

Both handlers must start with:

```ts
const auth = await requireUser();
if (auth.error) return auth.error;
```

Remove `hasSessionCookie` from both routes and `getRequestUser` from the single-job route. Keep existing service-role access and liveness behavior unchanged after authentication. Record the event with:

```ts
await trackServerEvent(service as any, auth.user.id, "job_liveness_at_click", {
  job_id: jobId,
  adapter,
  result,
});
```

- [ ] **Step 4: Verify GREEN and related security tests**

Run:

```bash
node --test tests/liveness-api-security.test.js tests/api-security.test.js tests/click-validity-metric.test.js
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add tests/liveness-api-security.test.js app/api/jobs/liveness-check/route.ts 'app/api/jobs/[jobId]/liveness/route.ts'
git commit -m "fix(security): require verified users for liveness writes"
```

### Task 2: Deduplicate and diversify Today opportunities

**Files:**
- Modify: `tests/opportunity-grouping.test.js`
- Modify: `lib/opportunities/grouping.ts`
- Modify: `components/JobCard.tsx`
- Modify: `jobs-db/schema.sql`
- Create: `tests/product-trust-contract.test.js`

- [ ] **Step 1: Write failing grouping tests**

Extend the test helper so each opportunity may specify `company`, `title`, and `location`. Add these behaviors:

```js
test("different ids with the same company title and location appear once", () => {
  const a = opp({ id: "a", company: "字节跳动", title: "AI 产品经理", location: "上海", score: 90 });
  const b = opp({ id: "b", company: " 字节跳动 ", title: "ai产品经理", location: "上海市", score: 80 });
  const { sections } = groupOpportunities([a, b], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.main.map((item) => item.job.id), ["a"]);
});

test("main prefers company diversity when alternatives exist", () => {
  const dominant = Array.from({ length: 8 }, (_, i) => opp({ id: `a${i}`, company: "A", title: `T${i}`, score: 100 - i }));
  const alternatives = ["B", "C", "D", "E", "F", "G", "H"].map((company, i) =>
    opp({ id: `x${i}`, company, title: `X${i}`, score: 70 - i }),
  );
  const { sections } = groupOpportunities([...dominant, ...alternatives], { dailyLimit: 10, intensity: "active" });
  assert.equal(sections.main.length, 10);
  assert.ok(sections.main.filter((item) => item.job.company === "A").length <= 3);
});

test("main backfills from one company instead of returning an artificial empty list", () => {
  const only = Array.from({ length: 10 }, (_, i) => opp({ id: `a${i}`, company: "A", title: `T${i}` }));
  const { sections } = groupOpportunities(only, { dailyLimit: 10, intensity: "active" });
  assert.equal(sections.main.length, 10);
});
```

Normalization must treat case, whitespace, punctuation, `上海/上海市` and similar trailing `市` differences as equivalent, but if company/title/location is missing it must fall back to job ID.

- [ ] **Step 2: Verify grouping RED**

Run:

```bash
node --test tests/opportunity-grouping.test.js
```

Expected: the semantic duplicate and diversity tests fail while existing grouping tests remain green.

- [ ] **Step 3: Implement pure helpers and wire them into grouping**

Add focused helpers in `grouping.ts`:

```ts
function semanticJobKey(opportunity: Opportunity): string;
function dedupeBySemanticJob(opportunities: Opportunity[]): Opportunity[];
function takeWithCompanyDiversity(opportunities: Opportunity[], limit: number): Opportunity[];
```

`takeWithCompanyDiversity` uses `Math.max(2, Math.ceil(limit * 0.3))` as the first-pass per-company cap, then backfills from skipped rows until `limit`. Apply semantic dedupe before any section is formed. Apply diversity only after sorting `main` and `explore`; do not cap `critical` or `waiting`.

- [ ] **Step 4: Add failing source-contract tests for labels and SQL**

Create `tests/product-trust-contract.test.js` that reads source files and asserts:

```js
assert.match(jobCardSource, /label:\s*"官网发布"/);
assert.match(schemaSource, /active_job_counts_by_company[\s\S]*summary is not null/i);
assert.match(schemaSource, /active_job_counts_by_company[\s\S]*char_length\(btrim\(j\.summary\)\)\s*>=\s*60/i);
```

Run the new file and verify it fails before production changes.

- [ ] **Step 5: Correct the UI and company-count contracts**

Change the `posted_at` metadata label in `JobCard.tsx` from `发布` to `官网发布`. Update `active_job_counts_by_company()` in `jobs-db/schema.sql` to require non-null trimmed summary length of at least 60, matching `count_valid_active_jobs()`.

- [ ] **Step 6: Verify Task 2**

Run:

```bash
node --test tests/opportunity-grouping.test.js tests/product-trust-contract.test.js tests/freshness-label.test.js tests/opportunity-scoring.test.js
bash scripts/check-migrations.sh
```

Expected: all tests and migration checks pass.

- [ ] **Step 7: Commit only Task 2 files**

```bash
git add tests/opportunity-grouping.test.js tests/product-trust-contract.test.js lib/opportunities/grouping.ts components/JobCard.tsx jobs-db/schema.sql
git commit -m "fix(product): dedupe and diversify daily opportunities"
```

### Task 3: Cache stats and fix critical UX accessibility gaps

**Files:**
- Create: `tests/ux-hardening-contract.test.js`
- Modify: `app/api/jobs/stats/route.ts`
- Modify: `components/JobLibraryStat.tsx`
- Modify: `components/TagInput.tsx`
- Modify: `components/PreferenceForm.tsx`
- Modify: `components/ResumeProfilePanel.tsx`
- Modify: `components/Navbar.tsx`
- Modify: `app/applied/page.tsx`

- [ ] **Step 1: Write a failing source-contract test**

The test must assert all of these contracts:

```js
assert.match(statsRoute, /public,\s*s-maxage=60,\s*stale-while-revalidate=300/);
assert.match(statComponent, /60_000|60000/);
assert.doesNotMatch(statComponent, /轮询间隔 12s/);
assert.match(tagInput, /ariaLabel:\s*string/);
assert.match(tagInput, /aria-label=\{ariaLabel\}/);
assert.doesNotMatch(navbar, /<button[\s\S]{0,180}aria-label="关闭菜单"[\s\S]{0,180}className="fixed inset-0 top-14/);
assert.match(appliedPage, /在岗位卡片里点击「标记投递」/);
assert.match(appliedPage, /href="\/today"/);
```

Also scan every `<TagInput` call in `PreferenceForm.tsx` and `ResumeProfilePanel.tsx` and fail if the call does not contain an `ariaLabel` prop.

- [ ] **Step 2: Verify UX RED**

Run:

```bash
node --test tests/ux-hardening-contract.test.js
```

Expected: multiple assertions fail against the current implementation.

- [ ] **Step 3: Implement cache and polling changes**

Return successful stats responses with:

```ts
{ headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300" } }
```

Use a named `const POLL_INTERVAL_MS = 60_000` in `JobLibraryStat.tsx`, retain visibility checks and manual refresh, and display “轮询间隔 60s”. Do not change the stale fallback.

- [ ] **Step 4: Implement accessible labels and empty-state action**

Make `ariaLabel: string` a required `TagInput` prop and set `aria-label={ariaLabel}` on the input. Add a specific label at every call site, such as `目标城市`、`目标岗位方向`、`关注公司`、`技能`、`目标行业`.

Replace the mobile backdrop `<button>` with a non-focusable `<div aria-hidden="true">` that keeps the same click-to-close behavior and visual classes.

Update the empty state to:

```tsx
<EmptyPanel
  title="还没有标记任何已投递岗位"
  description="在岗位卡片里点击「标记投递」后，这里会形成你的投递记录。"
  action={<Link href="/today" className="btn-ink">返回今日机会</Link>}
/>
```

Import `Link` from `next/link`.

- [ ] **Step 5: Verify Task 3**

Run:

```bash
node --test tests/ux-hardening-contract.test.js tests/homepage-count-scope.test.js tests/loading-copy.test.js
npm run lint
```

Expected: tests pass; lint has no new errors or warnings beyond any documented pre-existing warning.

- [ ] **Step 6: Commit only Task 3 files**

```bash
git add tests/ux-hardening-contract.test.js app/api/jobs/stats/route.ts components/JobLibraryStat.tsx components/TagInput.tsx components/PreferenceForm.tsx components/ResumeProfilePanel.tsx components/Navbar.tsx app/applied/page.tsx
git commit -m "fix(ux): cache stats and improve accessible actions"
```

### Task 4: Upgrade vulnerable dependencies and add the DB operations gate

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `.env.example`
- Create: `docs/runbooks/jobs-db-production-safety.md`
- Modify: `README.md`
- Modify: `app/api/job-actions/[jobId]/route.ts` (Next 15 async route context compatibility only)
- Modify: `app/api/jobs/[jobId]/liveness/route.ts` (Next 15 async route context compatibility only)
- Modify: `app/api/job-actions/[jobId]/view/route.ts` (Next 15 async route context compatibility only)
- Create: `tests/next15-route-context.test.js`

- [ ] **Step 1: Capture the failing security gate**

Run:

```bash
npm audit --omit=dev --audit-level=high --json
```

Expected before implementation: non-zero exit with at least one high-severity direct `next` vulnerability. Save the package/severity counts in the task report; do not commit generated audit output.

- [ ] **Step 2: Upgrade the supported Next.js line**

Run:

```bash
npm install next@15.5.18 eslint-config-next@15.5.18
```

执行时最新 advisory 将安全修复下限推进到 `15.5.18`，因此在不跨越 Next 15 支持线、也不升级 React 19 的前提下，将原计划版本更新为 `15.5.18`。

Keep React 18 unless the package manager or build proves React 19 is required. Do not use `npm audit fix --force`.

- [ ] **Step 3: Add explicit environment and production-safety documentation**

Add `JOBS_DATABASE_URL` to `.env.example` using a non-secret placeholder. Create the runbook with these mandatory sections and exact acceptance states:

- TLS: production has a trusted CA; `rejectUnauthorized:false` is listed as an unresolved blocker until a coordinated code+secret rollout.
- Backup: daily encrypted snapshot, retention period, owner and evidence URL.
- Recovery: PITR capability, RPO, RTO, quarterly restore drill and latest drill date.
- Capacity: database connection ceiling, application pool size, alert thresholds and escalation owner.
- Rollout order: provision CA/secret first, deploy verified TLS code second, remove insecure compatibility flag last.

Update README migration count from 174 to 183 and link the new runbook from the production/deployment section.

- [ ] **Step 4: Verify dependency and documentation gates**

Run:

```bash
npm audit --omit=dev --audit-level=high --json
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
bash scripts/check-migrations.sh
npm run lint
env NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=dummy npm run build
git diff --check
```

Expected: audit exits zero with zero high/critical vulnerabilities; Node and Python tests pass; migrations, lint, build and diff check pass. Raw audit still reports two accepted temporary moderate findings from Next's bundled PostCSS 8.4.31. Current repository inspection found no runtime path that stringifies an untrusted CSS AST into `<style>`; review this risk weekly and on every dependency upgrade. Do not run `npm audit fix --force`, whose suggested resolution can incorrectly downgrade the supported dependency line. If Next 15 introduces a compatibility failure, fix only the demonstrated failure and add a regression test before production code changes.

- [ ] **Step 5: Commit Task 4 files**

```bash
git add package.json package-lock.json .env.example README.md docs/runbooks/jobs-db-production-safety.md docs/superpowers/plans/2026-07-10-product-engineering-hardening.md tests/next15-route-context.test.js tests/scoring.test.js lib/scoring.ts app/api/job-actions/[jobId]/route.ts app/api/job-actions/[jobId]/view/route.ts app/api/jobs/[jobId]/liveness/route.ts
git commit -m "chore(security): upgrade Next and document production DB gates"
```

### Task 5: Final integration verification

**Files:**
- Verify only; do not add unrelated changes.

- [ ] **Step 1: Review the complete diff against the design**

Run:

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
git status --short
```

Expected: only design/plan, four implementation tasks and existing `artifacts/` screenshots are present. No secrets, generated build output or unrelated refactors.

- [ ] **Step 2: Run the complete verification bundle again**

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
bash scripts/check-migrations.sh
npm run lint
env NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=dummy npm run build
npm audit --omit=dev --audit-level=high --json
git diff --check origin/main...HEAD
```

Expected: every command exits 0, with no high/critical vulnerability and no new lint warning.
