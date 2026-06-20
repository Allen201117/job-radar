# Admin Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight admin-only `/admin/health` page that reports real seven-day operational health across the jobs PostgreSQL database and Supabase.

**Architecture:** Add one aggregate reader to `lib/jobs-store`, one service-role-only Supabase RPC, and a small server-side normalization module. The page authenticates before starting parallel cross-database reads and renders each database section independently.

**Tech Stack:** Next.js 14 App Router, React server components, TypeScript, node:test, PostgreSQL, Supabase/PostgREST.

---

### Task 1: Define health metric normalization

**Files:**
- Create: `lib/admin-health.ts`
- Create: `tests/admin-health.test.js`

- [x] Write tests for percentage formatting, duration formatting, crawl-source rows, discovery mode summaries, and insight dimensions.
- [x] Run `node --test tests/admin-health.test.js` and verify failure because the module does not exist.
- [x] Implement the minimal pure normalization helpers.
- [x] Run `node --test tests/admin-health.test.js` and verify all tests pass.

### Task 2: Add lightweight cross-database aggregate readers

**Files:**
- Modify: `lib/jobs-store/read.ts`
- Create: `supabase/migrations/158_admin_health_snapshot.sql`
- Modify: `tests/admin-health.test.js`

- [x] Add source-contract tests that require `count_valid_active_jobs()` and reject full-row health reads.
- [x] Run the test and verify it fails.
- [x] Add one conditional aggregate SQL query for jobs health.
- [x] Add a `service_role`-only `admin_health_snapshot(interval)` RPC that aggregates crawl, discovery, and insight metrics in PostgreSQL.
- [x] Reuse the existing crawl/discovery/insight indexes; do not add duplicate write overhead.
- [x] Re-run the focused test.

### Task 3: Build the protected page and loading boundary

**Files:**
- Create: `app/admin/health/page.tsx`
- Create: `app/admin/health/loading.tsx`
- Modify: `tests/admin-health.test.js`

- [x] Add source-contract tests for `isAdmin()`, redirect behavior, parallel loading, placeholders, and skeleton reuse.
- [x] Run the test and verify it fails.
- [x] Implement the server-rendered warm-paper dashboard with independent error states.
- [x] Implement the matching loading skeleton.
- [x] Re-run the focused test.

### Task 4: Verify the complete change

**Files:**
- Review all files above.

- [x] Run `node --test tests/admin-health.test.js`.
- [x] Run `node --test tests/*.test.js`.
- [x] Run `npm run build`.
- [x] Run `git diff --check`.
- [x] Inspect `git diff --stat` and confirm no unrelated files were modified.
