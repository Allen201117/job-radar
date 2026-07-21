# 校招洞察 P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已上线的校招专区补上"该什么时候投"的往年时间/批次洞察——新建结构化观测表，校招卡上显一行"据往年·提前批约7月·正式批8-9月·现处黄金期"、抽屉里显时间轴，admin 可网页录入核验扩覆盖。

**Architecture:** 新表 `recruitment_cycle_observations`（Supabase 洞察层）当校招时间的**唯一结构化真相源**（immutable 事实字段 + 版本化 + 绑届别 + 留证据）。纯函数 `lib/recruitment-cycle.ts` 把观测算成卡片一行摘要（现处哪批/黄金期/尾声）。校招页 SSR 读观测 merge 到卡片；`/api/insights` 扩 `recruitment_cycles` 喂抽屉时间轴；`/api/insights/admin/cycles` + admin 页管理面做录入核验。老的 timing 文字洞察原样不动、不反向同步。

**Tech Stack:** Next.js 15 App Router + React 18 + TypeScript；Supabase Postgres + RLS（migrate.yml CI 自动 apply）；node --test（`tests/_load-ts.js` 转译 TS 纯函数）。

## Global Constraints

- **红线：宁缺不编 + 据往年必绑届别**。观测只在 `verify_status='verified'` 且未过期时展示；卡片无 verified 观测→不显示、不占位。`grad_class` 必填（"2027届"），绝不用泛"往年"。
- **事实字段 immutable**：`grad_class/season/batch/event/time_expr_type/value_text/month_*/date_*/evidence_*` 一经写入不 UPDATE；改错=新增一条 + `superseded_by` 指旧的。仅 `verify_status/valid_until/superseded_by/updated_at` 可改。写路径（admin API）强制这条。
- **P2 只做批次时机时间事实**，不做"提前批 vs 正式批 难度/流程/HC 差异"经验洞察（推 P3）。
- **新表是唯一源，不双写**：卡片+抽屉时间轴直接读新表；老 `insight_items` timing 散文原样不动、不反向同步。
- **季节感知不污染事实层**：卡片时间线行与 P1 实时窗口徽章视觉/语义分离。
- **迁移规约**：下一个前缀 = `182`（现有最高 `181`）。seed 类文件名带 `_seed_`。migrate.yml push main 自动 apply，勿手动跑 Supabase SQL。大表回填/建索引前加 `set local statement_timeout`。
- **服务端写库用 `createServiceClient()`**（`@/lib/supabaseService`，绕 RLS，绝不暴露浏览器）。admin 路由用 `requireAdmin()`（`@/lib/apiAuth`）。
- **TS 纯函数测试约束**：`lib/recruitment-cycle.ts` 与 `lib/recruitment-cycle-validate.ts` 只能 import 类型（被 transpile 擦除）或相对 `.ts`；**不能有 `@/lib/...` 别名的运行时 import**（`tests/_load-ts.js` 只解析相对 `.ts` 与 node_modules）。
- **提交前回归**：`node --test tests/*.test.js && npm run build`（改到 crawler 才跑 python）。commit 用显式路径，不吞无关改动；**不 push**（等用户指令）。

---

## 文件结构（先锁定边界）

| 文件 | 职责 | 任务 |
|---|---|---|
| `supabase/migrations/182_recruitment_cycle_observations.sql` | 建表 + RLS + 索引 | T1 |
| `supabase/migrations/183_seed_recruitment_cycles.sql` | 10 家头部种子（结构化 INSERT） | T2 |
| `lib/recruitment-cycle.ts` | 纯函数：类型 `RecruitmentObservation`/`CampusTimeline` + `campusTimelineSummary` | T3 |
| `tests/recruitment-cycle.test.js` | T3/T6 纯函数单测 | T3, T6 |
| `lib/recruitment-cycle-store.ts` | 服务端读：`getRecruitmentCyclesForCompanies(list)`（Supabase + insight-match） | T4 |
| `app/campus/page.tsx` | SSR 读观测 merge 到卡片 | T4 |
| `app/campus/campus-client.tsx` | 卡片徽章下渲染时间线一行 | T5 |
| `app/api/insights/route.ts` | GET 响应扩 `recruitment_cycles` | T5 |
| `lib/insight-client.ts` | `CompanyInsightResponse` 加 `recruitment_cycles` 字段 | T5 |
| `components/CompanyInsightDrawer.tsx` | 抽屉加 `RecruitmentTimeline` 分区 | T5 |
| `lib/recruitment-cycle-validate.ts` | 纯函数：admin 录入校验 + 枚举门 | T6 |
| `app/api/insights/admin/cycles/route.ts` | admin GET/POST/PATCH（service-role，过校验门，强制 immutable） | T7 |
| `components/InsightsAdminClient.tsx` | 加"招聘周期"管理面（列/增/核验） | T8 |

**落地顺序**：Phase 1（T1–T2 数据地基）→ Phase 2（T3–T5 展示核心，用户可见）→ Phase 3（T6–T8 admin 录入核验，扩覆盖）→ Phase 4（LLM 草稿，本计划只描述不实现）。

---

## Phase 1 — 数据地基

### Task 1: 建表迁移 `recruitment_cycle_observations`

**Files:**
- Create: `supabase/migrations/182_recruitment_cycle_observations.sql`

**Interfaces:**
- Produces: 表 `recruitment_cycle_observations`（字段见下），供 T2 seed、T4 读层、T7 admin API 消费。

DDL 是幂等 apply（migrate.yml）；无单元测试，交付=SQL 文件 + `git diff --check` 干净。样式严格照 `013_career_insights.sql`（authenticated 过滤读 + admin 写、CHECK 枚举、多列索引）。

- [ ] **Step 1: 写迁移文件**

```sql
-- ============================================================
-- 校招洞察 P2：招聘周期观测表（结构化事实底座，可版本化、绑届别、留证据）
-- 唯一结构化真相源；insight_items timing 散文洞察不受影响、不反向同步。
-- 不变量：事实字段 immutable（改错=新增 + superseded_by），仅 verify_status/
--   valid_until/superseded_by/updated_at 可改，由 admin API 写路径强制。
-- ============================================================

create table recruitment_cycle_observations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references company_profiles(id) on delete cascade,
  grad_class text not null,                         -- 毕业届别，如 "2027届"（据往年必绑此）
  season text not null check (season in ('秋招','春招')),
  batch text not null check (batch in ('提前批','正式批','补录','实习转正')),
  event text not null check (event in ('开放','截止','黄金期','结束')),
  time_expr_type text not null check (time_expr_type in ('精确日期','日期范围','月','历史规律')),
  value_text text not null,                         -- 展示串："约7月" / "8-9月" / "全年滚动"
  month_start smallint check (month_start between 1 and 12),
  month_end smallint check (month_end between 1 and 12),
  date_start date,                                  -- 仅 time_expr_type='精确日期'（P3）
  date_end date,
  confidence text not null default 'medium' check (confidence in ('high','medium','low')),
  evidence_url text,
  evidence_excerpt text,                            -- 证据短摘要，禁整段原文
  evidence_fetched_at timestamptz,
  source_kind text,                                 -- official_site/official_notice/manual_curation/llm_draft/public_aggregate
  verify_status text not null default 'draft' check (verify_status in ('draft','verified','rejected')),
  valid_until date,
  superseded_by uuid references recruitment_cycle_observations(id),
  created_by text,                                  -- admin email / 'seed' / 'llm'
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_rco_company_verify_valid
  on recruitment_cycle_observations(company_id, verify_status, valid_until);
create index idx_rco_grad_class on recruitment_cycle_observations(grad_class);

alter table recruitment_cycle_observations enable row level security;

-- 读：仅 verified 且未过期（宁缺不编）
create policy "Authenticated users can read verified cycles"
  on recruitment_cycle_observations for select
  using (
    auth.role() = 'authenticated'
    and verify_status = 'verified'
    and (valid_until is null or valid_until >= current_date)
  );

-- 写：仅 admin（service_role 绕 RLS，另走）
create policy "Admins can write cycles"
  on recruitment_cycle_observations for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
```

- [ ] **Step 2: 校验 diff 干净**

Run: `git -C /Users/bytedance/Desktop/求职雷达/.claude/worktrees/campus-insights-p2-design-69d8c0 diff --check`
Expected: 无输出（无空白错误）

- [ ] **Step 3: 确认前缀未占用**

Run: `ls supabase/migrations/ | grep '^182' || echo "OK 未占用"`
Expected: 打印 `OK 未占用`（仅本文件在，或空）

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/182_recruitment_cycle_observations.sql
git commit -m "feat(campus-p2): 建 recruitment_cycle_observations 表 + RLS + 索引"
```

---

### Task 2: 10 家头部种子（结构化 INSERT）

**Files:**
- Create: `supabase/migrations/183_seed_recruitment_cycles.sql`

**Interfaces:**
- Consumes: T1 的表 + `company_profiles`（014 已建这 10 家）。
- Produces: ~22 条 verified 观测，供 T3/T4/T5 展示与测试对照。

把 `014` 的 phase 串**手工结构化**成显式 INSERT（不在 SQL 里解析字符串，只 10 家、更可靠）。届别绑 2027届（今为 2026-07，当前活跃秋招面向 2027 届毕业生），`time_expr_type='历史规律'`、`source_kind='official_site'`、`verify_status='verified'`、`valid_until='2027-06-30'`。用 plpgsql 助手按公司名查 company_id，镜像 014 的 `_seed_insight` 风格。

- [ ] **Step 1: 写 seed 迁移文件**

```sql
-- ============================================================
-- 校招洞察 P2 种子：10 家头部往年招聘周期（据往年规律，官方招聘域名锚定）
-- 均 verify_status='verified'、绑 2027届、valid_until=2027-06-30（下季前失效）。
-- 重复执行注意：本文件为追加插入，仅在全新库或先删同 grad_class 行后重跑。
-- ============================================================

create or replace function _seed_cycle(
  p_company text, p_season text, p_batch text, p_event text,
  p_value_text text, p_month_start smallint, p_month_end smallint,
  p_evidence_url text
) returns void language plpgsql as $$
declare v_company_id uuid;
begin
  select id into v_company_id from company_profiles where company = p_company;
  if v_company_id is null then
    raise notice '跳过（company_profiles 无此公司）: %', p_company;
    return;
  end if;
  insert into recruitment_cycle_observations (
    company_id, grad_class, season, batch, event, time_expr_type,
    value_text, month_start, month_end, confidence, evidence_url,
    source_kind, verify_status, valid_until, created_by
  ) values (
    v_company_id, '2027届', p_season, p_batch, p_event, '历史规律',
    p_value_text, p_month_start, p_month_end, 'high', p_evidence_url,
    'official_site', 'verified', date '2027-06-30', 'seed'
  );
end;
$$;

-- 字节：秋招提前批约7月 / 正式批8-9月 / 春招3-4月
select _seed_cycle('字节跳动','秋招','提前批','开放','约7月',7::smallint,7::smallint,'https://jobs.bytedance.com/campus');
select _seed_cycle('字节跳动','秋招','正式批','开放','8-9月',8::smallint,9::smallint,'https://jobs.bytedance.com/campus');
select _seed_cycle('字节跳动','春招','正式批','开放','3-4月',3::smallint,4::smallint,'https://jobs.bytedance.com/campus');
-- 腾讯：秋招约8-10月（设提前批）
select _seed_cycle('腾讯','秋招','提前批','开放','靠前（约7月）',7::smallint,7::smallint,'https://join.qq.com/');
select _seed_cycle('腾讯','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://join.qq.com/');
-- 阿里：秋招8-10月 / 春招2-4月
select _seed_cycle('阿里巴巴','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://talent.alibaba.com/');
select _seed_cycle('阿里巴巴','春招','正式批','开放','2-4月',2::smallint,4::smallint,'https://talent.alibaba.com/');
-- 美团：秋招8-10月（设提前批）
select _seed_cycle('美团','秋招','提前批','开放','靠前',7::smallint,7::smallint,'https://zhaopin.meituan.com/');
select _seed_cycle('美团','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.meituan.com/');
-- 拼多多：秋招8-10月
select _seed_cycle('拼多多','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://careers.pinduoduo.com/');
-- 京东：秋招8-10月 / 春招补录
select _seed_cycle('京东','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.jd.com/');
select _seed_cycle('京东','春招','补录','开放','3-4月',3::smallint,4::smallint,'https://zhaopin.jd.com/');
-- 百度：秋招8-10月 / 春招2-4月
select _seed_cycle('百度','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://talent.baidu.com/');
select _seed_cycle('百度','春招','正式批','开放','2-4月',2::smallint,4::smallint,'https://talent.baidu.com/');
-- 快手：秋招8-10月
select _seed_cycle('快手','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.kuaishou.cn/');
-- 小红书：秋招8-10月
select _seed_cycle('小红书','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://job.xiaohongshu.com/');
-- 华为：秋招8-11月（设实习转正）
select _seed_cycle('华为','秋招','正式批','开放','8-11月',8::smallint,11::smallint,'https://career.huawei.com/');
select _seed_cycle('华为','秋招','实习转正','开放','贯穿秋招',8::smallint,11::smallint,'https://career.huawei.com/');

drop function _seed_cycle(text, text, text, text, text, smallint, smallint, text);
```

> 注：微软中国（财年节奏）与苹果中国（全年滚动）不属"校招批次时机"，本 seed 不纳入——它们的 timing 散文洞察仍在 `insight_items` 展示，符合"新表只承载结构化校招周期"的边界。

- [ ] **Step 2: 校验 diff 干净**

Run: `git diff --check`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/183_seed_recruitment_cycles.sql
git commit -m "feat(campus-p2): 10 家头部往年招聘周期种子（结构化 verified）"
```

---

## Phase 2 — 展示核心

### Task 3: 纯函数 `campusTimelineSummary`

**Files:**
- Create: `lib/recruitment-cycle.ts`
- Test: `tests/recruitment-cycle.test.js`

**Interfaces:**
- Produces:
  - `interface RecruitmentObservation`（DB 行的 TS 视图，见 Step 3 代码）
  - `interface CampusTimeline { gradClass: string; season: "秋招"|"春招"; batchBits: string[]; phaseLabel: string | null }`
  - `function campusTimelineSummary(observations: RecruitmentObservation[], now?: Date): CampusTimeline | null`
- 被 T4（page 组卡）、T5（drawer）import（app 端走 `@/lib/recruitment-cycle`），被本测试直接 loadTs。

**规则（无歧义）**：
1. 过滤可展示：`verify_status` 缺省或 `='verified'`；`valid_until` 缺省或 `>= now 的 YYYY-MM-DD`；`month_start != null` 且 `event ∈ {开放,黄金期}`。
2. 无可展示 → 返回 `null`。
3. 选季：`m = now月`；`m∈[5,12]→秋招`，否则 `春招`；选中季无观测则回退另一季。
4. 季内按 `BATCH_ORDER = {提前批:0,正式批:1,补录:2,实习转正:3}` 排序、按 batch 去重（保留 month_start 最小的那条）。
5. `batchBits[i] = `${batch}${value_text}``（如 `提前批约7月`、`正式批8-9月`）。
6. `phaseLabel`：季内找窗口 `month_start<=m<=month_end`（若 `month_start>month_end` 视为跨年环绕：`m>=start||m<=end`）→ 命中且 `event==='黄金期'`→`"现处黄金期"`，否则→``现处${batch}``；无命中且 `m > 季内最大 month_end` 且 `m - 最大month_end <= 3`→`"往年这时多已近尾声"`；否则 `null`。
7. `gradClass` = 选中季首条的 `grad_class`；`season` = 选中季。

- [ ] **Step 1: 写失败测试**

```js
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
const { campusTimelineSummary } = loadTs(
  path.join(__dirname, "..", "lib", "recruitment-cycle.ts"),
);

// 字节秋招提前批7月/正式批8-9月 + 春招3-4月
const bytedance = [
  { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", value_text: "约7月", month_start: 7, month_end: 7, verify_status: "verified" },
  { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放", value_text: "8-9月", month_start: 8, month_end: 9, verify_status: "verified" },
  { grad_class: "2027届", season: "春招", batch: "正式批", event: "开放", value_text: "3-4月", month_start: 3, month_end: 4, verify_status: "verified" },
];

test("7月：秋招·现处提前批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-07-15T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.gradClass, "2027届");
  assert.deepEqual(r.batchBits, ["提前批约7月", "正式批8-9月"]);
  assert.equal(r.phaseLabel, "现处提前批");
});

test("8月：现处正式批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-08-20T00:00:00"));
  assert.equal(r.phaseLabel, "现处正式批");
});

test("12月：秋招已近尾声", () => {
  const r = campusTimelineSummary(bytedance, new Date("2026-12-01T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, "往年这时多已近尾声");
});

test("3月：切到春招·现处正式批", () => {
  const r = campusTimelineSummary(bytedance, new Date("2027-03-10T00:00:00"));
  assert.equal(r.season, "春招");
  assert.deepEqual(r.batchBits, ["正式批3-4月"]);
  assert.equal(r.phaseLabel, "现处正式批");
});

test("2月且只有秋招观测：回退秋招·phaseLabel null", () => {
  const onlyFall = bytedance.filter((o) => o.season === "秋招");
  const r = campusTimelineSummary(onlyFall, new Date("2027-02-10T00:00:00"));
  assert.equal(r.season, "秋招");
  assert.equal(r.phaseLabel, null);
});

test("黄金期事件命中：现处黄金期", () => {
  const withGolden = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "黄金期", value_text: "9月", month_start: 9, month_end: 9, verify_status: "verified" },
  ];
  const r = campusTimelineSummary(withGolden, new Date("2026-09-10T00:00:00"));
  assert.equal(r.phaseLabel, "现处黄金期");
});

test("过期观测被过滤 → null", () => {
  const expired = bytedance.map((o) => ({ ...o, valid_until: "2025-06-30" }));
  const r = campusTimelineSummary(expired, new Date("2026-07-15T00:00:00"));
  assert.equal(r, null);
});

test("未 verified 被过滤 → null", () => {
  const draft = bytedance.map((o) => ({ ...o, verify_status: "draft" }));
  assert.equal(campusTimelineSummary(draft, new Date("2026-07-15T00:00:00")), null);
});

test("空数组 → null", () => {
  assert.equal(campusTimelineSummary([], new Date("2026-07-15T00:00:00")), null);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/recruitment-cycle.test.js`
Expected: FAIL（`campusTimelineSummary is not a function` / 模块不存在）

- [ ] **Step 3: 写实现**

```ts
// ============================================================
// 校招洞察 P2 — 招聘周期纯函数（无 LLM/网络/DB，node --test 可测）
// 只 import 类型（被 transpile 擦除）；禁 @/ 别名运行时 import（见 Global Constraints）。
// ============================================================

export type CycleSeason = "秋招" | "春招";
export type CycleBatch = "提前批" | "正式批" | "补录" | "实习转正";
export type CycleEvent = "开放" | "截止" | "黄金期" | "结束";

export interface RecruitmentObservation {
  id?: string;
  grad_class: string;
  season: CycleSeason;
  batch: CycleBatch;
  event: CycleEvent;
  time_expr_type?: string;
  value_text: string;
  month_start: number | null;
  month_end: number | null;
  date_start?: string | null;
  date_end?: string | null;
  confidence?: string | null;
  evidence_url?: string | null;
  evidence_excerpt?: string | null;
  source_kind?: string | null;
  verify_status?: string | null;
  valid_until?: string | null;
}

export interface CampusTimeline {
  gradClass: string;
  season: CycleSeason;
  batchBits: string[];
  phaseLabel: string | null;
}

const BATCH_ORDER: Record<CycleBatch, number> = {
  提前批: 0,
  正式批: 1,
  补录: 2,
  实习转正: 3,
};

function ymd(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

// 是否落在窗口内（支持 month_start>month_end 的跨年环绕）
function inWindow(m: number, start: number, end: number): boolean {
  return start <= end ? m >= start && m <= end : m >= start || m <= end;
}

export function campusTimelineSummary(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): CampusTimeline | null {
  const today = ymd(now);
  const usable = (observations || []).filter(
    (o) =>
      o &&
      o.month_start != null &&
      (o.event === "开放" || o.event === "黄金期") &&
      (!o.verify_status || o.verify_status === "verified") &&
      (!o.valid_until || o.valid_until >= today),
  );
  if (usable.length === 0) return null;

  const m = now.getMonth() + 1;
  const preferred: CycleSeason = m >= 5 && m <= 12 ? "秋招" : "春招";
  const inPreferred = usable.filter((o) => o.season === preferred);
  const picked = inPreferred.length > 0 ? inPreferred : usable;
  const season = picked[0].season;
  const seasonObs = usable.filter((o) => o.season === season);

  // 按批次去重（保留 month_start 最小），再按批次序排
  const byBatch = new Map<CycleBatch, RecruitmentObservation>();
  for (const o of seasonObs) {
    const cur = byBatch.get(o.batch);
    if (!cur || (o.month_start ?? 99) < (cur.month_start ?? 99)) byBatch.set(o.batch, o);
  }
  const batches = Array.from(byBatch.values()).sort(
    (a, b) => BATCH_ORDER[a.batch] - BATCH_ORDER[b.batch],
  );

  const batchBits = batches.map((o) => `${o.batch}${o.value_text}`);

  // 当前阶段
  let phaseLabel: string | null = null;
  const hit = batches.find(
    (o) => o.month_start != null && o.month_end != null && inWindow(m, o.month_start, o.month_end),
  );
  if (hit) {
    phaseLabel = hit.event === "黄金期" ? "现处黄金期" : `现处${hit.batch}`;
  } else {
    const maxEnd = Math.max(...batches.map((o) => o.month_end ?? o.month_start ?? 0));
    if (m > maxEnd && m - maxEnd <= 3) phaseLabel = "往年这时多已近尾声";
  }

  return { gradClass: batches[0].grad_class, season, batchBits, phaseLabel };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/recruitment-cycle.test.js`
Expected: PASS（9 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/recruitment-cycle.ts tests/recruitment-cycle.test.js
git commit -m "feat(campus-p2): campusTimelineSummary 纯函数 + 单测"
```

---

### Task 4: 读层 + 校招页 SSR 挂时间线数据

**Files:**
- Create: `lib/recruitment-cycle-store.ts`
- Modify: `app/campus/page.tsx`（imports 段 + `Promise.all`（现 lines 46–49）+ 组卡 `.map`（现 lines 51–67）+ 传 props（现 line 74））

**Interfaces:**
- Consumes: T3 的 `RecruitmentObservation`；`createServiceClient`（`@/lib/supabaseService`）；`companyMatches`（`@/lib/insight-match`）；`getCampusZone`（已在 page 用）。
- Produces: `getRecruitmentCyclesForCompanies(list: Array<{name:string;pattern:string}>): Promise<Map<string, RecruitmentObservation[]>>`（key=pattern）。page 把 `timeline` 摘要挂到每张卡：`card.timeline: CampusTimeline | null`。

读层无单元测试（DB 读，镜像 `lib/campus-sources.ts` 无单测的既有约定）。

- [ ] **Step 1: 写读层**

```ts
import { createServiceClient } from "@/lib/supabaseService";
import { companyMatches } from "@/lib/insight-match";
import type { RecruitmentObservation } from "@/lib/recruitment-cycle";

// 读全部 verified 且未过期的招聘周期观测，按公司归一匹配到必投清单公司（key=pattern）。
export async function getRecruitmentCyclesForCompanies(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, RecruitmentObservation[]>> {
  const out = new Map<string, RecruitmentObservation[]>();
  const service = createServiceClient();
  const today = new Date().toISOString().slice(0, 10);
  const { data, error } = await service
    .from("recruitment_cycle_observations")
    .select(
      "grad_class, season, batch, event, time_expr_type, value_text, month_start, month_end, confidence, evidence_url, evidence_excerpt, verify_status, valid_until, company_profiles!inner(company, aliases)",
    )
    .eq("verify_status", "verified")
    .or(`valid_until.is.null,valid_until.gte.${today}`);
  if (error) {
    console.error("[campus-cycles] 读取失败", error.message);
    return out;
  }
  for (const c of list) {
    const matched = (data || []).filter((row: any) =>
      companyMatches(
        { company: row.company_profiles?.company || "", aliases: row.company_profiles?.aliases || [] },
        c.name,
      ),
    );
    if (matched.length > 0) out.set(c.pattern, matched as RecruitmentObservation[]);
  }
  return out;
}
```

- [ ] **Step 2: page.tsx 加 imports**

在 `app/campus/page.tsx` imports 段（现 line 8 附近 `getCampusZone` import 之后）加：

```ts
import { getRecruitmentCyclesForCompanies } from "@/lib/recruitment-cycle-store";
import { campusTimelineSummary } from "@/lib/recruitment-cycle";
```

- [ ] **Step 3: page.tsx 并入 Promise.all**

把现有（lines 46–49）：

```tsx
  const [zone, sourceCov] = await Promise.all([
    getCampusZone(companies),
    getCampusSourceCoverage(companies),
  ]);
```

改为：

```tsx
  const [zone, sourceCov, cyclesByPattern] = await Promise.all([
    getCampusZone(companies),
    getCampusSourceCoverage(companies),
    getRecruitmentCyclesForCompanies(companies),
  ]);
```

- [ ] **Step 4: page.tsx 组卡时算 timeline**

在组卡 `.map`（现 lines 51–67）里，`return { ...z, window, nearestDeadlineMs }` 改为带上 timeline：

```tsx
    const obs = cyclesByPattern.get(z.pattern) || [];
    const timeline = obs.length > 0 ? campusTimelineSummary(obs) : null;
    return { ...z, window, nearestDeadlineMs, timeline };
```

（`timeline` 字段随 `cards` 一起进 `CampusClient`，`CampusCardData` 已经是 `CampusCompanyRow & {...}` 的宽松展开，T5 在 client 端补类型。）

- [ ] **Step 5: 编译确认无类型错**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "campus|recruitment" || echo "OK 无相关类型错"`
Expected: `OK 无相关类型错`（page 端 timeline 是新增可选字段，client 端 T5 补类型）

- [ ] **Step 6: Commit**

```bash
git add lib/recruitment-cycle-store.ts app/campus/page.tsx
git commit -m "feat(campus-p2): 读层 getRecruitmentCyclesForCompanies + 校招页组卡挂 timeline"
```

---

### Task 5: 卡片时间线行 + 抽屉时间轴 + `/api/insights` 扩字段

**Files:**
- Modify: `app/campus/campus-client.tsx`（`CampusCardData` 类型 + 卡片徽章下插一行，现 line 362↔363 之间）
- Modify: `app/api/insights/route.ts`（GET 响应对象，现 lines 153–162 加 `recruitment_cycles`）
- Modify: `lib/insight-client.ts`（`CompanyInsightResponse` 加字段）
- Modify: `components/CompanyInsightDrawer.tsx`（加 `RecruitmentTimeline` 分区）

**Interfaces:**
- Consumes: T3 `CampusTimeline`/`RecruitmentObservation`、`campusTimelineSummary`；T4 挂在 card 上的 `timeline`。
- Produces: 卡片可见的时间线一行；`/api/insights` 响应 `recruitment_cycles: RecruitmentObservation[]`；抽屉时间轴分区。

纯 UI/接口改动，无单元测试；验证走 `npm run build` + 浏览器走查。

- [ ] **Step 1: campus-client.tsx 补卡片类型**

`CampusCardData` 类型（现 lines 24–27）加 `timeline`：

```tsx
import type { CampusTimeline } from "@/lib/recruitment-cycle";
// ...
export type CampusCardData = CampusCompanyRow & {
  window: WindowState;
  nearestDeadlineMs: number | null;
  timeline: CampusTimeline | null;
};
```

- [ ] **Step 2: campus-client.tsx 插时间线行**

在卡片头部 flex 行 `</div>`（现 line 362）与计数 `<p>`（现 line 363）之间插入（`data-*` 便于走查）：

```tsx
                  {card.timeline && (
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
                      <span className="inline-flex items-center gap-1 rounded-md border border-[#b7d2ee] bg-[#dceafa] px-1.5 py-0.5 font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
                        据往年
                      </span>
                      <span>{card.timeline.gradClass}</span>
                      {card.timeline.batchBits.map((bit) => (
                        <span key={bit}>· {bit}</span>
                      ))}
                      {card.timeline.phaseLabel && (
                        <span className="font-medium text-[#8a6312] dark:text-[#e0b15a]">
                          · {card.timeline.phaseLabel}
                        </span>
                      )}
                    </div>
                  )}
```

> 视觉：浅色小字（`text-[#8a8275]`），"据往年"用蓝色小 chip（与 timing 维度同蓝系）与上方实时窗口徽章分离；phaseLabel 用琥珀强调。这与 D2「紧凑一行·事实优先」一致。

- [ ] **Step 3: lib/insight-client.ts 加响应字段**

`CompanyInsightResponse`（现 lines 15–23）加：

```ts
import type { RecruitmentObservation } from "./recruitment-cycle";
// ... interface 内加：
  recruitment_cycles: RecruitmentObservation[];
```

并在 `fetchCompanyInsights` 归一化默认值处补 `recruitment_cycles: data.recruitment_cycles || []`（合并 EMPTY 默认对象时带上该键，防 undefined）。

- [ ] **Step 4: /api/insights 查观测并入响应**

在 `app/api/insights/route.ts` GET 内，`enrichNow`/`firstParty` 解析处（现 ~lines 144–151）之后、组响应对象之前，加：

```ts
  let recruitmentCycles: any[] = [];
  if (profile) {
    const today = new Date().toISOString().slice(0, 10);
    const { data: cycleRows } = await createServiceClient()
      .from("recruitment_cycle_observations")
      .select(
        "id, grad_class, season, batch, event, time_expr_type, value_text, month_start, month_end, confidence, evidence_url, evidence_excerpt, valid_until",
      )
      .eq("company_id", profile.id)
      .eq("verify_status", "verified")
      .or(`valid_until.is.null,valid_until.gte.${today}`)
      .order("season")
      .order("month_start");
    recruitmentCycles = cycleRows || [];
  }
```

（若文件未 import `createServiceClient`，从 `@/lib/supabaseService` 补 import。）
再把响应对象（现 lines 153–162）`first_party: firstParty,` 之后加一行：

```ts
    recruitment_cycles: recruitmentCycles,
```

- [ ] **Step 5: CompanyInsightDrawer.tsx 加时间轴分区**

在 drawer 文件末尾加组件：

```tsx
import type { RecruitmentObservation } from "@/lib/types";
// 注：RecruitmentObservation 从 @/lib/recruitment-cycle import（若 types 未 re-export）

function RecruitmentTimeline({ cycles }: { cycles: RecruitmentObservation[] }) {
  if (!cycles || cycles.length === 0) return null;
  const bySeason = new Map<string, RecruitmentObservation[]>();
  for (const c of cycles) {
    if (!bySeason.has(c.season)) bySeason.set(c.season, []);
    bySeason.get(c.season)!.push(c);
  }
  const gradClass = cycles[0]?.grad_class || "";
  return (
    <section className="mb-8">
      <header className="mb-3 flex items-center gap-2.5">
        <span className="grid size-8 place-items-center rounded-xl border border-[#b7d2ee] bg-[#dceafa] text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
          <CalendarBlank size={17} weight="bold" />
        </span>
        <h3 className="text-base font-semibold text-[#1a1714] dark:text-[#f3ecdf]">招聘周期</h3>
        <span className="rounded-full border border-[#b7d2ee] bg-[#dceafa] px-2 py-0.5 text-[11px] font-medium text-[#2f6299] dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]">
          据往年 · {gradClass}
        </span>
      </header>
      <div className="space-y-3.5">
        {Array.from(bySeason.entries()).map(([season, rows]) => (
          <div key={season} className="rounded-xl border border-black/[0.06] bg-white/60 p-4 dark:border-white/[0.1] dark:bg-white/[0.05]">
            <p className="mb-2 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">{season}</p>
            <ul className="space-y-1.5">
              {rows.map((r, i) => (
                <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-[#5f594e] dark:text-[#b6ad9d]">
                  <span className="rounded-md bg-black/[0.05] px-1.5 py-0.5 text-[11px] font-medium dark:bg-white/[0.08]">{r.batch}</span>
                  <span>{r.event}</span>
                  <span className="font-medium text-[#1a1714] dark:text-[#f3ecdf]">{r.value_text}</span>
                  {r.evidence_url && (
                    <a href={r.evidence_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-[11px] text-[#2f6299] hover:underline dark:text-[#7fb2e8]">
                      来源 <ArrowSquareOut size={10} weight="bold" />
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
        据往年规律整理（非今年确切日期），今年批次时间以官网当年公告为准。
      </p>
    </section>
  );
}
```

在主体渲染处（`{!loading && data && (<FirstPartySection .../>)}` 之后、`{!loading && totalItems > 0 && (...)}` 之前）插入：

```tsx
          {!loading && data && (
            <RecruitmentTimeline cycles={data.recruitment_cycles || []} />
          )}
```

> 注：`totalItems`（现 lines 174–177）不含 recruitment_cycles，因此「有周期无 insight_items」时 `totalItems===0` 会走 failureMessage 空态并同时渲染时间轴——需把空态判定改为 `totalItems === 0 && (!data?.recruitment_cycles?.length)` 才显示"暂无洞察"。修改现 line 246 的条件为：`{!loading && totalItems === 0 && !(data?.recruitment_cycles?.length) && (...)}`。

- [ ] **Step 6: 全量回归 + build**

Run: `node --test tests/*.test.js && npm run build`
Expected: 单测全绿；build 成功无类型错

- [ ] **Step 7: Commit**

```bash
git add app/campus/campus-client.tsx app/api/insights/route.ts lib/insight-client.ts components/CompanyInsightDrawer.tsx
git commit -m "feat(campus-p2): 卡片时间线行 + 抽屉招聘周期时间轴 + /api/insights 扩 recruitment_cycles"
```

---

## Phase 3 — admin 录入核验（扩塌陷行业覆盖）

### Task 6: 录入校验纯函数

**Files:**
- Create: `lib/recruitment-cycle-validate.ts`
- Test: `tests/recruitment-cycle.test.js`（追加）

**Interfaces:**
- Produces: `validateCycleInput(body: any): { ok: true; fields: Record<string, any> } | { ok: false; error: string }`——校枚举 + 必填 + `time_expr_type='精确日期'` 必须带 `evidence_url`（P3 门）+ month 合法。
- 被 T7 admin API 消费。纯函数、只 import 类型或本地常量（loadTs 可测）。

- [ ] **Step 1: 追加失败测试**

```js
const { validateCycleInput } = loadTs(
  path.join(__dirname, "..", "lib", "recruitment-cycle-validate.ts"),
);

test("合法输入通过", () => {
  const r = validateCycleInput({
    company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批",
    event: "开放", time_expr_type: "月", value_text: "约7月", month_start: 7, month_end: 7,
  });
  assert.equal(r.ok, true);
  assert.equal(r.fields.value_text, "约7月");
});

test("非法季 → 报错", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "夏招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x" });
  assert.equal(r.ok, false);
});

test("缺 grad_class → 报错（据往年必绑届别）", () => {
  const r = validateCycleInput({ company_id: "c1", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x" });
  assert.equal(r.ok, false);
});

test("精确日期缺 evidence_url → 报错（P3 官方源门）", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "精确日期", value_text: "9月1日", date_start: "2026-09-01" });
  assert.equal(r.ok, false);
});

test("month 越界 → 报错", () => {
  const r = validateCycleInput({ company_id: "c1", grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放", time_expr_type: "月", value_text: "x", month_start: 13 });
  assert.equal(r.ok, false);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/recruitment-cycle.test.js`
Expected: FAIL（`validateCycleInput is not a function`）

- [ ] **Step 3: 写实现**

```ts
// admin 录入校验（纯函数）。只做结构/枚举门；immutable 纪律在 API 写路径。
const SEASONS = ["秋招", "春招"];
const BATCHES = ["提前批", "正式批", "补录", "实习转正"];
const EVENTS = ["开放", "截止", "黄金期", "结束"];
const TIME_TYPES = ["精确日期", "日期范围", "月", "历史规律"];
const CONFIDENCES = ["high", "medium", "low"];

function badMonth(v: any): boolean {
  return v != null && (typeof v !== "number" || v < 1 || v > 12);
}

export function validateCycleInput(
  body: any,
): { ok: true; fields: Record<string, any> } | { ok: false; error: string } {
  const b = body || {};
  const companyId = String(b.company_id || "").trim();
  const gradClass = String(b.grad_class || "").trim();
  const valueText = String(b.value_text || "").trim();
  if (!companyId) return { ok: false, error: "missing_company_id" };
  if (!gradClass) return { ok: false, error: "missing_grad_class" };
  if (!valueText) return { ok: false, error: "missing_value_text" };
  if (!SEASONS.includes(b.season)) return { ok: false, error: "invalid_season" };
  if (!BATCHES.includes(b.batch)) return { ok: false, error: "invalid_batch" };
  if (!EVENTS.includes(b.event)) return { ok: false, error: "invalid_event" };
  if (!TIME_TYPES.includes(b.time_expr_type)) return { ok: false, error: "invalid_time_expr_type" };
  if (badMonth(b.month_start) || badMonth(b.month_end)) return { ok: false, error: "invalid_month" };
  if (b.confidence != null && !CONFIDENCES.includes(b.confidence)) return { ok: false, error: "invalid_confidence" };
  // 精确日期只接受可复查官方证据（P3 门）
  if (b.time_expr_type === "精确日期" && !String(b.evidence_url || "").trim()) {
    return { ok: false, error: "exact_date_requires_evidence" };
  }
  return {
    ok: true,
    fields: {
      company_id: companyId,
      grad_class: gradClass,
      season: b.season,
      batch: b.batch,
      event: b.event,
      time_expr_type: b.time_expr_type,
      value_text: valueText,
      month_start: b.month_start ?? null,
      month_end: b.month_end ?? null,
      date_start: b.date_start || null,
      date_end: b.date_end || null,
      confidence: b.confidence || "medium",
      evidence_url: String(b.evidence_url || "").trim() || null,
      evidence_excerpt: String(b.evidence_excerpt || "").trim() || null,
      source_kind: b.source_kind || "manual_curation",
    },
  };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/recruitment-cycle.test.js`
Expected: PASS（14 tests 累计）

- [ ] **Step 5: Commit**

```bash
git add lib/recruitment-cycle-validate.ts tests/recruitment-cycle.test.js
git commit -m "feat(campus-p2): admin 录入校验纯函数 validateCycleInput + 单测"
```

---

### Task 7: admin API 路由 `/api/insights/admin/cycles`

**Files:**
- Create: `app/api/insights/admin/cycles/route.ts`

**Interfaces:**
- Consumes: `requireAdmin`（`@/lib/apiAuth`）、`createServiceClient`（`@/lib/supabaseService`）、`validateCycleInput`（T6）。
- Produces: GET `{ ok, companies, cycles }`；POST 建观测（draft/verified）；PATCH 改 `verify_status`/`valid_until`/`superseded_by`（immutable 纪律：POST 只建、PATCH 只碰这三个可变字段）。被 T8 admin UI 消费。

无单元测试（route，与既有 admin route 一致约定；核心校验逻辑已在 T6 测过）。

- [ ] **Step 1: 写路由**

```ts
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { validateCycleInput } from "@/lib/recruitment-cycle-validate";

export const runtime = "nodejs";

const VERIFY_STATUSES = ["draft", "verified", "rejected"];

export async function GET() {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  const service = createServiceClient();
  const [{ data: companies, error: cErr }, { data: cycles, error: yErr }] = await Promise.all([
    service.from("company_profiles").select("id, company, display_name").order("company"),
    service
      .from("recruitment_cycle_observations")
      .select("*, company_profiles!inner(company, display_name)")
      .order("updated_at", { ascending: false }),
  ]);
  if (cErr || yErr) {
    const message = cErr?.message || yErr?.message || "load_failed";
    console.error("[cycles-admin] 读取失败", message);
    return NextResponse.json({ ok: false, error: message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, companies: companies || [], cycles: cycles || [] });
}

export async function POST(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const v = validateCycleInput(body);
  if (!v.ok) return NextResponse.json({ ok: false, error: v.error }, { status: 422 });

  const verifyStatus = VERIFY_STATUSES.includes(body.verify_status) ? body.verify_status : "draft";
  const service = createServiceClient();
  const { data, error } = await service
    .from("recruitment_cycle_observations")
    .insert({
      ...v.fields,
      verify_status: verifyStatus,
      valid_until: body.valid_until || null,
      superseded_by: body.superseded_by || null,
      created_by: guard.user?.email || "admin",
    })
    .select("id")
    .single();
  if (error) {
    console.error("[cycles-admin] 写入失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, id: data.id });
}

// 只改可变字段（immutable：事实字段一律不接受更新）
export async function PATCH(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;
  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }
  const id = String(body.id || "").trim();
  if (!id) return NextResponse.json({ ok: false, error: "missing_id" }, { status: 400 });
  const patch: Record<string, any> = { updated_at: new Date().toISOString() };
  if (body.verify_status !== undefined) {
    if (!VERIFY_STATUSES.includes(body.verify_status))
      return NextResponse.json({ ok: false, error: "invalid_verify_status" }, { status: 400 });
    patch.verify_status = body.verify_status;
  }
  if (body.valid_until !== undefined) patch.valid_until = body.valid_until || null;
  if (body.superseded_by !== undefined) patch.superseded_by = body.superseded_by || null;

  const service = createServiceClient();
  const { error } = await service
    .from("recruitment_cycle_observations")
    .update(patch)
    .eq("id", id);
  if (error) {
    console.error("[cycles-admin] 更新失败", error.message);
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, id });
}
```

> `guard.user` 若 `requireAdmin` 不返回 user，改用 `"admin"` 常量作 `created_by`（先看 `lib/apiAuth.ts` 的 `requireAdmin` 返回结构，与既有用法对齐）。

- [ ] **Step 2: build 确认路由编译**

Run: `npm run build 2>&1 | grep -E "cycles|error" | head || echo "OK"`
Expected: 无 error；`/api/insights/admin/cycles` 进路由清单

- [ ] **Step 3: Commit**

```bash
git add app/api/insights/admin/cycles/route.ts
git commit -m "feat(campus-p2): admin 招聘周期 API（GET/POST 建/PATCH 核验，immutable 纪律）"
```

---

### Task 8: admin 页"招聘周期"管理面

**Files:**
- Modify: `components/InsightsAdminClient.tsx`（`load()` 加第三个 fetch、新 state、新 `<section>` + `CycleForm` + `CycleRow` 子组件）

**Interfaces:**
- Consumes: T7 的 `/api/insights/admin/cycles`（GET/POST/PATCH）。
- Produces: admin 页可增/核验招聘周期观测的 UI。

镜像既有 `SubmissionRow`/`reviewSubmission`/`ItemForm` 模式（见抽取报告）。无单元测试；验证走 build + 走查。

- [ ] **Step 1: `load()` 加第三个 fetch**

`load()` 的 `Promise.all`（现 lines 177–180）加 `fetch("/api/insights/admin/cycles")`，并 `setCycles(cyclesData.cycles || [])`。顶部加 `const [cycles, setCycles] = useState<any[]>([]);`（跟 `submissions` state 并列，现 line ~165）。

- [ ] **Step 2: 加"招聘周期"section**

在 disputes section 之后、companies worklist 之前（现 line ~610）插入一个 `<section>`，标题 `招聘周期（据往年 · 校招洞察 P2）`，含：
- 一个 `CycleForm`（受控输入：company_id 下拉用 `companies`、grad_class 文本、season/batch/event/time_expr_type 下拉、value_text 文本、month_start/month_end 数字、confidence 下拉、evidence_url 文本、evidence_excerpt 文本、valid_until 日期、verify_status 下拉），提交 `POST /api/insights/admin/cycles` → 成功 `await load()`。复用 `inputCls`（现 lines 149–150）。
- 一列 `CycleRow`（每行显示 company / grad_class / season·batch·event / value_text / verify_status chip + 证据链接），带 `设为 verified` / `设为 rejected` / 改 `valid_until` 按钮 → `PATCH`，`busyId` 门控（复刻 `reviewSubmission` 模式，现 lines 472–489）。

代表性 mutation（照抄 `reviewSubmission` 改端点）：

```tsx
async function setCycleStatus(id: string, verify_status: "verified" | "rejected") {
  setBusyId(id);
  try {
    const res = await fetch("/api/insights/admin/cycles", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, verify_status }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) { alert(data.error || "操作失败"); return; }
    await load();
  } finally {
    setBusyId("");
  }
}
```

`CycleForm` 提交：

```tsx
async function submitCycle(form: Record<string, any>) {
  const res = await fetch("/api/insights/admin/cycles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) { alert(data.error || "提交失败"); return; }
  await load();
}
```

> `CycleForm` 与 `CycleRow` 作为本文件内子组件定义在默认导出下方（同 `ItemForm`/`SubmissionRow` 位置），用 `FormField`（现 lines 1068–1083）拼输入。month_start/month_end 空串要转 `undefined`/`null` 再提交（避免 `""` 撞 `validateCycleInput` 的 `badMonth` 类型判定）。

- [ ] **Step 3: build + 全量回归**

Run: `node --test tests/*.test.js && npm run build`
Expected: 单测全绿；build 成功

- [ ] **Step 4: Commit**

```bash
git add components/InsightsAdminClient.tsx
git commit -m "feat(campus-p2): admin 页招聘周期管理面（录入 + 核验）"
```

---

## Phase 4 — LLM 辅助草稿（本计划只描述，暂不实现）

塌陷行业覆盖的加速项：复用 `crawler/insight_engine.py` 的 timing prompt + `app/api/insights/admin/ai-draft` route，让 LLM 产 `verify_status='draft'` 的招聘周期候选（只提候选、标证据片段），admin 在 Task 8 的管理面人工核对过门才 `verified`。**不进 cron、不按用户触发**（控账单）。失效巡检（`valid_until` 过期→读天然过滤，RLS 已处理，无需额外 sweep 代码）。此 Phase 待核心 Phase 1–3 上线、founder 评估塌陷行业实际需要多少 draft 后再启。

---

## Self-Review（对照 spec 的覆盖检查）

- **D1 塌陷行业优先**：T2 迁 10 家种子当 base；T6–T8 admin 网页录入核验是塌陷行业扩覆盖的落地路径；Phase 4 描述 LLM 加速。✓
- **D2 紧凑一行·事实优先**：T5 Step 2 卡片一行浅色小字 + "据往年" chip + 视觉分离。✓
- **D3 新表唯一源不双写**：T3–T5 卡片/抽屉直接读新表；老 insight_items timing 未改动。✓
- **D4 只做时机不做批次难度**：表无难度字段；展示只到时间/批次；Phase 4 及非目标明确排除。✓
- **D5 过期不删/绑届别/滚动追加**：T1 表有 `grad_class`+`valid_until`+`superseded_by`；RLS 读过滤过期（不删）；T6 校验强制 grad_class。✓
- **不变量 immutable**：T1 注释 + T7 PATCH 只碰可变三字段、POST 只建。✓
- **红线宁缺不编**：T1 RLS 只读 verified+未过期；T3 纯函数无 verified→null；卡片 timeline null→不显示。✓
- **测试**：T3（9）+T6（5）纯函数单测；migration/route 按既有约定不单测。✓
- **迁移规约**：182/183 前缀、183 带 `_seed_`。✓

无占位符；类型 `RecruitmentObservation`/`CampusTimeline`/`campusTimelineSummary`/`validateCycleInput` 在跨任务引用处签名一致。
