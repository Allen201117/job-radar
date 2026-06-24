# 个人机会时效雷达 Acceptance Spec

> 日期：2026-06-24  
> 状态：验收规格，供实现 agent 和验收 agent 共用  
> 产品规格：`docs/superpowers/specs/2026-06-24-opportunity-timing-radar-product-spec.md`  
> 技术规格：`docs/superpowers/specs/2026-06-24-opportunity-timing-radar-technical-spec.md`

---

## 0. 验收原则

本次验收只认真实行为，不认表面 UI。

必须满足：

- API 返回真实字段；
- 数据库读回真实写入；
- Today 卡片必须有 signal；
- 不用 mock 数据假装成功；
- 不把 source_candidates pending 当成产品成功；
- 不把 crawler 运行次数当成用户价值；
- 不展示岗位内容变更；
- 不对外承诺竞品没有或全网最早。

---

## 1. 文档一致性验收

检查 UI / 代码中的外宣文案：

```bash
rg -n "岗位内容变更|JD.*变更|内容更新|重新开放|全网最快|全网最早|BOSS.*没有|自动投递" app components lib
```

允许：

- docs 中说明“不展示 / 不承诺”；
- technical spec 中的 `JOB_CONTENT_HASH_CHANGED_INTERNAL`；
- 测试中验证禁止展示。

如果需要审文档外宣稿，只检查不带否定语义的宣传段落；不要把本文中的禁止性描述当成违规。

不允许：

- Landing 宣传岗位内容变更；
- Today 卡片展示岗位内容变更；
- 报名帖把内容变更当核心卖点；
- UI 写“全网最快”“竞品没有”。

---

## 2. 数据模型验收

### 2.1 radar_mode

数据库必须存在：

```sql
select column_name
from information_schema.columns
where table_name = 'user_preferences'
  and column_name in ('radar_mode', 'radar_mode_confirmed_at');
```

必须返回两行。

约束验收：

- `radar_mode` 只允许 `sprint/watch/campus`；
- 默认 `sprint`；
- API 保存时写当前用户，不接受客户端 user_id。

### 2.2 user_opportunity_deliveries

必须存在：

```sql
select table_name
from information_schema.tables
where table_name = 'user_opportunity_deliveries';
```

字段必须包含：

```text
user_id
job_id
company
signal_type
delivery_key
surface
radar_mode
score
tier
delivered_at
consumed_at
dismissed_at
payload
```

唯一约束必须保证：

```text
(user_id, delivery_key, surface)
```

### 2.3 job_events

如果 Phase D 已执行，jobs DB 必须存在：

```sql
select to_regclass('public.job_events');
```

事件类型必须只允许：

```text
JOB_FIRST_SEEN
JOB_STILL_OPEN_CONFIRMED
JOB_CLOSED
JOB_CONTENT_HASH_CHANGED_INTERNAL
JOB_REAPPEARED_INTERNAL
```

若 Phase D 未执行，验收报告必须明确写：

```text
Phase D 未执行；V1 用户侧不得依赖 job_events；内容变更不得展示。
```

---

## 3. API 验收

### 3.1 `GET /api/preferences`

必须返回：

```json
{
  "ok": true,
  "preferences": {
    "radar_mode": "sprint"
  },
  "profile_ready": false,
  "profile_ready_missing": [],
  "coverage": [],
  "notification_settings": {}
}
```

验收点：

- 未登录返回 401 或 redirect，符合项目既有 auth 规范；
- 登录后不泄漏其他用户数据；
- 返回 mode；
- 返回 coverage；
- 返回 profile_ready；
- 不返回 source 技术细节给普通用户。

### 3.2 `PUT /api/preferences`

测试：

```json
{
  "radar_mode": "watch",
  "target_companies": ["字节跳动"],
  "target_roles": ["产品经理"],
  "daily_limit": 99,
  "user_id": "malicious"
}
```

必须：

- 忽略或拒绝 user_id；
- daily_limit clamp 到 watch max；
- 写当前登录用户；
- `company_watch_requests` 生成或更新；
- 返回 coverage；
- 写 `radar_mode_confirmed_at`。

### 3.3 `GET /api/opportunities`

必须返回：

```json
{
  "ok": true,
  "profile_ready": true,
  "mode": "sprint",
  "counts": {
    "by_signal": {}
  },
  "sections": []
}
```

每个 section：

```json
{
  "key": "new_matches",
  "title": "新出现的对口机会",
  "description": "...",
  "opportunities": []
}
```

每个 opportunity 必须有：

```text
job
score
tier
reasons
signals
freshness
firstSeenAt
lastSeenAt
deadlineAt
mode
```

每个 opportunity 的 `signals.length >= 1`。

禁止：

- 返回 mock opportunity；
- feed 失败仍返回 ok true；
- 无 profile 时返回随机岗位；
- unknown freshness 却显示 “最近确认仍在招”。

### 3.4 `POST /api/radar/open`

必须：

- 更新 `user_radar_state.last_opened_at`；
- 不接受 user_id；
- 写事件 `radar_feed_opened`；
- 幂等；
- 不创建岗位动作。

### 3.5 `POST /api/job-actions/[jobId]`

ignored 无 reason：

```json
{ "action": "ignored" }
```

必须返回 400。

ignored 有 reason：

```json
{ "action": "ignored", "reason_code": "location_mismatch" }
```

必须成功，并读回：

```text
reason_code = location_mismatch
job_snapshot 非空
```

saved/applied：

- 必须清空 reason_code/reason_text；
- 同岗位主动作唯一；
- viewed 不受影响。

---

## 4. Feed 行为验收

### 4.1 Profile readiness

#### sprint

输入：

- 有 target role；
- 无 location。

结果：

- `profile_ready=false`；
- Today 显示 onboarding；
- 不展示随机岗位。

#### watch

输入：

- 只有 target company；
- 无 location。

结果：

- `profile_ready=true`；
- 可生成 feed；
- 城市不作为硬门。

#### campus

输入：

- target role 有；
- experience_stage 为空。

结果：

- `profile_ready=false`。

输入：

- target role 有；
- experience_stage=实习。

结果：

- `profile_ready=true`。

### 4.2 NEW_MATCH

构造岗位：

- active；
- summary >= 60；
- freshness verified；
- first_seen_at > novelty_since；
- score >= threshold。

必须：

- signals 包含 `NEW_MATCH`；
- 卡片显示 `新发现` 或等价文案；
- 不显示 `全网最早`。

### 4.3 STILL_OPEN_PRIORITY

构造岗位：

- active；
- last_seen_at 在 verified SLA 内；
- first_seen_at <= novelty_since；
- score >= 70；
- source metadata 存在。

必须：

- signals 包含 `STILL_OPEN_PRIORITY`；
- 显示 `最近确认仍在招`；
- 如果 last_seen_at 缺失，不能触发。

### 4.4 DEADLINE_SOON

构造：

- deadline `2026-07-01`；
- now `2026-06-28`；
- mode sprint。

必须：

- signals 包含 `DEADLINE_SOON`。

构造：

- deadline `长期有效`。

必须：

- 不触发 `DEADLINE_SOON`。

campus：

- now 到 deadline 14 天内可触发；
- 15 天不触发。

### 4.5 COMPANY_MOMENTUM

构造公司：

- 近 14 天 5 个新 active 岗位；
- 前 14 天 1 个；
- 至少 2 个代表岗位通过硬门；
- verified 比例 >= 50%。

必须：

- section 包含 company momentum；
- 文案带 `据本平台已覆盖官方源`；
- 不写 `扩招`、`HC 暴涨`、`官方宣布`。

构造公司：

- 近 14 天 2 个；

必须：

- 不触发 momentum。

### 4.6 CLOSED_OR_STALE

saved 岗位变为 expired：

- saved/status section 显示 `可能已关闭`；
- 不在主推荐区展示。

active 但 stale：

- 对 saved/target company 可提示 `长时间未确认`；
- 对普通未交互岗位不进入 Today。

### 4.7 内容变更禁止展示

构造：

- content_hash 从 A 变 B；

如果 Phase D 已执行：

- 可生成 `JOB_CONTENT_HASH_CHANGED_INTERNAL`；
- 不生成任何用户侧 signal；
- Today 不展示“内容变更”。

如果 Phase D 未执行：

- 不影响 V1 feed；
- 不展示内容变更。

---

## 5. UI 验收

### 5.1 Landing

必须表达：

- 企业官网；
- 真实；
- 对口；
- 仍有效；
- 现在值得处理。

不得表达：

- 主动爬虫；
- 全网最全；
- 岗位内容变更；
- 自动投递；
- 竞品没有。

### 5.2 Today

必须：

- 登录后默认核心页；
- 显示模式；
- 显示 signal counts；
- 每张卡有 signal label；
- 每张卡有官方链接；
- 每张卡有最近确认时间或明确降级状态；
- 有 saved / ignored / applied 动作；
- ignored 要选择原因。

不得：

- 展示内部 score；
- 展示 crawler/source/workflow；
- 用无关岗位填满；
- 用户未画像时展示岗位。

### 5.3 Preferences

必须：

- 可选择 sprint/watch/campus；
- 保存后 API 读回；
- 显示关注公司覆盖状态；
- 普通用户看不到“启动爬虫”。

### 5.4 Jobs

必须：

- 保留搜索；
- 普通用户默认不看到主动 refresh/discovery；
- 管理员或 feature flag 可保留；
- 搜索页不影响 Today 主叙事。

---

## 6. 技术测试命令

必须运行：

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

验收报告必须列出：

- 命令；
- 是否通过；
- 失败原因；
- 如果未运行，说明阻塞原因。

---

## 7. 回归重点

不得破坏：

- 现有 `/jobs` 搜索；
- `canonical_jd_url` 去重；
- jobs 独立 PostgreSQL 读取；
- Supabase auth；
- `job_actions` 用户隔离；
- admin health；
- crawler upsert 语义；
- expired sticky；
- summary preserve-if-empty；
- source disabled 过滤；
- events payload 清洗。

---

## 8. 最终验收判定

可通过条件：

1. 三种模式真实可用；
2. 五类用户侧 signal 中至少前四类可在测试中构造并返回，`CLOSED_OR_STALE` 至少在 saved/status 场景可返回；
3. Today 不再是普通岗位列表；
4. 普通用户主动爬取入口已降级；
5. 忽略反馈真实入库；
6. delivery ledger 可去重；
7. 内容变更不展示；
8. 所有测试命令通过或失败原因明确且非本改动引入。

不可通过条件：

- 用 mock feed 代替真实引擎；
- 无画像仍展示岗位；
- Today 卡片没有 signal；
- 展示“岗位内容变更”；
- 展示“全网最快 / 竞品没有”；
- ignored 无 reason 仍成功；
- action 写入绕过当前用户；
- feed 失败仍返回 ok。
