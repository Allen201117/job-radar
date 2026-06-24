# Agent Implementation Prompt：个人机会时效雷达

> 用途：把本文件完整粘给实现 agent。  
> 目标：让 agent 基于新版核心价值实现产品和技术改造，不再沿用旧的“岗位库 / 主动爬取”叙事。  
> 日期：2026-06-24

---

## 你的任务

你是实现 agent。请基于新版定位，把求职雷达从“岗位聚合/主动爬取工具”改造成“个人机会时效雷达”。

新版核心定位：

> 当与你有关的求职机会发生时效变化时，职达告诉你：发生了什么、为什么与你有关、为什么现在值得行动。

你必须先阅读以下文档，并以它们为权威：

1. `docs/opportunity-timing-radar-specs/产品转型方案-个人机会时效雷达.md`
2. `docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-product-spec.md`
3. `docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-technical-spec.md`
4. `docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-acceptance-spec.md`

旧文档只能作为背景，不得覆盖 2026-06-24 新文档。

---

## 最高优先级原则

必须做：

- 三种用户模式：`sprint / watch / campus`；
- 五类用户侧信号：`NEW_MATCH / STILL_OPEN_PRIORITY / DEADLINE_SOON / COMPANY_MOMENTUM / CLOSED_OR_STALE`；
- Today 每张卡片至少有一个 signal；
- 用户能理解“为什么现在”；
- 官方链接和最近确认时间是证据；
- ignored 必须收集 reason_code；
- 普通用户主动爬岗位入口降级；
- feed 不足时宁缺毋滥；
- 所有用户相关写入都走鉴权 API，不接受客户端 user_id；
- 测试覆盖核心规则。

禁止做：

- 不要展示岗位内容变更；
- 不要宣传重新开放；
- 不要宣传全网最快、竞品没有；
- 不要做自动投递；
- 不要引入向量库、Redis、队列、LLM 排名；
- 不要新增 crawler adapter；
- 不要把 source/crawler/workflow 暴露给普通用户；
- 不要用 mock feed 假装成功；
- 不要为了填满 Today 混入无关岗位；
- 不要改坏 `expired` sticky 和 summary preserve-if-empty 语义。

---

## 建议执行顺序

### Step 0：审当前分支状态

先执行：

```bash
git status --short
git branch --show-current
rg --files docs/superpowers/specs | sort | tail -40
rg -n "lib/opportunities|Opportunity|radar_mode|user_radar_state|company_watch_requests|job_action" app lib supabase tests crawler jobs-db
```

判断当前分支是否已经包含 6/23 pivot 产物：

- `lib/opportunities/*`
- `app/api/opportunities/route.ts`
- `app/api/preferences/route.ts`
- `app/api/radar/open/route.ts`
- `app/api/job-actions/[jobId]/route.ts`
- migrations `161/162/163`

如果已有，不要重写，按新版 spec 扩展。

如果没有，先按 6/24 spec 建立最小模块，不要照搬旧 Today 逻辑。

---

## Step 1：数据模型

### 1.1 添加 radar_mode

新增 Supabase migration：

```text
164_user_preferences_radar_mode.sql
```

内容：

- `user_preferences.radar_mode text not null default 'sprint'`
- check in `sprint/watch/campus`
- `radar_mode_confirmed_at timestamptz`

要求：

- migration 幂等；
- 不回改旧 migration；
- RLS 不放宽。

### 1.2 添加 delivery ledger

新增 Supabase migration：

```text
165_user_opportunity_deliveries.sql
```

表：

```text
user_opportunity_deliveries
```

字段按 technical spec §3.2。

要求：

- unique `(user_id, delivery_key, surface)`；
- 用户只读自己；
- 客户端不能直接 insert/update/delete；
- API service role 写入。

### 1.3 事件台账

如果本轮时间允许，做 Phase D：

- jobs DB 增加 `job_events`；
- crawler/jobs_db.py 和 lib/jobs-store/write.ts 写事件。

如果不做，必须在交付说明中明确：

```text
Phase D 未执行，V1 用户侧不依赖 job_events；内容变更不展示。
```

---

## Step 2：类型与 Opportunity Engine

修改或新增：

```text
lib/opportunities/types.ts
lib/opportunities/profile.ts
lib/opportunities/mode-config.ts
lib/opportunities/deadline.ts
lib/opportunities/signals.ts
lib/opportunities/momentum.ts
lib/opportunities/eligibility.ts
lib/opportunities/scoring.ts
lib/opportunities/grouping.ts
lib/opportunities/service.ts
```

### 2.1 类型

增加：

```ts
RadarMode = "sprint" | "watch" | "campus"
OpportunitySignalType =
  | "NEW_MATCH"
  | "STILL_OPEN_PRIORITY"
  | "DEADLINE_SOON"
  | "COMPANY_MOMENTUM"
  | "CLOSED_OR_STALE"
```

Opportunity 必须包含：

```text
signals
deadlineAt
mode
```

Feed 必须包含：

```text
mode
counts.by_signal
sections[]
```

### 2.2 Profile readiness

按 technical spec §4.2 实现：

- sprint: content + location；
- watch: content；
- campus: stage in 校招/实习 + content。

### 2.3 Deadline

实现 `parseDeadline`：

支持：

- ISO；
- slash；
- dot；
- 中文年月日；
- month-day 年份推断。

不支持：

- 长期有效；
- 招满即止；
- 尽快；
- 无法判断的多个日期。

### 2.4 Signals

实现 `deriveOpportunitySignals`。

规则：

- `NEW_MATCH` 必须 verified；
- `STILL_OPEN_PRIORITY` 必须 verified；
- `DEADLINE_SOON` 必须可解析日期；
- `CLOSED_OR_STALE` 只对 saved/viewed/target company/已 delivery；
- `COMPANY_MOMENTUM` 公司级生成。

禁止：

- content_hash 改变映射用户 signal。

### 2.5 Momentum

实现：

- 近 14 天 vs 前 14 天；
- recent >= 3 且 recent >= previous + 2；
- 或 previous < 3 且 recent >= 5；
- 代表岗位 >= 2；
- verified ratio >= 50%；
- 同一用户同一公司 7 天去重。

### 2.6 Grouping

按 mode 分区：

#### sprint

1. deadline
2. new_matches
3. priority
4. explore
5. awaiting_confirmation

#### watch

1. company_momentum
2. new_matches
3. saved_status_changes

#### campus

1. deadline
2. new_matches
3. priority
4. company_momentum

要求：

- 一个岗位只出现一次；
- deadline 优先于 new；
- saved/ignored/applied 不进主推荐；
- 不用无关岗位填满。

---

## Step 3：API

### 3.1 `/api/preferences`

必须：

- GET 返回 radar_mode、profile_ready、profile_ready_missing、coverage、notification_settings；
- PUT 保存 radar_mode；
- PUT 保存 target_companies 时同步 company_watch_requests；
- 不接受 user_id；
- daily_limit 按 mode clamp；
- 所有数组 trim/去空/去重/限长。

错误契约：

- 所有失败响应必须是 `{ ok:false, error:{ code, message, fields? } }`；
- body 带 `user_id` 返回 400 `validation_failed`；
- 非法 mode 返回 400 `validation_failed`；
- 未登录返回 401 `unauthorized`；
- Supabase 失败返回 503，不要吞错后假成功。

### 3.2 `/api/opportunities`

必须：

- 返回新版 feed；
- profile not ready 返回空 sections；
- 每个 opportunity 有 signals；
- GET 不更新 last_opened_at；
- 生成 delivery ledger，幂等；
- feed 失败返回 503，不返回 mock。

假成功防线：

- profile 不 ready 返回空 feed，不返回最新岗位兜底；
- jobs store 或 engine 抛错时返回 503 `feed_unavailable`；
- 如果 delivery ledger 写入失败，本次 feed 也返回 503；
- 每个 opportunity 的 `job.id` 必须能从权威 jobs 库读回；
- 每个 opportunity 的 `signals.length >= 1`。

### 3.3 `/api/radar/open`

必须：

- 更新 `user_radar_state.last_opened_at`；
- 写 radar_feed_opened event；
- 不接受 user_id；
- 不创建 job action。

### 3.4 `/api/job-actions/[jobId]`

必须：

- saved/ignored/applied 主动作互斥；
- ignored 无 reason_code 返回 400；
- 服务端校验 job 存在；
- 服务端生成 job_snapshot；
- saved/applied 清空 reason；
- action 失败前端不得永久改变。

错误契约：

- ignored 无 reason_code 返回 400 `validation_failed`；
- job 不存在返回 404 `job_not_found`；
- 客户端传 `job_snapshot` 或 `user_id` 返回 400；
- 写入失败返回 503；
- 不得先写 UI 成功再忽略 API 失败。

---

## Step 4：UI

### 4.1 Landing

改为新版叙事：

```text
别每天刷岗位了。
职达替你看企业官网，只提醒真实、对口、仍有效、现在值得处理的机会。
```

必须突出：

- 官方源；
- 新机会；
- 仍在招；
- 快截止；
- 低噪音；
- 为什么现在。

不得突出：

- crawler；
- 主动爬；
- 岗位内容变更；
- 全网最全；
- 自动投递。

### 4.2 Today

必须：

- 登录后默认核心页；
- 显示当前 mode；
- 按 mode 展示 sections；
- 每张卡片展示 signal label；
- 展示官方链接；
- 展示最近确认时间或降级状态；
- 展示 2–4 条推荐原因；
- 支持 saved/ignored/applied；
- ignored 弹 reason 选择。

不得：

- 展示内部 score；
- 展示 crawler/source/workflow；
- 无 profile 展示随机岗位；
- 用无关岗位填满。

### 4.3 Preferences

必须：

- mode 选择；
- mode 说明；
- 目标岗位/关键词/城市/公司/行业/阶段/学历；
- 每日上限；
- 通知设置；
- company coverage 状态。

保存必须走 API，不要客户端直接写 Supabase。

### 4.4 Jobs

普通用户默认隐藏主动爬取入口。

保留：

- 搜索；
- 筛选；
- 保存；
- 官方链接；
- 新鲜度提示。

管理员或 feature flag 可见 refresh/discovery，但不要作为主产品入口。

---

## Step 5：测试

必须新增或更新测试：

```text
tests/opportunity-mode.test.js
tests/opportunity-signals.test.js
tests/opportunity-deadline.test.js
tests/opportunity-momentum.test.js
tests/opportunity-grouping.test.js
tests/opportunity-delivery.test.js
```

如果做 job_events：

```text
crawler/test_jobs_db_events.py
```

测试必须覆盖：

- 三种 profile readiness；
- mode daily limit clamp；
- NEW_MATCH 需要 verified；
- STILL_OPEN 不接受 unknown；
- DEADLINE_SOON 只在可解析日期时触发；
- campus 14 天 deadline；
- watch 不展示普通 related；
- company momentum 阈值；
- content_hash change 不进入用户 signal；
- delivery_key 去重；
- ignored 无 reason 返回 400；
- saved/ignored/applied 不进主推荐；
- 普通用户不显示主动爬取入口。
- jobs store 故障时 opportunities 返回 503；
- API 返回 opportunity 后 delivery 表能读回；
- 第二次生成同一 feed 不重复写 delivery；
- action API 失败时前端回滚；
- job.id 必须来自真实 jobs 库，不能是 mock 常量。

---

## Step 6：必跑验证

运行：

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

如果某条无法运行，必须写明：

- 原因；
- 是否与本改动有关；
- 已经用什么替代验证。

不要把未运行写成通过。

---

## Step 7：最终交付说明

交付时必须写清：

1. 实现了哪些文件；
2. 三种模式如何生效；
3. 五类 signal 哪些已实现；
4. 是否实现 job_events；
5. 普通用户主动爬取入口如何降级；
6. 测试命令和结果；
7. 已知未完成项；
8. 如何手动验收。

必须明确：

```text
岗位内容变更没有进入用户侧展示。
```

---

## 验收失败的典型情况

以下任一情况出现，视为失败：

- Today 仍然只是岗位列表；
- Opportunity 没有 signals；
- 无画像仍展示岗位；
- ignored 不需要 reason；
- 普通用户还能看到主入口“刷新/发掘公司”；
- Landing 宣传岗位内容变更；
- UI 写“全网最快/竞品没有”；
- feed 失败返回假 ok；
- action API 接受 user_id；
- 使用 mock 数据冒充真实成功；
- 测试未跑却写通过。
