> ⚠️ **已被取代（2026-06-24）**：本文为早期三模式版，已被 `04-技术规格v3.md` 取代（见 `README.md`）。仅作背景参考。

# 个人机会时效雷达 Technical Spec

> 日期：2026-06-24
> 状态：新版技术规格，供实现 agent 执行
> 产品规格：`docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-product-spec.md`
> 战略文档：`docs/opportunity-timing-radar-specs/产品转型方案-个人机会时效雷达.md`
> 验收规格：`docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-acceptance-spec.md`

---

## 0. 技术结论

个人机会时效雷达在技术上可行，但必须分清两层：

1. **V1 可立即兑现的用户价值**
   用现有 `jobs` current-state 表和用户动作表，可靠展示新机会、最近确认仍在招、截止临近、短期招聘动量、关闭/陈旧。

2. **长期必须补齐的系统能力**
   增加 append-only 事件台账和 per-user delivery ledger，避免“机会变化”被临时从 current state 推导，支撑去重、摘要、追溯和数据质量审计。

V1 不需要先完成复杂的岗位内容 diff；内容 hash 变化只作为后台内部事件，不进入用户体验。

---

## 1. 当前系统基线

### 1.1 jobs 数据库

权威岗位热表位于独立 PostgreSQL，schema 见：

- `jobs-db/schema.sql`

关键字段：

```text
id
source_id
company
title
location
job_type
summary
jd_url
apply_url
salary_text
posted_at
first_seen_at
last_seen_at
status
content_hash
experience
education
deadline
enrich_checked_at
canonical_jd_url
search_doc
```

已具备的能力：

- `first_seen_at`：新发现；
- `last_seen_at`：最近确认；
- `status`：active / removed / expired / error；
- `content_hash`：内容变化埋点基础；
- `deadline`：截止提醒基础；
- `canonical_jd_url`：官方详情页去重；
- `search_doc`：FTS 召回；
- active canonical unique：避免重复 active 岗位。

### 1.2 crawler 写入语义

权威写入路径：

- `crawler/jobs_db.py`：香港 jobs PostgreSQL 写入；
- `crawler/db.py`：Supabase jobs 回退路径；
- `lib/jobs-store/write.ts`：应用侧写入。

关键语义：

- 新岗位插入时设置 `first_seen_at=now`、`last_seen_at=now`；
- 既有岗位更新时保持 `first_seen_at`，刷新 `last_seen_at`；
- `expired` 是 detail 探活确认撤岗后的强信号，列表重抓不复活；
- `removed` 可在再次出现时恢复 active；
- summary/job_type/experience/education/deadline 等字段新值为空时保留旧值，避免列表重抓抹掉富化结果。

这些语义必须保留。

### 1.3 Supabase 用户侧数据

现有或 6/23 pivot 已设计的数据：

- `user_preferences`
- `candidate_profiles`
- `job_actions`
- `events`
- `profiles`
- `sources`
- `crawl_runs`
- `discovery_runs`
- `user_radar_state`
- `notification_settings`
- `company_watch_requests`

如果当前实现分支尚未合入 `user_radar_state / notification_settings / company_watch_requests / job_action_feedback`，本规格要求继续实现，不回退到前台直写 Supabase 的旧模式。

### 1.4 已有 Opportunity Engine

6/23 pivot 分支中已有以下模块设计或实现：

```text
lib/opportunities/
  types.ts
  profile.ts
  freshness.ts
  eligibility.ts
  scoring.ts
  grouping.ts
  service.ts
  feedback.ts
  action-input.ts
  hydration.ts
  today-reducer.ts
```

新版要求不是推翻这些模块，而是扩展它们：

- 增加 `RadarMode`；
- 增加 `OpportunitySignalType`；
- 增加 deadline 和 momentum；
- 调整 grouping 从“分数分区”升级为“信号分区 + 模式阈值”；
- 增加用户展示去重和摘要边界；
- 明确禁止内容变更用户展示。

---

## 2. 权威类型

### 2.1 RadarMode

在 `lib/opportunities/types.ts` 增加：

```ts
export type RadarMode = "sprint" | "watch" | "campus";
```

### 2.2 OpportunitySignalType

```ts
export type OpportunitySignalType =
  | "NEW_MATCH"
  | "STILL_OPEN_PRIORITY"
  | "DEADLINE_SOON"
  | "COMPANY_MOMENTUM"
  | "CLOSED_OR_STALE";
```

后台内部事件可扩展：

```ts
export type InternalJobEventType =
  | "JOB_FIRST_SEEN"
  | "JOB_STILL_OPEN_CONFIRMED"
  | "JOB_CLOSED"
  | "JOB_CONTENT_HASH_CHANGED_INTERNAL"
  | "JOB_REAPPEARED_INTERNAL";
```

注意：

- `JOB_CONTENT_HASH_CHANGED_INTERNAL` 不得映射为用户侧 `OpportunitySignalType`；
- `JOB_REAPPEARED_INTERNAL` 不得在 V1 展示为重新开放。

### 2.3 RadarProfile

扩展现有 `RadarProfile`：

```ts
export interface RadarProfile {
  userId: string;
  mode: RadarMode;
  targetRoles: string[];
  targetKeywords: string[];
  excludeKeywords: string[];
  targetLocations: string[];
  targetCompanies: string[];
  targetIndustries: string[];
  skills: string[];
  experienceStage: "" | "实习" | "校招" | "社招";
  seniority: string | null;
  highestEducation: "博士" | "硕士" | "本科" | "大专" | null;
  dailyLimit: number;
}
```

默认：

- 新用户默认 `mode='sprint'`，但 onboarding 必须让用户确认；
- 旧用户无 mode 时使用 `sprint`，并在偏好页提示确认。

### 2.4 OpportunitySignal

新增：

```ts
export interface OpportunitySignal {
  type: OpportunitySignalType;
  label: string;
  priority: number;
  evidence: {
    firstSeenAt?: string | null;
    lastSeenAt?: string | null;
    deadlineAt?: string | null;
    sourceId?: string | null;
    freshness?: FreshnessState;
    companyWindow?: {
      company: string;
      recentDays: number;
      recentNewJobs: number;
      previousNewJobs: number;
      representativeJobIds: string[];
    };
    status?: string | null;
  };
}
```

要求：

- 每个 Today opportunity 至少有一个 `signals[]`；
- `signals[]` 是用户展示和 analytics 的统一来源；
- 不允许 UI 自己从字段临时判断标签。

### 2.5 Opportunity

扩展现有 `Opportunity`：

```ts
export interface Opportunity {
  job: Job;
  score: number;
  tier: OpportunityTier;
  reasons: OpportunityReason[];
  signals: OpportunitySignal[];
  freshness: FreshnessState;
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  deadlineAt: string | null;
  userAction: "saved" | "ignored" | "applied" | null;
  viewed: boolean;
  isNew: boolean;
  mode: RadarMode;
}
```

### 2.6 FeedSections

当前 `new / priority / explore / aging` 需要升级为模式化分区。

```ts
export interface FeedSection {
  key:
    | "new_matches"
    | "priority"
    | "deadline"
    | "company_momentum"
    | "saved_status_changes"
    | "explore"
    | "awaiting_confirmation";
  title: string;
  description: string;
  opportunities: Opportunity[];
}

export interface OpportunityFeed {
  generated_at: string;
  profile_ready: boolean;
  mode: RadarMode;
  candidate_capped: boolean;
  last_opened_at: string | null;
  counts: {
    total: number;
    by_signal: Record<OpportunitySignalType, number>;
    verified: number;
    aging: number;
    deadline_soon: number;
    company_momentum: number;
  };
  sections: FeedSection[];
}
```

---

## 3. 数据模型变更

### 3.1 Supabase migration：`164_user_preferences_radar_mode.sql`

在 `user_preferences` 增加：

```sql
alter table user_preferences
  add column if not exists radar_mode text not null default 'sprint'
    check (radar_mode in ('sprint', 'watch', 'campus'));

alter table user_preferences
  add column if not exists radar_mode_confirmed_at timestamptz;
```

要求：

- 不接受客户端传 `user_id`；
- 只允许 API 写当前用户；
- 老用户默认 sprint；
- 用户在 onboarding 或偏好页确认后写 `radar_mode_confirmed_at=now()`。

### 3.2 Supabase migration：`165_user_opportunity_deliveries.sql`

新增 per-user delivery ledger，用于去重、摘要、审计。

```sql
create table if not exists user_opportunity_deliveries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid,
  company text,
  signal_type text not null check (signal_type in (
    'NEW_MATCH',
    'STILL_OPEN_PRIORITY',
    'DEADLINE_SOON',
    'COMPANY_MOMENTUM',
    'CLOSED_OR_STALE'
  )),
  delivery_key text not null,
  surface text not null check (surface in ('today', 'email')),
  radar_mode text not null check (radar_mode in ('sprint', 'watch', 'campus')),
  score integer,
  tier text,
  delivered_at timestamptz not null default now(),
  consumed_at timestamptz,
  dismissed_at timestamptz,
  payload jsonb not null default '{}'::jsonb,
  unique (user_id, delivery_key, surface)
);

create index if not exists idx_user_opportunity_deliveries_user_delivered
  on user_opportunity_deliveries (user_id, delivered_at desc);

create index if not exists idx_user_opportunity_deliveries_signal_delivered
  on user_opportunity_deliveries (signal_type, delivered_at desc);
```

`delivery_key` 生成规则：

```text
job-level:
  ${signal_type}:${job_id}:${evidence_date_bucket}

company momentum:
  COMPANY_MOMENTUM:${normalized_company}:${window_start}:${window_end}
```

RLS：

- 用户可 select 自己；
- 用户不可直接 insert/update/delete；
- 写入由 API service role 完成；
- service role 可读写全部；
- admin aggregate 使用 service role RPC，不暴露用户明细。

Payload 允许：

- signal evidence；
- section key；
- score tier；
- company；
- normalized company；
- representative job ids；
- deadline date。

Payload 禁止：

- 用户邮箱；
- 简历原文；
- reason_text；
- 完整 JD；
- 带 token 的 URL。

### 3.3 jobs-db migration：`2026_06_24_job_events.sql`

长期必须增加 append-only jobs 事件表。若实现 agent 要拆阶段，允许先完成用户侧 V1，再做此迁移；但技术方案必须以此为最终方向。

```sql
create table if not exists job_events (
  id uuid primary key default gen_random_uuid(),
  event_key text not null unique,
  job_id uuid not null references jobs(id) on delete cascade,
  source_id uuid,
  event_type text not null check (event_type in (
    'JOB_FIRST_SEEN',
    'JOB_STILL_OPEN_CONFIRMED',
    'JOB_CLOSED',
    'JOB_CONTENT_HASH_CHANGED_INTERNAL',
    'JOB_REAPPEARED_INTERNAL'
  )),
  occurred_at timestamptz not null default now(),
  observed_at timestamptz not null default now(),
  old_status text,
  new_status text,
  old_content_hash text,
  new_content_hash text,
  changed_fields text[] not null default '{}',
  confidence text not null default 'observed'
    check (confidence in ('observed', 'derived', 'low')),
  payload jsonb not null default '{}'::jsonb
);

create index if not exists idx_job_events_job_time
  on job_events (job_id, occurred_at desc);

create index if not exists idx_job_events_type_time
  on job_events (event_type, occurred_at desc);

create index if not exists idx_job_events_source_time
  on job_events (source_id, occurred_at desc);
```

`event_key` 规则：

```text
JOB_FIRST_SEEN:${job_id}
JOB_STILL_OPEN_CONFIRMED:${job_id}:${yyyy-mm-dd}:${source_id}
JOB_CLOSED:${job_id}:${new_status}:${yyyy-mm-dd}
JOB_CONTENT_HASH_CHANGED_INTERNAL:${job_id}:${new_hash}
JOB_REAPPEARED_INTERNAL:${job_id}:${yyyy-mm-dd}
```

说明：

- `JOB_STILL_OPEN_CONFIRMED` 按天去重，不要每次 crawler 命中都插一条；
- content hash 变化内部记录即可，不要触发用户侧提醒；
- `JOB_REAPPEARED_INTERNAL` 仅从 `removed -> active` 产生；`expired -> active` 当前不应由列表重抓复活。

### 3.4 字段契约总表

实现 agent 必须按本表核对字段，不能只看 SQL 片段。

#### `user_preferences` 新增字段

| 字段 | 类型 | 必填 | 默认值 | 合法值 | 写入者 | 用途 |
|---|---|---:|---|---|---|---|
| `radar_mode` | `text` | 是 | `'sprint'` | `sprint` / `watch` / `campus` | `/api/preferences` | 决定 profile readiness、feed 阈值、分区和通知默认值 |
| `radar_mode_confirmed_at` | `timestamptz` | 否 | `null` | 合法时间 | `/api/preferences` | 区分系统默认模式和用户已确认模式 |

#### `user_opportunity_deliveries`

| 字段 | 类型 | 必填 | 默认值 | 合法值 / 约束 | 写入者 | 用途 |
|---|---|---:|---|---|---|---|
| `id` | `uuid` | 是 | `gen_random_uuid()` | primary key | DB | 行标识 |
| `user_id` | `uuid` | 是 | 无 | references `auth.users(id)` | service API | 用户隔离 |
| `job_id` | `uuid` | 否 | `null` | job-level signal 必填；company momentum 可空 | service API | 关联岗位 |
| `company` | `text` | 否 | `null` | momentum 必填；job-level 可取 job.company | service API | 公司级信号展示和去重 |
| `signal_type` | `text` | 是 | 无 | 五类用户侧 signal | service API | 用户收到的机会变化类型 |
| `delivery_key` | `text` | 是 | 无 | 同一用户同一 surface 幂等 | service API | 防重复展示/邮件 |
| `surface` | `text` | 是 | 无 | `today` / `email` | service API | 投递面 |
| `radar_mode` | `text` | 是 | 无 | `sprint` / `watch` / `campus` | service API | 审计当时模式 |
| `score` | `integer` | 否 | `null` | 0–100 | service API | 审计排序，不向用户展示 |
| `tier` | `text` | 否 | `null` | `high` / `related` / `explore` | service API | 审计档位 |
| `delivered_at` | `timestamptz` | 是 | `now()` | 合法时间 | DB/API | 首次投递时间 |
| `consumed_at` | `timestamptz` | 否 | `null` | 合法时间 | `/api/radar/open` 或 action API | 用户已看/已消费 |
| `dismissed_at` | `timestamptz` | 否 | `null` | 合法时间 | action API | 用户关闭或忽略该提醒 |
| `payload` | `jsonb` | 是 | `{}` | 不含 PII；见隐私规则 | service API | 保存 signal evidence |

唯一约束：

```text
unique (user_id, delivery_key, surface)
```

job-level `delivery_key` 必须包含日期桶，避免长期机会永远不再出现：

| signal | date bucket |
|---|---|
| `NEW_MATCH` | `yyyy-mm-dd(first_seen_at)` |
| `STILL_OPEN_PRIORITY` | `yyyy-mm-dd(last_seen_at)` |
| `DEADLINE_SOON` | `yyyy-mm-dd(deadlineAt)` |
| `CLOSED_OR_STALE` | `yyyy-mm-dd(now)`，同一 job 7 天内只能一条 |
| `COMPANY_MOMENTUM` | `window_start:window_end` |

#### `job_events`

| 字段 | 类型 | 必填 | 默认值 | 合法值 / 约束 | 写入者 | 用途 |
|---|---|---:|---|---|---|---|
| `id` | `uuid` | 是 | `gen_random_uuid()` | primary key | DB | 行标识 |
| `event_key` | `text` | 是 | 无 | unique | crawler / app writer | 事件幂等 |
| `job_id` | `uuid` | 是 | 无 | references `jobs(id)` | crawler / app writer | 关联岗位 |
| `source_id` | `uuid` | 否 | `null` | source id | crawler / app writer | 关联来源 |
| `event_type` | `text` | 是 | 无 | 五类内部 job event | crawler / app writer | 岗位事实变化类型 |
| `occurred_at` | `timestamptz` | 是 | `now()` | 事实发生时间 | crawler / app writer | 排序和追溯 |
| `observed_at` | `timestamptz` | 是 | `now()` | 系统观察时间 | crawler / app writer | 观测延迟 |
| `old_status` | `text` | 否 | `null` | active/removed/expired/error | crawler / app writer | 状态变化证据 |
| `new_status` | `text` | 否 | `null` | active/removed/expired/error | crawler / app writer | 状态变化证据 |
| `old_content_hash` | `text` | 否 | `null` | hash | crawler / app writer | 内部内容变化证据 |
| `new_content_hash` | `text` | 否 | `null` | hash | crawler / app writer | 内部内容变化证据 |
| `changed_fields` | `text[]` | 是 | `{}` | V1 通常为空 | crawler / app writer | 未来字段级 diff |
| `confidence` | `text` | 是 | `observed` | `observed` / `derived` / `low` | crawler / app writer | 事实置信度 |
| `payload` | `jsonb` | 是 | `{}` | 不含 PII | crawler / app writer | 额外证据 |

`job_events` 不做 RLS，因为它位于 jobs PostgreSQL，不直接给客户端读。客户端只读 `/api/opportunities` 生成后的用户侧 signal。

### 3.5 不新增的东西

本轮不新增：

- 向量数据库；
- Redis；
- Kafka / 队列系统；
- LLM ranking 表；
- 复制 jobs 到 Supabase；
- per-user feed cache 大表；
- JD 全量历史快照表。

---

## 4. Profile 与模式合并

### 4.1 buildRadarProfile

`lib/opportunities/profile.ts`：

- 从 `user_preferences` 读取手工偏好；
- 从 `candidate_profiles` 补充 skills、education、seniority；
- 手工偏好优先；
- 简历不得覆盖目标岗位、城市、公司、排除词；
- dailyLimit 按 mode clamp。

Mode default：

```ts
const DEFAULT_MODE: RadarMode = "sprint";
```

Daily limit：

| mode | default | min | max |
|---|---:|---:|---:|
| sprint | 15 | 5 | 30 |
| watch | 8 | 3 | 15 |
| campus | 20 | 5 | 30 |

### 4.2 isProfileReady

按 mode 判断：

```ts
function isProfileReady(profile: RadarProfile): boolean {
  const hasContent =
    profile.targetRoles.length > 0 ||
    profile.targetKeywords.length > 0 ||
    profile.targetCompanies.length > 0;

  if (profile.mode === "sprint") {
    return hasContent && profile.targetLocations.length > 0;
  }

  if (profile.mode === "watch") {
    return hasContent;
  }

  if (profile.mode === "campus") {
    return (
      (profile.experienceStage === "校招" || profile.experienceStage === "实习") &&
      hasContent
    );
  }

  return false;
}
```

---

## 5. Freshness SLA

保留 6/23 设计：

| crawl_method | verified | aging |
|---|---:|---:|
| http | 18h | 36h |
| playwright | 36h | 72h |
| manual，或 source 行存在但 `crawl_method` 为空 | 72h | 144h |

规则：

- `last_seen_at` 缺失或非法 → `unknown`；
- source metadata 查询整体失败 → 本次 feed 返回 503 `feed_unavailable`，不得猜测 freshness；
- 单个岗位的 `source_id` 为空，或 `source_id` 在 metadata 查询结果中找不到 → 该岗位 freshness=`unknown`；
- source 行存在但 `crawl_method` 为空 → 按 manual SLA；
- `age <= verified` → `verified`；
- `verified < age <= aging` → `aging`；
- `age > aging` → `stale`。

用户侧信号约束：

- `NEW_MATCH` 必须 verified；
- `STILL_OPEN_PRIORITY` 必须 verified；
- `DEADLINE_SOON` 可接受 verified 或 aging，但 aging 必须显示提醒；
- `COMPANY_MOMENTUM` 代表岗位 verified 比例必须 >= 50%；
- `CLOSED_OR_STALE` 可由 stale 触发；
- `unknown` 不进入 Today 主队列。

---

## 6. Deadline 解析

新增：

```text
lib/opportunities/deadline.ts
```

导出：

```ts
export interface ParsedDeadline {
  date: string; // YYYY-MM-DD
  source: "iso" | "cn_date" | "slash_date" | "month_day";
  confidence: "high" | "medium";
}

export function parseDeadline(raw: string | null, now: Date): ParsedDeadline | null;
export function daysUntilDeadline(parsed: ParsedDeadline, now: Date): number;
```

可解析格式：

- `2026-07-15`
- `2026/07/15`
- `2026.07.15`
- `2026年7月15日`
- `7月15日`，年份按 now 推断；如果推断日期已过去超过 30 天，则使用下一年；
- `07-15`，同上，confidence 为 medium。

不解析：

- `长期有效`
- `招满即止`
- `尽快`
- `本周内`
- `若干天后`
- 多个日期但无法判断截止语义的文本。

触发窗口：

| mode | deadline soon |
|---|---:|
| sprint | <= 7 天 |
| watch | <= 7 天，仅 saved/target company |
| campus | <= 14 天 |

过期：

- `daysUntilDeadline < 0` 不触发 `DEADLINE_SOON`；
- 如果岗位仍 active 但 deadline 已过，不能强行判 closed；
- 可在卡片中不展示 deadline 标签。

---

## 7. 招聘动量

新增：

```text
lib/opportunities/momentum.ts
```

导出：

```ts
export interface CompanyMomentumSignal {
  company: string;
  normalizedCompany: string;
  recentDays: number;
  recentNewJobs: number;
  previousNewJobs: number;
  representativeJobIds: string[];
  confidence: "medium" | "high";
}

export function deriveCompanyMomentum(...): CompanyMomentumSignal[];
```

### 7.1 数据窗口

默认：

```text
recent window = now - 14 days to now
previous window = now - 28 days to now - 14 days
```

查询范围：

- 优先 target companies；
- 其次 feed 中通过硬门的公司；
- 每个用户最多计算 30 家公司；
- 只看 `status='active'`；
- 只看 summary 有效岗位；
- 代表岗位必须通过用户硬门或命中 target company。

### 7.2 触发阈值

满足任一：

```text
recentNewJobs >= 3
AND recentNewJobs >= previousNewJobs + 2
```

或：

```text
previousNewJobs < 3
AND recentNewJobs >= 5
```

同时：

- representative jobs >= 2；
- verified representative jobs ratio >= 50%；
- 同一 user/company 7 天内未 delivery 相同 momentum；
- watch 模式只对 target companies 或 score 高公司展示。

### 7.3 展示形态

公司动量是 section 或 group，不是单个岗位硬塞进 job card。

展示：

```text
字节跳动近两周新增 8 个与你相关的官方岗位
据本平台已覆盖官方源观察，主要集中在上海、产品/数据方向。
```

代表岗位：

- 最多 5 个；
- 排序按 score、deadline、first_seen；
- 每个岗位仍显示官方链接和单岗位信号。

---

## 8. Signal Derivation

新增：

```text
lib/opportunities/signals.ts
```

导出：

```ts
export function deriveOpportunitySignals(input: {
  job: Job;
  facts: MatchFacts;
  score: ScoreResult;
  profile: RadarProfile;
  noveltySince: string;
  parsedDeadline: ParsedDeadline | null;
  now: Date;
}): OpportunitySignal[];
```

规则顺序：

1. `DEADLINE_SOON`
2. `NEW_MATCH`
3. `STILL_OPEN_PRIORITY`
4. `CLOSED_OR_STALE`

`COMPANY_MOMENTUM` 由 `momentum.ts` 公司级生成，再关联代表岗位。

### 8.1 NEW_MATCH

```ts
isNew = job.first_seen_at != null && job.first_seen_at > noveltySince
```

阈值：

- sprint/campus: score >= 45；
- watch: score >= 70 or facts.companyHit。

freshness 必须 verified。

### 8.2 STILL_OPEN_PRIORITY

阈值：

- freshness verified；
- score >= 70；
- not new；
- not deadline soon；
- mode watch 时 score >= 85 或 companyHit。

### 8.3 DEADLINE_SOON

阈值：

- parsed deadline exists；
- within mode window；
- active；
- freshness verified or aging。

### 8.4 CLOSED_OR_STALE

只对用户已交互或关注对象：

- saved；
- viewed；
- target company；
- delivery 过但未处理。

触发：

- status expired/removed/error；
- freshness stale。

不进入主推荐，进入 saved/status section。

---

## 9. Eligibility 与 Scoring

保留 6/23 的硬门顺序，并加 mode 调整。

### 9.1 通用硬门

1. inactive reject；
2. thin summary reject；
3. source disabled reject；
4. freshness stale/unknown reject 主队列；
5. exclude keywords reject；
6. already ignored/applied/saved reject 主推荐；
7. role/keyword constrained 且不匹配 reject；
8. location mismatch reject；
9. stage mismatch reject；
10. education mismatch reject；
11. industry mismatch reject，target company 命中时跳过行业拒绝。

### 9.2 mode 调整

#### sprint

- location 是 profile_ready 硬要求；
- related 可进 explore；
- aging 仅在 verified 少于 5 时展示。

#### watch

- location 不是硬要求；
- ordinary related 不进主队列；
- target company 权重更高；
- 不展示 aging 普通岗位；
- 关闭/陈旧只针对 saved/target company。

#### campus

- experienceStage 必须是 校招/实习；
- stage mismatch 直接 reject；
- deadline 权重高；
- 城市允许 `全国 / 多地 / 不限 / 远程` 匹配任何目标城市。

### 9.3 Score V2 调整

保留现有分值，并增加：

| 信号 | sprint | watch | campus |
|---|---:|---:|---:|
| target company | +15 | +25 | +15 |
| deadline soon | +10 | +8 | +25 |
| campus/intern stage match | +10 | +5 | +20 |
| viewed but no action | -8 | -12 | -8 |
| aging | 不进主队列 | 不进主队列 | 可进 deadline 区但 -5 |

Score 仍只作内部排序，不向用户展示数字。

---

## 10. Grouping

新增：

```text
lib/opportunities/mode-config.ts
```

示例：

```ts
export const MODE_CONFIG = {
  sprint: {
    sections: ["deadline", "new_matches", "priority", "explore", "awaiting_confirmation"],
    dailyLimitDefault: 15,
    deadlineDays: 7,
    minScoreNew: 45,
    minScorePriority: 70,
  },
  watch: {
    sections: ["company_momentum", "new_matches", "saved_status_changes"],
    dailyLimitDefault: 8,
    deadlineDays: 7,
    minScoreNew: 70,
    minScorePriority: 85,
  },
  campus: {
    sections: ["deadline", "new_matches", "priority", "company_momentum"],
    dailyLimitDefault: 20,
    deadlineDays: 14,
    minScoreNew: 45,
    minScorePriority: 65,
  },
} as const;
```

去重规则：

- 一个 job 可有多个 signals，但只出现一次；
- section 选择按 signal priority；
- deadline 优先于 new；
- saved/applied/ignored 不进入主推荐；
- company momentum representative jobs 可以在 company section 内出现，但不能再在普通 section 重复。

截断规则：

- 总量不超过 `dailyLimit`，但 `saved_status_changes` 可以额外最多 5 个；
- deadline section 最多 8；
- company momentum 最多 3 个公司，每公司最多 5 个代表岗位；
- explore 最多 5；
- awaiting_confirmation 最多 3。

---

## 11. API 规格

### 11.0 通用 API 契约

所有 JSON API 必须使用统一响应形态。

成功：

```json
{
  "ok": true
}
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "validation_failed",
    "message": "请求参数不合法",
    "fields": {
      "radar_mode": "must be sprint, watch, or campus"
    },
    "request_id": "optional-server-request-id"
  }
}
```

错误对象规则：

- `code` 必填，使用 snake_case；
- `message` 必填，面向用户或 agent 可理解；
- `fields` 可选，仅用于 400/422 字段错误；
- 不返回堆栈；
- 不返回 service role error 原文；
- 不返回用户邮箱、简历、完整 JD、reason_text 或带 token 的 URL。

状态码矩阵：

| HTTP | code | 适用场景 |
|---:|---|---|
| 400 | `invalid_json` | body 不是合法 JSON |
| 400 | `validation_failed` | 字段类型、枚举、长度、数组上限不合法 |
| 401 | `unauthorized` | 未登录 |
| 403 | `forbidden` | 已登录但无权访问 admin 或他人资源 |
| 404 | `job_not_found` | action/view 的 jobId 在权威 jobs 库不存在 |
| 409 | `conflict` | 并发写入或唯一约束冲突且无法自动幂等恢复 |
| 422 | `profile_not_ready` | 调用需要完整画像的写入/生成动作但画像不满足 mode 条件 |
| 503 | `feed_unavailable` | jobs store 失败、source metadata 查询整体失败、delivery 写入失败或 Opportunity Engine 异常 |

鉴权规则：

- 用户相关 API 必须调用 `requireUser()`；
- admin API 必须调用 `requireAdmin()`；
- 请求体中的 `user_id` 一律拒绝或忽略，但行为必须在测试中固定：推荐返回 400 `validation_failed`；
- 所有写入使用服务端当前用户 id。

### 11.1 `GET /api/preferences`

请求：

```http
GET /api/preferences
```

返回：

```json
{
  "ok": true,
  "preferences": {
    "radar_mode": "sprint",
    "radar_mode_confirmed_at": "2026-06-24T00:00:00.000Z",
    "target_roles": [],
    "target_keywords": [],
    "exclude_keywords": [],
    "target_locations": [],
    "target_companies": [],
    "target_industries": [],
    "daily_limit": 15
  },
  "profile_ready": true,
  "profile_ready_missing": [],
  "coverage": [],
  "notification_settings": {}
}
```

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 成功；即使没有 preference 行也返回默认值 |
| 401 | `unauthorized` | 未登录 |
| 503 | `preferences_unavailable` | Supabase 查询失败 |

### 11.2 `PUT /api/preferences`

接受：

```json
{
  "radar_mode": "watch",
  "target_locations": ["上海"],
  "target_roles": ["产品经理"],
  "target_keywords": ["AI"],
  "exclude_keywords": ["销售"],
  "target_companies": ["字节跳动"],
  "target_industries": ["互联网"],
  "daily_limit": 8
}
```

校验：

- radar_mode 必须是 sprint/watch/campus；
- 数组去空、trim、去重；
- 单数组最多 30；
- 单项最多 80 字；
- daily_limit 按 mode clamp；
- 不接受 `user_id`；
- 保存 target_companies 后同步 `company_watch_requests`。

响应：

```json
{
  "ok": true,
  "preferences": {
    "radar_mode": "watch",
    "daily_limit": 8
  },
  "profile_ready": true,
  "profile_ready_missing": [],
  "coverage": [
    {
      "company": "字节跳动",
      "status": "covered",
      "matched_sources": 2
    }
  ]
}
```

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 保存成功 |
| 400 | `invalid_json` | body 非 JSON |
| 400 | `validation_failed` | 包含 `user_id`、非法 mode、数组过长、单项过长、类型错误 |
| 401 | `unauthorized` | 未登录 |
| 503 | `preferences_unavailable` | Supabase 写入失败 |

### 11.3 `GET /api/opportunities`

读取当前用户 profile、actions、radar state，返回：

```json
{
  "ok": true,
  "generated_at": "2026-06-24T00:00:00.000Z",
  "profile_ready": true,
  "mode": "sprint",
  "candidate_capped": false,
  "last_opened_at": null,
  "counts": {
    "total": 12,
    "by_signal": {
      "NEW_MATCH": 5,
      "STILL_OPEN_PRIORITY": 4,
      "DEADLINE_SOON": 2,
      "COMPANY_MOMENTUM": 1,
      "CLOSED_OR_STALE": 0
    },
    "verified": 11,
    "aging": 1,
    "deadline_soon": 2,
    "company_momentum": 1
  },
  "sections": []
}
```

要求：

- GET 不更新 `last_opened_at`；
- 生成时可写 `user_opportunity_deliveries`，但必须 idempotent；
- 如果 profile 不 ready，返回 `profile_ready=false` 和空 sections；
- 如果 feed 失败，返回 503，不返回 mock 数据。

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 成功；profile 不完整也返回 200 + 空 feed |
| 401 | `unauthorized` | 未登录 |
| 503 | `feed_unavailable` | 权威 jobs 读取失败、source metadata 查询整体失败、delivery 写入失败、engine 异常 |

`profile_ready=false` 不是错误；不得返回 422。它是前台 onboarding 状态。

delivery 写入规则：

- `surface='today'`；
- 对每个返回 opportunity 的每个 signal upsert 一条 delivery；
- 使用 `(user_id, delivery_key, surface)` 幂等；
- delivery 写入失败时，本次 feed 返回 503，不允许“feed 成功但去重台账失败”，否则会造成重复提醒；
- 如果实现方选择 Phase A 暂不写 delivery，必须在交付说明标注“delivery ledger 未接入”，且 acceptance 中相关用例不得宣称通过。

### 11.4 `POST /api/radar/open`

作用：

- 用户真实打开 Today 时更新 `user_radar_state.last_opened_at`；
- 写 `radar_feed_opened` event；
- 可标记 delivery consumed。

请求：

```json
{
  "surface": "today",
  "generated_at": "2026-06-24T00:00:00.000Z"
}
```

服务端：

- 不接受 user_id；
- `last_opened_at=now()`；
- `last_feed_generated_at=generated_at`；
- `last_feed_count` 使用服务端最近 feed count 或请求中安全字段，不信任客户端完整 feed。

响应：

```json
{
  "ok": true,
  "last_opened_at": "2026-06-24T08:30:00.000Z"
}
```

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 更新成功 |
| 400 | `validation_failed` | `surface` 非 today/email，`generated_at` 非 ISO 时间，包含 `user_id` |
| 401 | `unauthorized` | 未登录 |
| 503 | `radar_state_unavailable` | Supabase upsert 失败 |

### 11.5 `POST /api/job-actions/[jobId]`

请求：

```json
{
  "action": "ignored",
  "reason_code": "location_mismatch",
  "reason_text": "可选，最长 200 字"
}
```

要求：

- 写主动作 saved/ignored/applied；
- ignored 必须有 `reason_code`；
- reason_text 最长 200；
- 服务端用 `jobsByIds(jobId)` 校验岗位存在并生成 snapshot；
- 不接受客户端 snapshot；
- action 成功后记录 event；
- action 失败时前端不得乐观永久改变。

响应：

```json
{
  "ok": true,
  "action": "ignored",
  "job_id": "00000000-0000-0000-0000-000000000000"
}
```

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 写入成功 |
| 400 | `invalid_json` | body 非 JSON |
| 400 | `validation_failed` | action 非法；ignored 缺 reason_code；reason_code 不在白名单；reason_text 超长；客户端传 job_snapshot/user_id |
| 401 | `unauthorized` | 未登录 |
| 404 | `job_not_found` | jobs 权威库查不到 jobId |
| 409 | `conflict` | 原子主动作 RPC 冲突且无法恢复 |
| 503 | `job_action_unavailable` | jobs 查询或 Supabase 写入失败 |

### 11.6 `POST /api/job-actions/[jobId]/view`

请求：

```json
{}
```

作用：

- 记录 viewed；
- 幂等；
- 不改变主动作；
- 不代表投递。

状态码：

| HTTP | code | 条件 |
|---:|---|---|
| 200 | 无 | 成功或已存在 viewed |
| 401 | `unauthorized` | 未登录 |
| 404 | `job_not_found` | jobs 权威库查不到 jobId |
| 503 | `job_view_unavailable` | 写入失败 |

---

## 12. Event Ledger 生成

### 12.1 crawler/jobs_db.py

为了生成 `job_events`，`_find_existing_id_by_canonical` 需要返回更多字段：

```text
id
status
content_hash
last_seen_at
source_id
```

实现建议：

- 增加 `_find_existing_by_canonical`，返回 dict；
- 保留旧函数兼容或同步替换；
- 单条 upsert 里比较旧值和新值；
- 批量 upsert 的 existing 查询也带上述字段；
- 插入/更新 jobs 后插入 job_events；
- event 插入必须 best-effort，不能因事件写失败导致 job upsert 失败。

### 12.2 事件触发

新插入：

```text
JOB_FIRST_SEEN
```

既有 active/removed 被列表命中并更新 last_seen：

```text
JOB_STILL_OPEN_CONFIRMED
```

但按天去重。

status 从 active 变为 expired/removed/error：

```text
JOB_CLOSED
```

content_hash 非空且变化：

```text
JOB_CONTENT_HASH_CHANGED_INTERNAL
```

removed -> active：

```text
JOB_REAPPEARED_INTERNAL
```

不允许 expired 被列表重抓复活。

### 12.3 lib/jobs-store/write.ts

应用侧写入也要遵循同样事件语义，尤其是 discovery/search 写入路径。

要求：

- 不复制两套事件判断；
- 可抽一个 SQL helper 或 TS helper；
- 事件写失败只 warning，不影响岗位写入；
- 测试覆盖 content hash internal event 不会进入 user signals。

---

## 13. UI 技术边界

### 13.1 `app/today/page.tsx`

服务端：

- 未登录 redirect `/login?next=/today`；
- 不再向匿名用户返回最新 200；
- 调 `/api/opportunities` 或直接使用 service；
- profile not ready 时传空 feed。

### 13.2 `app/today-client.tsx`

客户端：

- 渲染 mode；
- 渲染 signal sections；
- 打开页面后调用 `/api/radar/open`；
- 卡片 view 可懒触发；
- action 成功后更新本地状态；
- action 失败时回滚；
- 不自己推导 freshness label；
- 不展示 score 数字。

### 13.3 `app/preferences/page.tsx`

必须改成 API 保存：

- GET `/api/preferences`；
- PUT `/api/preferences`；
- 不直接从客户端写 Supabase；
- mode 选择清晰；
- company coverage 状态从 API 返回。

### 13.4 `app/jobs/page.tsx`

普通用户默认隐藏：

- refresh company；
- discovery dispatch；
- crawler 运行状态。

管理员或 feature flag 可见，但不作为主产品动作。

---

## 14. 安全与隐私

### 14.1 认证

所有用户相关 API 使用：

- `requireUser()`
- 不接受客户端 `user_id`
- 需要管理员的用 `requireAdmin()`

### 14.2 RLS

用户表：

- 用户可读自己的 preference/state/delivery；
- 写入通过 API；
- service role 用于后台摘要和 admin aggregate。

### 14.3 数据最小化

events 和 deliveries payload 不写敏感数据。

允许：

- job_id；
- signal_type；
- mode；
- section；
- score tier；
- freshness；
- reason_code；
- company 标准名或 hash。

禁止：

- email；
- resume text；
- phone；
- id card；
- reason_text；
- full JD；
- tokenized URL。

---

## 15. 测试要求

### 15.1 Unit tests

新增或更新：

```text
tests/opportunity-mode.test.js
tests/opportunity-signals.test.js
tests/opportunity-deadline.test.js
tests/opportunity-momentum.test.js
tests/opportunity-grouping.test.js
tests/opportunity-delivery.test.js
```

覆盖：

- mode profile readiness；
- mode daily limit clamp；
- deadline parsing；
- invalid deadline 不触发；
- NEW_MATCH 需要 verified；
- STILL_OPEN 不接受 unknown；
- watch 模式不展示普通 related；
- campus 阶段硬门；
- company momentum 样本门槛；
- content hash internal event 不映射用户 signal；
- delivery_key 去重；
- saved/ignored/applied 不进主推荐。

### 15.2 Python tests

新增或更新：

```text
crawler/test_jobs_db_events.py
```

覆盖：

- 新岗位生成 JOB_FIRST_SEEN；
- 同一天重复 still-open 只生成一次；
- content_hash 变化生成 internal event；
- expired 不被列表重抓复活；
- removed -> active 生成 internal reappeared；
- event 写失败不影响 upsert。

### 15.3 API tests

若项目已有 node route 测试模式，覆盖：

- `/api/preferences` 不接受 user_id；
- `/api/preferences` 保存 mode；
- `/api/opportunities` 返回 mode 和 signals；
- `/api/radar/open` 更新 state；
- `/api/job-actions/[jobId]` ignored 无 reason_code 返回 400；
- action API 生成服务端 snapshot。

### 15.4 必跑验证

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npm run build
git diff --check
```

如果 migration 改动：

```bash
bash scripts/check-migrations.sh
```

注意：

- 不把交互式 `npm run lint` 当作有效 gate；
- 不用 mock 数据冒充真实 DB 写入成功；
- feed 失败不能返回假成功。

---

## 16. 分阶段实现建议

### Phase A：用户模式 + 信号化 Feed

必须完成：

- `radar_mode`；
- profile readiness 按 mode；
- `OpportunitySignalType`；
- deadline parser；
- `deriveOpportunitySignals`；
- grouping 改为 signal sections；
- Today UI 展示 signal；
- 禁止内容变更展示。

### Phase B：动作闭环与去重

必须完成：

- `user_opportunity_deliveries`；
- action API reason 校验；
- radar open state；
- delivery_key 幂等；
- saved/status changes；
- events payload 清洗。

### Phase C：招聘动量

必须完成：

- `momentum.ts`；
- company section；
- 阈值和 7 天去重；
- watch/campus/sprint 差异化；
- admin metrics。

### Phase D：事件台账

必须完成：

- jobs-db `job_events`；
- crawler/jobs_db 事件写入；
- lib/jobs-store/write 事件写入；
- Python tests；
- content_hash internal only。

说明：

- Phase A+B 是产品可用的最小闭环；
- Phase C 是差异化增强；
- Phase D 是长期可靠性和追溯能力；
- 如果时间紧，不能为了 Phase D 牺牲 A+B 的用户体验和验收。

---

## 17. 迁移兼容性

实现 agent 必须先检查当前分支已有 migration 编号。

若 `161/162/163` 已存在：

- 追加 `164/165`；
- 不回改已应用历史迁移；
- 如果需要修正旧迁移，新增补丁迁移。

若当前分支没有 `161/162/163`：

- 按 6/23 spec 和本 spec 一并创建；
- 编号不得冲突；
- 所有 RLS 策略幂等。

jobs-db migration 命名按当前项目 jobs-db 习惯；如果没有 migrations 目录，可将 append-only schema 写入 `jobs-db/schema.sql` 并提供单独 apply SQL 文档，但不得破坏现有 jobs schema。
