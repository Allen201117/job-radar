# 个人机会雷达转型实施 Spec

> 状态：产品方向已确认，可交付实施 Agent
> 日期：2026-06-23
> 产品范围：综合白领求职市场
> 战略依据：`docs/产品转型方案-从岗位聚合到个人机会雷达.md`
> 本文优先级：用户最新指令 > `CLAUDE.md` > 本 Spec > 历史 Spec / README
> 目标：Agent 可直接据此拆任务和实现，不得重新发散产品方向

---

## 0. 执行摘要

本次不是重写 crawler，也不是新增一个平行产品，而是把现有能力重新组织为一个明确主任务：

> 用户设置一次目标后，系统每天从已保鲜的官方岗位库中，生成不超过每日上限的“值得处理机会队列”。

必须完成：

1. 将 `/today` 升级为唯一主产品“今日机会”；
2. 将匹配逻辑从粗粒度加权改为“硬门 + 可解释排序”；
3. 将岗位新鲜度作为进入今日机会的资格条件；
4. 将收藏 / 忽略 / 投递改造成清晰的机会处理动作；
5. 对“不适合”收集结构化原因；
6. 将 `/jobs` 中的用户主动刷新和发掘入口默认移除；
7. 将“关注公司”改造成异步覆盖请求，不让用户等待抓取；
8. 建立转型所需的行为指标和管理员统计；
9. 提供可选的每日邮件摘要，但默认关闭、用户主动开启；
10. 保留现有刷新、发现和 crawler 基础设施，不做破坏性删除。

不允许：

- 新增普通 crawler adapter；
- 扩充职业洞察维度；
- 做自动投递；
- 做简历润色；
- 引入新的推荐模型或向量数据库；
- 用 LLM 直接决定岗位排序；
- 将 source、crawler、workflow 等技术概念继续暴露给普通用户；
- 为了填满列表而混入明显不相关岗位。

---

## 1. 当前实现基线

### 1.1 可直接复用

| 能力 | 当前实现 | 本次处理 |
|---|---|---|
| 今日页 | `app/today/page.tsx` + `app/today-client.tsx` | 原地升级为主产品 |
| 岗位搜索 | `/api/jobs/search` + `lib/jobs-store/search.ts` | 保留，降为探索工具 |
| 基础打分 | `lib/scoring.ts` | 升级为 Opportunity Score V2 |
| 筛选 | `lib/job-filter.ts` | 继续服务 `/jobs` |
| 偏好 | `user_preferences` + `candidate_profiles` | 继续作为用户目标来源 |
| 用户动作 | `job_actions` | 扩展结构化负反馈 |
| 新鲜度 | `jobs.last_seen_at` | 提升为 Today 准入门 |
| 新岗位 | `jobs.first_seen_at` | 计算“自上次访问新增” |
| 失活处理 | liveness sweep / display check / dead-link audit | 保留 |
| 官方链接 | `jd_url` + canonical unique | 保留 |
| 职业洞察 | `CompanyInsightDrawer` | 保留为次级信息 |
| 主动刷新 | `/api/refresh` | 后台保留，普通 UI 默认隐藏 |
| 动态发现 | `/api/discovery/*` | 后台 / 管理员保留 |
| 埋点 | `events` + `/api/events` | 扩展事件口径 |
| 管理员健康页 | `/admin/health` | 增加消费侧漏斗 |

### 1.2 当前主要缺陷

1. Today 候选池最多 200 条，容易被最近完成抓取的大源影响。
2. Today 在预筛不足时使用“最新 active”兜底，虽然有相关性门，仍缺少完整的硬条件判断。
3. 当前 `match_score` 是无量纲累加，未完整使用阶段、学历、技能和 source freshness。
4. `daily_limit` 控制数量，但列表没有稳定分区，用户不知道优先处理什么。
5. `saved / ignored / applied` 是数据动作，不是清晰的产品决策语言。
6. 忽略岗位不记录原因，无法区分匹配错误和用户个人偏好。
7. `/jobs` 将本地搜索、刷新对口公司、发掘新公司平级展示，暴露技术实现。
8. 用户填写关注公司后，未覆盖公司不会形成明确的后台接入请求。
9. 没有可靠的“上次打开机会页”状态，无法准确计算“自上次访问新增”。
10. 没有用户可控的机会摘要通知。

---

## 2. 产品不变量

实施过程中以下规则不可被折中：

### 2.1 岗位质量

- Today 只展示 `status='active'`；
- Today 默认只展示 JD 正文有效的岗位：`summary` 去空白后长度至少 60；
- `jd_url` 必须继续通过现有官方详情页质量门；
- active `canonical_jd_url` 唯一约束不可移除；
- 无法确认仍在招的岗位不能伪装成“今天确认”；
- 失效检测异常时允许降级为 unknown，但不能误判 active 为 dead。

### 2.2 匹配诚实

- 排名可由确定性规则完成，不接 LLM；
- 不显示虚假的百分比准确率；
- 对用户展示匹配档位和具体原因，不展示内部权重细节；
- 明确硬条件不符的岗位不进入 Today；
- 信息缺失与明确不符必须区分；
- 列表不足时宁可少，不允许用无关岗位填满。

### 2.3 用户控制

- 简历画像和偏好仍由用户确认后保存；
- 负反馈不得自动修改用户偏好；
- 邮件摘要默认关闭；
- 用户可随时关闭摘要、删除关注公司；
- 不做自动投递；
- 不因打开官网自动标记“已投递”。

### 2.4 架构边界

- jobs 继续位于独立 PostgreSQL；
-用户、偏好、动作、事件、请求和通知设置继续位于 Supabase；
- 不在此次转型迁移 jobs 表；
- 不引入 Redis、向量数据库、消息队列或新搜索服务；
- 不复制一份 Python 版推荐算法；
- Opportunity Engine 的权威实现只存在于 TypeScript `lib/opportunities/`。

---

## 3. 新信息架构

### 3.1 顶部导航

修改 `components/Navbar.tsx`：

桌面与移动端主导航按以下顺序：

1. `/today`：今日机会
2. `/jobs`：搜索岗位
3. `/preferences`：关注与偏好
4. `/saved`：值得投
5. `/applied`：已投递

处理：

- `/path` 从一级导航移除，路由和代码保留；
- `/me` 从一级导航移除，放入账号菜单；
- `/sources`、`/admin/insights`、`/admin/health` 继续仅管理员直达；
- 登录后点击 Logo 跳 `/today`；
- 未登录点击 Logo 跳 `/`。

需要同步修改 `lib/i18n.ts` 的中文导航标签，但不恢复语言切换。

### 3.2 路由角色

| 路由 | 新角色 |
|---|---|
| `/` | 解释“系统每天替你筛机会”的公开 Landing |
| `/today` | 默认产品首页，登录后核心任务 |
| `/jobs` | 主动搜索和探索全库 |
| `/preferences` | 目标、画像、关注公司和通知设置 |
| `/saved` | “值得投”的候选清单 |
| `/applied` | 已投递记录 |
| `/path` | 保留为辅助工具，不在主导航 |
| `/sources` | 管理员处理 source 和覆盖请求 |

---

## 4. Onboarding 与画像完整度

### 4.1 Today 登录要求

修改 `app/today/page.tsx`：

- 未登录直接 `redirect('/login?next=/today')`；
- 不再向匿名用户展示“最新 200 条”；
- 登录后没有有效画像时显示 onboarding，而不是随机岗位。

### 4.2 有效画像定义

满足以下条件才视为可生成 Today：

```text
content_signal =
  target_roles 非空
  OR target_keywords 非空
  OR target_companies 非空

location_signal =
  target_locations 非空

profile_ready =
  content_signal AND location_signal
```

行业、技能、学历和阶段用于提高准确度，但不作为首次生成队列的强制字段。

### 4.3 Onboarding 空状态

当 `profile_ready=false`：

- 标题：`先告诉我们你想找什么`
- 说明：`设置目标岗位和城市后，系统会每天从企业官网中筛出值得处理的机会。`
- 主按钮：`设置求职目标` → `/preferences`
- 次按钮：`上传简历生成画像` → `/preferences#resume`
- 不展示任何随机岗位；
- 发送事件 `radar_onboarding_required`，payload 仅包含缺失字段布尔值。

### 4.4 偏好保存

新增：

- `app/api/preferences/route.ts`

替换 `PreferenceForm` 直接写 Supabase 的方式。

`GET /api/preferences` 返回：

```json
{
  "ok": true,
  "preferences": {},
  "profile_ready": true,
  "coverage": [
    {
      "company": "示例公司",
      "status": "covered",
      "matched_sources": 2
    }
  ],
  "notification_settings": {}
}
```

`PUT /api/preferences` 接受：

```json
{
  "target_locations": ["上海"],
  "target_roles": ["产品经理"],
  "target_keywords": ["AI"],
  "exclude_keywords": ["销售"],
  "target_companies": ["字节跳动"],
  "target_industries": ["互联网"],
  "daily_limit": 20
}
```

校验：

- 数组每项 trim、去空、大小写不敏感去重；
- 每个数组最多 30 项；
- 单项最长 80 字；
- `daily_limit` 限制为 5–30；
- 不接受 `user_id`；
- 只写当前登录用户；
- 保存成功后同步公司覆盖请求，见 §11。

---

## 5. 数据模型

当前最高迁移前缀为 `160_user_preferences_target_industries.sql`。新增迁移必须使用以下编号和职责，避免多个无关变更塞进同一迁移；已应用的历史迁移不得回改。

### 5.1 `161_radar_state_and_notification_settings.sql`

新增：

```sql
create table user_radar_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  last_opened_at timestamptz,
  last_feed_generated_at timestamptz,
  last_feed_count integer not null default 0 check (last_feed_count >= 0),
  updated_at timestamptz not null default now()
);

create table notification_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email_digest_enabled boolean not null default false,
  frequency text not null default 'daily'
    check (frequency in ('daily', 'weekdays')),
  send_hour smallint not null default 8
    check (send_hour between 0 and 23),
  timezone text not null default 'Asia/Shanghai',
  last_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

RLS：

- 用户可 select / insert / update 自己的 `user_radar_state`；
- 用户可 select / insert / update 自己的 `notification_settings`；
- 不允许客户端 delete；
- service role 可供摘要任务读取。

索引：

```sql
create index idx_notification_settings_due
  on notification_settings (email_digest_enabled, last_sent_at)
  where email_digest_enabled = true;
```

### 5.2 `162_job_action_feedback.sql`

扩展 `job_actions`：

```sql
alter table job_actions
  add column if not exists reason_code text,
  add column if not exists reason_text text,
  add column if not exists job_snapshot jsonb not null default '{}'::jsonb,
  add column if not exists updated_at timestamptz not null default now();
```

同时修正 jobs 已迁到独立 PostgreSQL 后的跨库外键边界：

```sql
alter table job_actions
  drop constraint if exists job_actions_job_id_fkey;

delete from job_actions where job_id is null;

alter table job_actions
  alter column job_id set not null;
```

原因：

- `job_actions` 位于 Supabase；
- 权威 `jobs` 位于独立 PostgreSQL；
- PostgreSQL 不能跨数据库维护外键；
- 继续保留指向 Supabase 旧 jobs 表的 FK，会让香港 jobs 库中新岗位无法收藏、忽略或投递；
- 岗位存在性改由 action API 在写入前调用 `jobsByIds()` 校验；
- action API 从权威 jobs 行生成最小 `job_snapshot`：

```json
{
  "company": "公司",
  "title": "岗位",
  "location": "城市",
  "jd_url": "https://official.example/job/1"
}
```

- snapshot 只由服务端生成，不接受客户端上传；
- 岗位被清理后，历史 applied 行允许保留；展示页优先用 snapshot 显示“原岗位已下线”，而不是级联删除用户历史。

`reason_code` 允许：

```text
role_mismatch
location_mismatch
industry_mismatch
seniority_mismatch
education_mismatch
compensation_mismatch
company_not_interested
already_seen_elsewhere
not_job_seeking
other
```

约束：

- `reason_text` 最长 200 字；
- `reason_code` 为空或属于白名单；
- action 不是 `ignored` 时，API 必须把 reason 清空；
- 数据库不强制 reason 必填，兼容旧客户端；新 API 对 `ignored` 强制 reason。

不改变原有 action 枚举和 unique 约束。

### 5.3 `163_company_watch_requests.sql`

新增：

```sql
create table company_watch_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  company text not null,
  normalized_company text not null,
  status text not null default 'queued'
    check (status in ('covered', 'queued', 'researching', 'unsupported')),
  matched_source_ids uuid[] not null default '{}',
  resolution_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, normalized_company)
);
```

RLS：

- 用户只能读自己的请求；
- authenticated 不直接 insert / update / delete；
- `PUT /api/preferences` 完成鉴权后使用 service role 代写；
- `status`、`matched_source_ids`、`resolution_note` 只由 API 或管理员写；
- admin 可读全部；
- service role 可管理全部。

索引：

```sql
create index idx_company_watch_requests_status_created
  on company_watch_requests (status, created_at desc);
```

### 5.4 不修改 jobs 数据库

本次不新增：

- opportunity snapshot 表；
- embedding；
- recommendation cache 表；
- jobs 新列；
- source freshness 表。

理由：`first_seen_at`、`last_seen_at`、`status`、`summary`、`source_id` 已足够生成第一版机会队列。

### 5.5 `164_admin_radar_metrics.sql`

新增独立的消费侧统计 RPC，不回改 `159_admin_ops_dashboard.sql`：

```text
admin_radar_metrics(p_since interval default interval '7 days')
```

要求：

- `security definer`；
- 固定 `search_path=public`；
- revoke public / anon / authenticated；
- 只 grant service_role；
- 返回 §13.2 所列真实计数；
- 不返回用户邮箱、简历或逐用户明细；
- 不与供给侧 `admin_health_snapshot` 混写历史迁移。

---

## 6. Opportunity Engine

### 6.1 文件边界

新增目录：

```text
lib/opportunities/
  types.ts
  profile.ts
  freshness.ts
  eligibility.ts
  scoring.ts
  grouping.ts
  service.ts
```

职责：

- `profile.ts`：合并 `user_preferences` 与 `candidate_profiles`；
- `freshness.ts`：判断 source SLA 和岗位新鲜度；
- `eligibility.ts`：硬门；
- `scoring.ts`：内部排序分和展示原因；
- `grouping.ts`：分区、截断和去重；
- `service.ts`：编排读取、召回、打分和响应。

`lib/scoring.ts` 继续服务旧页面兼容和 `/jobs`，但 Today 改为 Opportunity Engine V2。完成迁移后可让公共辅助函数下沉复用，不在第一步强行重构。

### 6.2 合并后的 RadarProfile

`types.ts` 定义：

```ts
type RadarProfile = {
  userId: string;
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
};
```

合并优先级：

1. 用户手工保存的 `user_preferences` 为求职意图权威；
2. `candidate_profiles` 只补充 skills、education、seniority 和缺失字段；
3. 简历不得覆盖用户手工填写的目标城市、目标岗位、目标公司和排除词；
4. 全部数组去重；
5. `dailyLimit` clamp 到 5–30。

### 6.3 候选召回

新增：

- `lib/jobs-store/opportunities.ts`
- 函数 `recallOpportunityCandidates(profile, now, limit=4000)`

召回窗口：

- `status='active'`
- `last_seen_at >= now() - interval '7 days'`，先在数据库层排除显著陈旧数据；
- `summary` 非空且 trim 长度 ≥60；
- 不限制 `first_seen_at`：长期开放但最近仍被官方源确认的高匹配岗位仍有价值；
- 最多 4000 条，超过时按 `first_seen_at desc` 截断并记录 `candidate_capped=true`。

召回集合是以下查询的并集：

1. 目标职能和关键词的 FTS OR 查询；
2. 目标公司的 exact / normalized company 查询；
3. 目标城市 + 最近 7 天新增查询，用于防止 FTS 漏召跨语言标题。

规则：

- 至少有 role / keyword 时才运行 FTS；
- 目标公司查询最多 30 家；
- 城市查询最多 10 个城市；
- 所有结果按 `id` 去重；
- 不使用“最新岗位盲兜底”；
- jobs-store 异常时回退 Supabase jobs；两边返回形状一致；
- source metadata 从 Supabase 一次批量查询：

```text
source_id, company, adapter_name, crawl_method, last_checked_at, enabled
```

- 禁止逐岗位查询 source，必须批量 `.in('id', sourceIds)`。

### 6.4 Source freshness SLA

`freshness.ts` 只使用 job 和 source metadata，不访问网络。

规则：

| source 类型 | verified SLA | aging 上限 |
|---|---:|---:|
| `crawl_method='http'` | 18 小时 | 36 小时 |
| `crawl_method='playwright'` | 36 小时 | 72 小时 |
| `manual` 或未知 | 72 小时 | 144 小时 |

使用 `job.last_seen_at` 计算：

```ts
type FreshnessState = "verified" | "aging" | "stale" | "unknown";
```

- `age <= verified SLA` → `verified`
- `verified SLA < age <= aging 上限` → `aging`
- `age > aging 上限` → `stale`
- 无时间 → `unknown`

Today 主队列只允许 `verified`。

若整个 verified 队列少于 5：

- 允许额外展示最多 3 个 `aging` 岗位；
- 必须单独放在“等待再次确认”分区；
- 卡片明确显示“最近一次确认已超过常规更新周期”；
- `stale` 和 `unknown` 永不进入 Today；
- `/jobs` 仍可显示 aging / stale，并沿用现有警告。

### 6.5 硬门 Eligibility

按以下顺序执行，返回第一个拒绝原因：

1. `status !== active` → reject；
2. summary 有效长度 <60 → reject；
3. source metadata 明确存在且 `enabled=false` → reject；
4. freshness 为 stale / unknown → reject；
5. 命中 `excludeKeywords` → reject；
6. action 为 ignored / applied / saved → reject 主队列；
7. 用户有 target role / keyword：
   - exact 或 related 职能匹配 → pass；
   - 全不匹配 → reject；
8. 用户有 target location：
   - location 明确匹配 → pass；
   - location 缺失 → pass + degraded；
   - location 明确不匹配 → reject；
9. experience stage：
   - 岗位存在明确阶段且与用户阶段不符 → reject；
   - 阶段未知 → pass + degraded；
10. education：
    - 岗位明确要求高于用户最高学历 → reject；
    - 岗位学历未知 → pass + degraded；
11. industry：
    - 目标公司直接命中 → 不执行行业拒绝；
    - 公司行业已知且不在 targetIndustries → reject；
    - 行业未知 → pass + degraded。

必须复用现有：

- `keywordMatchTier`
- `recruitmentCategory`
- `hasExplicitRecruitmentType`
- `educationMatch`
- `jobIndustryAllowed`
- `normalizeChinaCity`

禁止复制一套近似规则。

### 6.6 Opportunity Score V2

内部排序分，最大 100：

| 信号 | 分值 |
|---|---:|
| 职能 exact | +35 |
| 职能 related | +22 |
| 目标公司命中 | +15 |
| 城市明确命中 | +15 |
| 城市未知 | +3 |
| 求职阶段明确匹配 | +10 |
| 求职阶段未知 | +3 |
| 行业明确匹配 | +10 |
| 行业未知 | +2 |
| 技能命中 | 每项 +3，最多 +15 |
| 24 小时内首次发现 | +10 |
| 24–72 小时首次发现 | +7 |
| 3–7 天首次发现 | +3 |
| summary ≥200 字且 freshness=verified | +5 |
| 已打开官网但未作决定 | -8 |
| 任一 degraded 条件 | 每项 -2，最低扣到 -8 |

最终：

```ts
score = clamp(rawScore, 0, 100)
```

展示档位：

```text
70–100  高匹配
45–69   相关机会
30–44   拓展机会
0–29    不展示
```

Today 主队列最低 45 分。

“拓展机会”只允许以下情况进入：

- related 职能；
- target company 命中；
- 其他硬门全部通过；
- 分数 30–44；
- 主队列不足 dailyLimit；
- 最多 5 条。

### 6.7 匹配原因

每个 Opportunity 必须返回：

```ts
type OpportunityReason =
  | { type: "role"; label: string }
  | { type: "location"; label: string }
  | { type: "company"; label: string }
  | { type: "stage"; label: string }
  | { type: "industry"; label: string }
  | { type: "skill"; label: string }
  | { type: "freshness"; label: string };
```

限制：

- 最多显示 4 条；
- 顺序：role → location → stage → industry → company → skill → freshness；
- 不显示“未知”作为正向理由；
- freshness 文案使用绝对可信表述，例如“今天首次发现”“今天确认仍在招”；
- 不显示内部 score 计算过程。

---

## 7. 今日机会 Feed

### 7.1 API

新增：

- `app/api/opportunities/route.ts`

`GET /api/opportunities`：

- 必须登录；
- 读取当前用户 profile、preferences、actions、radar state；
- 调用 `buildOpportunityFeed()`；
- 不在 GET 内更新 `last_opened_at`；
- 返回：

```json
{
  "ok": true,
  "generated_at": "2026-06-23T08:00:00Z",
  "profile_ready": true,
  "candidate_capped": false,
  "last_opened_at": "2026-06-22T08:00:00Z",
  "counts": {
    "new_since_last_open": 6,
    "high_match": 11,
    "verified": 20,
    "aging": 0
  },
  "sections": {
    "new": [],
    "priority": [],
    "explore": [],
    "aging": []
  }
}
```

`buildOpportunityFeed()` 接受可选参数：

```ts
type OpportunityFeedOptions = {
  now?: Date;
  noveltySinceOverride?: string | null;
  surface: "today" | "email";
};
```

- Today 不传 override，使用 `user_radar_state.last_opened_at`；
- Email 传入 `max(last_sent_at, last_opened_at)`；
- 测试必须注入固定 now，禁止在纯函数内部散落 `Date.now()`。

### 7.2 上次访问状态

新增：

- `app/api/radar/open/route.ts`

`POST /api/radar/open`：

- 必须登录；
- body：

```json
{
  "generated_at": "ISO timestamp",
  "feed_count": 20
}
```

- 校验 generated_at 不得晚于服务器当前时间 5 分钟以上；
- feed_count 0–30；
- upsert `user_radar_state`；
- `last_opened_at=now()`；
- `last_feed_generated_at=generated_at`；
- `last_feed_count=feed_count`；
- 返回 204。

调用时机：

- `TodayClient` 首次成功渲染 feed 后 fire-and-forget；
- SSR 读取到的是更新前的 `last_opened_at`；
- 因此“自上次访问新增”不会在当前请求中被提前清零；
- React Strict Mode 下必须用 ref 防止重复调用。

首次访问：

- `last_opened_at` 为空时，以 `now - 72 hours` 作为新岗位窗口；
- 不把全部历史岗位算作新岗位。

### 7.3 Feed 分区

严格按以下顺序：

#### A. 新出现

条件：

- `first_seen_at > effectiveLastOpenedAt`
- score ≥45
- freshness verified

排序：

1. score desc
2. first_seen_at desc

上限 10。

#### B. 高匹配待处理

条件：

- 不在 A；
- score ≥70；
- 无 saved / ignored / applied；
- freshness verified。

排序：

1. 未 viewed 优先；
2. score desc；
3. first_seen_at desc。

填充到 dailyLimit。

#### C. 可以拓展看看

条件见 §6.6，最多 5 条，仅当 A+B 未达到 dailyLimit。

#### D. 等待再次确认

仅当 verified 总数 <5 时出现，最多 3 条 aging 岗位，不计入主队列匹配承诺。

全 Feed 去重，最终主队列 A+B+C 不超过 `dailyLimit`。

### 7.4 Today UI

修改：

- `app/today/page.tsx`
- `app/today-client.tsx`

Hero：

- eyebrow：`今日机会`
- title：`今天值得处理的官方岗位`
- description：`系统已按你的目标、简历和岗位新鲜度完成筛选。先处理最相关的，再决定是否扩大搜索。`

指标只保留：

1. `自上次查看新增`
2. `高匹配待处理`
3. `今天确认仍在招`

移除 Hero 中的：

- 已收藏；
- 已投递；
- 已忽略。

这些是历史状态，不是今日队列质量指标。

分区标题和空状态必须使用 §7.3 的固定文案。

Today 不再显示：

- crawler；
- 刷新按钮；
- 发掘按钮；
- 抓取数量；
- source 数量；
- workflow 状态。

### 7.5 JobCard 在 Today 的差异

`JobCard` 新增可选 prop：

```ts
variant?: "library" | "opportunity";
opportunityReasons?: OpportunityReason[];
freshnessState?: FreshnessState;
```

`variant='opportunity'` 时：

- 顶部显示“高匹配 / 相关机会 / 拓展机会”；
- 显示最多 4 个匹配原因；
- 显示“首次发现”和“最近确认在招”；
- 主按钮：`查看官网`
- 决策按钮：
  - `值得投`
  - `不适合`
  - `已投递`
- 原“收藏”文案改为“值得投”，底层 action 仍为 `saved`；
- 职业洞察按钮保留但降为次级；
- 不展示内部数值 score。

`variant='library'` 保持岗位库原行为，避免一次性改坏全部页面。

### 7.6 值得投与已投递页面

修改：

- `app/saved/page.tsx`
- `app/saved/saved-client.tsx`
- `app/applied/page.tsx`

要求：

- `/saved` eyebrow 和导航统一改为“值得投”；
- saved action 的底层值保持 `saved`；
- `/applied` 先从权威 jobs 库按 id 取岗位；
- 若岗位已被物理清理，使用 `job_actions.job_snapshot` 渲染公司、岗位、地点；
- 已清理岗位显示“原岗位已下线”，不提供失效官网链接；
- 不因为 jobs 行不存在而丢失投递历史。

---

## 8. 机会处理与负反馈

### 8.1 API 化

新增：

```text
app/api/job-actions/[jobId]/route.ts
app/api/job-actions/[jobId]/view/route.ts
```

停止 `JobCard` 直接操作 Supabase。

#### `PUT /api/job-actions/[jobId]`

请求：

```json
{
  "action": "saved",
  "reason_code": null,
  "reason_text": null
}
```

或取消：

```json
{
  "action": null
}
```

规则：

- jobId 必须是 UUID；
- 必须登录；
- `action` 只允许 saved / ignored / applied / null；
- ignored 必须有 reason_code；
- reason_code=other 时允许 reason_text，最长 200；
- 其他 action 强制清空 reason；
- 一次事务语义：
  1. 删除当前用户该 job 的 saved / ignored / applied；
  2. action 非空则 insert；
  3. viewed 记录不删除；
- 响应返回最终 action；
- 失败不得保留半状态。

Supabase REST 无多语句事务时，新增 `security definer` RPC：

```text
set_job_primary_action(
  p_job_id uuid,
  p_action text,
  p_reason_code text,
  p_reason_text text,
  p_job_snapshot jsonb
)
```

RPC 内使用 `auth.uid()`，不得接受 user_id。只 grant authenticated。

API 调用 RPC 前必须：

1. action 非空时，用 `jobsByIds([jobId], false)` 查询权威 jobs 库；
2. action 非空且查不到时返回 `404 job_not_found`；
3. action=null 时允许直接删除历史 primary action，即使岗位已被物理清理；
4. 不用 Supabase 旧 jobs 表验证存在性；
5. 用查询结果构建白名单 snapshot，忽略客户端可能传入的同名字段；
6. 不因岗位当前 expired 而禁止取消历史 applied，但新建 saved / ignored / applied 时岗位必须存在。

#### `POST /api/job-actions/[jobId]/view`

- upsert viewed；
- 不改变 primary action；
- 返回 204；
- 打开官网不能被该 API 失败阻塞。

### 8.2 “不适合”交互

点击“不适合”后打开轻量原因面板，必须选择一个：

- 岗位方向不对
- 城市不合适
- 行业不合适
- 经验级别不合适
- 学历要求不合适
- 薪资不合适
- 对这家公司没兴趣
- 已在别处看过
- 暂时不找工作
- 其他

映射到 §5.2 reason code。

关闭面板不写入。

写入成功后：

- 岗位立即从 Today 移除；
- 显示可撤销 toast 5 秒；
- 撤销调用 action=null；
- 发送 `opportunity_feedback` 事件：

```json
{
  "action": "ignored",
  "reason_code": "role_mismatch",
  "surface": "today"
}
```

不得在事件 payload 中写 title、resume、email 或 reason_text。

### 8.3 反馈在 V1 的用途

V1 只用于：

- 当前岗位隐藏；
- 统计匹配错误类型；
- 人工调优规则；
- 判断用户价值。

V1 不允许：

- 自动把 reason 写入 exclude keywords；
- 自动删除目标城市或行业；
- 根据单次反馈训练模型；
- 根据“薪资不合适”推断薪资底线。

---

## 9. 搜索岗位页改造

### 9.1 页面定位

`/jobs` 改为：

> 当用户希望主动探索、扩大条件或查看完整岗位库时使用的搜索工具。

修改 Hero：

- eyebrow：`搜索岗位`
- title：`探索完整官方岗位库`
- description：`按公司、城市、岗位方向和条件主动搜索。每日推荐请回到“今日机会”。`

### 9.2 移除三入口

修改 `app/jobs/jobs-client.tsx`：

删除默认展示的 ActionTile 区域：

- 查已有岗位；
- 刷新对口公司；
- 发掘新公司。

搜索由筛选变化自动执行，保留明确的“搜索”按钮可手动重试，但不再宣传“不联网 / 联网 / 约 1–5 分钟”。

删除或停用 UI 状态：

- `activeSearch`
- `existingBusy`
- `pendingLocalResult`
- `RetrievalDoneBanner` 的 local 用途

`useDiscoveryPoll` 和相关组件暂不删除，避免破坏后台能力；普通 JobsClient 不再调用。

### 9.3 手动爬取 feature flag

新增 `lib/product-flags.ts`：

```ts
export const MANUAL_CRAWL_UI_ENABLED =
  process.env.NEXT_PUBLIC_MANUAL_CRAWL_UI === "true";
```

默认 false。

仅为故障回滚保留：

- true 时，在 `/jobs` 页面底部的“高级工具”折叠区恢复原 refresh / discovery；
- false 时不渲染相关按钮和说明；
- Landing、Today 和主导航永远不引用该能力。

### 9.4 搜索结果

- 保留全部现有筛选；
- 默认排序继续按匹配度；
- 保留“仅新岗位”和 freshness 标签；
- 搜索结果卡使用 `variant='library'`；
- 搜索空状态新增入口：
  - `调整筛选`
  - `添加关注公司`
- 不引导用户发起 Web Search。

---

## 10. 关注公司与覆盖请求

### 10.1 用户体验

在 `/preferences` 中将“关注公司”单独做成一块：

- 用户输入公司名；
- 保存后立即出现状态；
- 不等待抓取。

状态文案：

| status | 用户文案 |
|---|---|
| covered | 已纳入持续监控 |
| queued | 已记录，等待接入官方招聘源 |
| researching | 正在确认官方招聘入口 |
| unsupported | 暂时无法稳定监控 |

不显示：

- adapter 名；
- parser 状态；
- source URL；
- GitHub Actions；
- 抓取失败堆栈。

### 10.2 公司归一

新增 `lib/company-normalize.ts`：

- Unicode NFKC；
- trim；
- lower case；
- 移除连续空白；
- 移除常见公司尾缀：
  - 有限公司
  - 股份有限公司
  - 集团
  - 控股
  - 中国
  - China
- 不做模糊编辑距离自动合并；
- 原始 display name 保留；
- 归一值只用于 exact coverage 对比。

### 10.3 覆盖同步

`PUT /api/preferences` 保存后：

1. 批量读取 enabled sources 的 `company`；
2. 按 normalized company 建 map；
3. 对每个 target company：
   - 命中 source → upsert covered + source IDs；
   - 未命中 → upsert queued；
4. 删除当前用户已不再 target 的 request；
5. 返回 coverage。

不得在用户请求内调用 Qianfan、Playwright 或 GitHub workflow。

### 10.4 管理员处理

修改：

- `app/sources/page.tsx`
- `components/SourceManager.tsx`

新增“用户希望监控的公司”区块：

- 按 normalized_company 聚合请求人数；
- queued 优先；
- 显示首次请求和最近请求时间；
- 管理员可：
  - 标记 researching；
  - 关联已有 source 并标 covered；
  - 标 unsupported 并填写人话说明；
  - 进入现有 AddSourceForm。

管理员处理后批量更新同 normalized_company 的用户请求。

动态 source discovery 可由管理员另行触发，但不是本 Spec 的用户流程。

---

## 11. 每日邮件摘要

### 11.1 范围

邮件摘要是转型后的主动触达能力，必须实现为用户主动开启的可选项。

默认：

- `email_digest_enabled=false`
- frequency=daily
- send_hour=8
- timezone=Asia/Shanghai

当前只支持用户 auth email，不新增手机号、微信或短信。

### 11.2 设置 UI

在 `/preferences` 增加“机会提醒”：

- 开关：每天把新机会发到登录邮箱；
- 频率：每天 / 仅工作日；
- 发送小时：0–23，UI 只提供 7、8、9、12、18、20；
- 时区首版固定显示 Asia/Shanghai，不开放自由输入；
- 保存走：
  - `GET /api/notification-settings`
  - `PUT /api/notification-settings`

### 11.3 发送架构

新增：

```text
app/api/internal/opportunity-digest/route.ts
.github/workflows/opportunity-digest.yml
lib/opportunities/email.ts
```

GitHub Actions：

- 每小时第 15 分钟运行；
- POST `${APP_URL}/api/internal/opportunity-digest`；
- Header `Authorization: Bearer ${INTERNAL_CRON_SECRET}`；
- 不在 workflow 中读取用户数据或拼邮件。

内部 API：

- 校验固定时序 secret，使用 timing-safe compare；
- 找到当前本地小时到期且 enabled 的用户；
- 单次最多处理 100 人；
- 仅给 profile_ready 用户发送；
- 通过 Supabase Admin Auth `getUserById` 获取已验证邮箱，最多 5 并发；邮箱不存在或未验证则跳过；
- 调用同一个 `buildOpportunityFeed()`，`noveltySinceOverride=max(last_sent_at,last_opened_at)`；
- 邮件只包含 A 区“新出现”前 5 条；
- 没有新机会则不发送，也不更新 `last_sent_at`；
- 成功发送后更新 `last_sent_at`；
- 单用户失败不阻塞其他用户；
- 返回匿名汇总：eligible / sent / skipped / failed。

邮件发送：

- 使用 Resend HTTP API，直接 `fetch`，不安装 SDK；
- 环境变量：
  - `RESEND_API_KEY`
  - `EMAIL_FROM`
  - `APP_URL`
  - `INTERNAL_CRON_SECRET`
- 任一缺失时任务 fail-fast 并写 ops log；
- 不使用 tracking pixel；
- 邮件链接只指向 `/today?source=email_digest`，不在邮件中直接暴露用户简历或详细画像；
- Footer 包含 `/preferences#notifications` 关闭入口。

事件：

- `opportunity_digest_sent`：仅 user_id、count、frequency；
- `opportunity_digest_open`：用户从带 source 参数的 `/today` 打开时记录；
- 不记录邮件打开像素。

---

## 12. Landing 与产品文案

修改 `app/landing-client.tsx`。

Hero 固定文案：

```text
eyebrow：个人机会雷达 · 持续更新
title：每天替你看官网，只留下值得行动的机会。
description：
设置一次目标，系统持续监控企业官方招聘页，
过滤失效和不相关岗位，告诉你今天真正值得看的机会。
```

主 CTA：

- 未登录：`开始设置我的雷达`
- 已登录：`查看今日机会`

四个价值点改为：

1. 企业官网直达
2. 持续确认仍在招
3. 按你的目标筛选
4. 每天只给少量机会

Landing 不再以以下内容作为主卖点：

- 800+ source 数；
- crawler 能力；
- 发掘新公司；
- AI 自动化；
- 职业洞察的维度数量。

可以保留职业洞察为次级“帮助判断”区块，但顺序必须在核心机会雷达之后。

---

## 13. 埋点与指标

### 13.1 新事件

所有事件继续走 `/api/events`，payload 必须通过现有大小限制和 PII 安全规则。

| event | 触发 | payload |
|---|---|---|
| `radar_open` | Today 成功渲染 | counts、source |
| `radar_onboarding_required` | 画像不足 | missing_roles、missing_locations |
| `opportunity_click` | Today 打开官网 | job_id、tier、surface |
| `opportunity_feedback` | saved / ignored / applied | action、reason_code、tier、surface |
| `opportunity_undo` | 撤销动作 | previous_action、surface |
| `company_watch_added` | 新增关注公司 | coverage_status |
| `company_watch_removed` | 删除关注公司 | previous_status |
| `opportunity_digest_enabled` | 开启摘要 | frequency、send_hour |
| `opportunity_digest_disabled` | 关闭摘要 | 无 |
| `opportunity_digest_sent` | 服务端发送成功 | count、frequency |
| `opportunity_digest_open` | 邮件入口访问 | 无 |

禁止 payload：

- email；
- resume text；
- reason_text；
- title；
- company 名；
- jd_url；
- skills 数组。

### 13.2 Admin 指标

调用 `164_admin_radar_metrics.sql` 新增的独立 service-role-only RPC：

消费侧展示：

- 今日 radar_open 用户数；
- profile_ready 用户数；
- Today 交付岗位总数；
- 高匹配占比；
- 官网点击数；
- 值得投数；
- 不适合数；
- 已投递数；
- 不适合原因 Top 5；
- digest enabled 用户数；
- digest sent 数；
- company watch queued 公司数。

不得用估算或占位代替真实值。

### 13.3 核心漏斗

管理员页面按用户去重显示：

```text
注册
→ profile_ready
→ radar_open
→ opportunity_click / saved / ignored
→ applied
```

这是转型后的主要产品漏斗。刷新和 discovery 次数继续属于运维指标，不属于产品漏斗。

---

## 14. 错误与降级

### 14.1 jobs 数据库不可用

- `/today` 显示明确错误页，不用 Supabase 空 jobs 假装成功；
- 若 Supabase 仍保留 jobs fallback 且有真实数据，可回退；
- 错误文案：`机会队列暂时无法更新，请稍后重试。你的偏好和历史操作没有丢失。`

### 14.2 source metadata 查询失败

- 可以继续基于 `last_seen_at` 用 unknown crawl method 的 72h SLA；
- 记录服务端 warning；
- 不让页面 500。

### 14.3 机会不足

- 不用无关岗位填满；
- 显示实际数量；
- 空状态提供：
  - 调整目标；
  - 搜索完整岗位库；
  - 添加关注公司。

### 14.4 反馈保存失败

- 客户端乐观更新必须回滚；
- toast：`操作失败，已恢复原状态`;
- 不吞掉失败；
- 官网跳转不受 view 埋点失败影响。

### 14.5 邮件失败

- 单用户失败不更新 last_sent_at；
- 不自动无限重试；
- 下一小时任务可重新命中；
- 同一 feed generated_at 需避免 24h 内重复发送：
  - 查询 `last_sent_at`；
  - daily 至少间隔 20 小时；
  - weekdays 周末跳过。

---

## 15. 安全与隐私

1. 所有用户 API 使用 `requireUser` 或用户上下文 Supabase；
2. service-role 查询后必须显式校验 user ownership；
3. `set_job_primary_action` 使用 `auth.uid()`，不接受 user_id；
4. internal digest endpoint 只接受服务器 secret；
5. reason_text 不进入 events；
6. 邮件不包含简历原文、联系方式或完整用户画像；
7. 用户关注公司属于个人求职偏好，只对本人和管理员可见；
8. 管理员聚合请求人数时不显示具体用户邮箱；
9. 不新增第三方分析 SDK；
10. 不新增自动投递、验证码绕过或登录态抓取。

---

## 16. 文件级改动清单

### 新增

```text
app/api/opportunities/route.ts
app/api/radar/open/route.ts
app/api/preferences/route.ts
app/api/job-actions/[jobId]/route.ts
app/api/job-actions/[jobId]/view/route.ts
app/api/notification-settings/route.ts
app/api/internal/opportunity-digest/route.ts
lib/opportunities/types.ts
lib/opportunities/profile.ts
lib/opportunities/freshness.ts
lib/opportunities/eligibility.ts
lib/opportunities/scoring.ts
lib/opportunities/grouping.ts
lib/opportunities/service.ts
lib/opportunities/email.ts
lib/jobs-store/opportunities.ts
lib/company-normalize.ts
lib/product-flags.ts
.github/workflows/opportunity-digest.yml
supabase/migrations/161_radar_state_and_notification_settings.sql
supabase/migrations/162_job_action_feedback.sql
supabase/migrations/163_company_watch_requests.sql
supabase/migrations/164_admin_radar_metrics.sql
tests/opportunity-profile.test.js
tests/opportunity-freshness.test.js
tests/opportunity-eligibility.test.js
tests/opportunity-scoring.test.js
tests/opportunity-grouping.test.js
tests/company-normalize.test.js
tests/opportunity-api-security.test.js
```

### 修改

```text
app/today/page.tsx
app/today-client.tsx
app/jobs/page.tsx
app/jobs/jobs-client.tsx
app/preferences/page.tsx
app/landing-client.tsx
app/sources/page.tsx
app/saved/page.tsx
app/saved/saved-client.tsx
app/applied/page.tsx
components/Navbar.tsx
components/JobCard.tsx
components/PreferenceForm.tsx
components/SourceManager.tsx
lib/types.ts
lib/i18n.ts
lib/track.ts
lib/admin-health.ts
tests/admin-health.test.js
tests/track.test.js
tests/api-security.test.js
```

注意：

- 不要修改 unrelated crawler adapters；
- 不要删除 `hooks/useDiscoveryPoll.ts`；
- 不要删除 `/api/refresh` 或 `/api/discovery/*`；
- 不要修改 jobs-db schema；
- 不要覆盖用户现有未提交文件。

---

## 17. 实施顺序

这是依赖顺序，不是时间计划。

### Workstream A：纯函数与数据模型

1. migrations 161–164；
2. opportunities types/profile/freshness/eligibility/scoring/grouping；
3. 纯函数测试；
4. jobs-store candidate recall。

### Workstream B：Today Feed

1. opportunities service；
2. `/api/opportunities`；
3. radar state；
4. Today SSR / client；
5. opportunity variant JobCard。

### Workstream C：动作闭环

1. action RPC / API；
2. ignored reason UI；
3. optimistic rollback；
4. events。

### Workstream D：信息架构

1. Navbar；
2. Jobs 页面降级主动爬取；
3. Landing 文案；
4. Preferences 重组。

### Workstream E：关注公司

1. company normalization；
2. preferences API sync；
3. coverage status UI；
4. admin queue。

### Workstream F：摘要与指标

1. notification settings；
2. email renderer；
3. internal digest；
4. workflow；
5. admin funnel。

每个 Workstream 完成后都必须能独立通过测试，不允许最后一次性补测试。

---

## 18. 测试规格

### 18.1 Opportunity profile

必须覆盖：

- 手工偏好优先于简历；
- 简历补 skills；
- target industries 合并；
- highest education 正确；
- daily limit clamp；
- profile_ready 判断；
- 空数组与历史 null。

### 18.2 Freshness

固定时间测试：

- http 17h verified；
- http 19h aging；
- http 37h stale；
- playwright 35h verified；
- playwright 40h aging；
- playwright 73h stale；
- manual 70h verified；
- null unknown。

### 18.3 Eligibility

必须覆盖：

- inactive reject；
- summary 过短 reject；
- stale reject；
- exclude keyword reject；
- saved / ignored / applied reject；
- viewed 不 reject；
- role exact / related；
- role mismatch reject；
- location unknown degrade；
- location mismatch reject；
- stage mismatch reject；
- education mismatch reject；
- target company 绕过 industry mismatch；
- unknown industry degrade。

### 18.4 Scoring

必须使用固定 now：

- exact role 分高于 related；
- target company 加分；
- skill 最多 15；
- freshness 分段；
- viewed -8；
- degraded 最多 -8；
- clamp 0–100；
- tier 边界 29/30/44/45/69/70/100。

### 18.5 Grouping

- new section 上限 10；
- priority 填充 dailyLimit；
- explore 最多 5；
- 主队列不超过 dailyLimit；
- aging 最多 3 且只在 verified<5；
- 多 section 不重复；
- 首次访问窗口 72h；
- last_opened_at 后新增计算正确；
- 不用低分岗位填满。

### 18.6 API 安全

- 未登录 opportunities 401；
- 未登录 radar/open 401；
- 用户不能改别人 action；
- action jobId 非法 400；
- ignored 无 reason 400；
- reason_text 超长 400；
- internal digest secret 错误 401；
- company watch 不能读别人请求；
- notification settings 不能写 user_id。

### 18.7 UI 验收

桌面和移动端：

- 新用户 Today 只出现 onboarding；
- 完整画像显示分区；
- Today 无刷新 / 发掘入口；
- Jobs 默认无三块技术操作；
- “不适合”必须选原因；
- 撤销恢复岗位；
- 值得投后从 Today 消失并进入 `/saved`；
- 已投递后进入 `/applied`；
- 关注未覆盖公司显示 queued；
- 导航在移动端不溢出；
- 深色模式可读；
- keyboard focus 可见；
- reduced motion 不影响功能。

---

## 19. 回归门

实施完成必须完整执行：

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npm run build
bash scripts/check-migrations.sh
git diff --check
```

不将 `npm run lint` 计为有效门，除非本次同时完成非交互 ESLint 配置；本 Spec 不要求处理 ESLint。

生产只读验收：

1. `/api/opportunities` 返回的 job 全部 active；
2. Today job summary 有效长度全部 ≥60；
3. Today 无 canonical duplicate；
4. Today 无 saved / ignored / applied；
5. freshness state 与 last_seen_at / source method 一致；
6. 用户 A 的反馈不影响用户 B；
7. company watch request 归属正确；
8. digest disabled 用户绝不发送；
9. admin 指标与原始表 exact count 一致。

---

## 20. 验收场景

### 场景 1：产品经理，上海，互联网

偏好：

- target role：产品经理；
- city：上海；
- industry：互联网；
- stage：社招。

要求：

- 机械、医药产品岗位不进入；
- 上海英文 Product Manager 可进入；
- location 缺失但其他强匹配可降级；
- 明确北京岗位拒绝；
- Today 展示具体原因。

### 场景 2：用户关注未覆盖公司

- 用户添加“示例新公司”；
- 保存立即成功；
- coverage=queued；
- 不触发浏览器；
- admin 可看到聚合请求；
- 关联 source 后用户状态变 covered；
- 下一轮候选召回可使用该公司岗位。

### 场景 3：忽略原因

- 用户点“不适合”；
- 未选原因不能提交；
- 选择“岗位方向不对”后岗位移出；
- job_actions 写 ignored + role_mismatch；
- events 不含 reason_text；
- 5 秒内撤销恢复；
- 用户 B 不受影响。

### 场景 4：新鲜度不足

- http 岗位 last_seen 40h；
- 不进入主队列；
- 若 verified 少于 5，也不能进入 aging，因为超过 36h；
- 在 `/jobs` 中仍可展示并显示风险；
- 后台刷新确认后 last_seen 更新，下一次可重新进入。

### 场景 5：邮件摘要

- 用户默认不接收；
- 用户主动开启每天 8 点；
- 当地 8 点且存在新机会时发 1 封；
- 无新机会不发；
- 20h 内不重复；
- 关闭后下次任务不再命中；
- 邮件不含简历和联系方式。

---

## 21. 完成定义

只有同时满足以下条件，才可宣布转型实现完成：

1. 登录用户默认进入“今日机会”；
2. Today 不再依赖用户主动爬取；
3. Today 的每个岗位通过质量、相关性和 freshness 准入；
4. 队列有稳定分区和不超过 30 的上限；
5. 用户可以完成值得投 / 不适合 / 已投递；
6. 不适合原因有结构化数据；
7. 未覆盖公司形成异步接入请求；
8. Jobs 页面不再平铺三条技术链路；
9. 手动刷新和 discovery 后台能力未删除；
10. 所有新 API 有 ownership / auth 测试；
11. 回归门全部通过；
12. 管理员可从真实数据查看转型漏斗；
13. 文案不承诺全市场覆盖、自动投递或保证面试；
14. 没有 mock 数据、假计数或“pending 即成功”。

本 Spec 到此封口。实现 Agent 如需改变产品规则，必须先回到用户确认，不得在开发过程中自行扩大范围。
