# 个人机会雷达 A–E 验收缺陷修复 Prompt

你现在接手的是“岗位聚合 → 个人机会雷达”转型的验收修复，不是重新设计产品，也不是继续增加功能。

工作目录：

```text
/Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623
```

当前分支：

```text
draft/radar-pivot-0623
```

先完整阅读：

```text
CLAUDE.md
docs/superpowers/specs/2026-06-23-personal-opportunity-radar-pivot-design.md
docs/superpowers/specs/2026-06-23-radar-pivot-acceptance-AtoE.md
```

本轮只修复 A–E 验收暴露的问题。Workstream F（邮件摘要、通知设置 API、管理员消费漏斗、迁移 164）仍然不做。

## 一、最终目标

修复后必须满足：

1. 完整画像用户打开 `/today` 时，真实岗位库候选召回可以在产品可接受时间内完成，不再触发 PostgreSQL `statement_timeout`。
2. 数据库表、RPC 或写入失败时，页面不得显示“已保存”“已纳入持续监控”等假成功。
3. Today 的“值得投 / 不适合 / 已投递 / 撤销”乐观状态可确定地移除、恢复和回滚。
4. `/saved` 和 `/applied` 都能保留已被物理清理岗位的历史快照。
5. Landing 和登录页不展示硬编码业务计数、虚假匹配分或其他容易被误解为真实产品数据的数字。
6. 导航、Loading、登录回跳和全部文案保持“个人机会雷达”口径。
7. 自动化门、真实数据库性能验证和迁移后的 live 写类流程全部有证据，不得只凭代码阅读宣布完成。

## 二、硬约束

- 不 push，不 merge 到 main，不触发生产部署。
- 不手工修改或打印 `.env.local`、数据库密码、service role key。
- 未经用户授权，不在生产 Supabase 或 jobs PostgreSQL 应用迁移、建索引或写业务测试数据。
- 可以在本地或独立测试数据库应用迁移做写类验收。
- 不删除 `/api/refresh`、`/api/discovery/*`、`useDiscoveryPoll`、crawler、source 管理能力。
- 不引入 Redis、向量库、LLM 排序、新搜索服务或消息队列。
- 不通过以下方式掩盖性能问题：
  - 单纯提高 `statement_timeout`；
  - 把候选上限从 4000 大幅调低；
  - 添加 `first_seen_at` 硬窗口，导致长期开放但最近仍确认在招的岗位消失；
  - 用最新岗位、随机岗位或无关岗位填满；
  - 查询失败后返回空 Feed 并标记成功。
- 不吞错误。可降级的场景必须记录 warning，并向前端返回诚实状态。
- 不使用 mock 数据、假计数或“pending 即成功”作为验收证据。
- 所有修复先写失败测试，再实现，再跑通过。

## 三、P0：修复真实岗位库候选召回超时

### 已复现问题

真实香港 jobs PostgreSQL 上，完整画像为：

```text
target role: 算法
target location: 上海
target companies: 字节跳动、示例新公司XYZ
target industry: 互联网
daily limit: 5
```

当前结果：

- FTS 召回约 36.6 秒；
- 城市召回约 31.5 秒；
- `/today` SSR 约 27.8 秒后报 `canceling statement due to statement timeout`；
- 页面只能显示“机会队列暂时无法更新”。

主要文件：

```text
lib/jobs-store/opportunities.ts
lib/jobs-store/client.ts
lib/opportunities/service.ts
jobs-db/schema.sql
app/today/page.tsx
app/api/opportunities/route.ts
```

### 修复要求

1. 先用 `EXPLAIN (ANALYZE, BUFFERS)` 或等价只读诊断定位耗时来源，记录：
   - 每条 SQL 的执行时间；
   - 是否走 `jobs_search_doc_gin`；
   - 城市查询是否 Seq Scan；
   - 排序、回表、summary 长度表达式和远程传输各自的影响。
2. 根据证据优化查询与索引。允许修改 `jobs-db/schema.sql`，但必须保持幂等，并说明生产应用方式；本轮不得自行应用到生产。
3. FTS、目标公司、城市三类召回可以并行，但必须：
   - 保持全局候选去重；
   - 保持最终最多 4000；
   - 保持 `candidate_capped` 诚实；
   - 不引入盲兜底；
   - 不丢失长期开放、最近仍被确认的高匹配岗位。
4. 目标公司候选查询可以是超集，但最终 `companyHit` 必须使用 `normalizeCompany()` 后 exact equality，不能继续用 substring 把“字节”自动视为“字节跳动”。
5. 行业准入必须复用现有 `jobIndustryAllowed()` 作为权威判断；可以额外计算行业类目用于原因展示，但不得复制近似行业门。
6. jobs 数据库不可用或查询超时时：
   - `/today` 返回明确 unavailable 状态；
   - `/api/opportunities` 返回 503；
   - 不返回 `{ ok:true, sections: empty }`；
   - `/jobs` 不能弹出未捕获 Runtime Error，应显示诚实错误面板。
7. 连接池遇到失效连接、`ETIMEDOUT` 或 `Connection terminated unexpectedly` 时，不得把坏连接长期留在池里导致后续请求持续失败。

### 性能验收

增加一个不输出连接串和敏感信息的只读性能验证脚本，例如：

```text
scripts/verify-opportunity-recall.ts
```

脚本使用真实 `JOBS_DATABASE_URL` 和固定画像，输出每个召回分支、合并候选数及总耗时。

最低门槛：

- 任一单条候选 SQL不得触发 15 秒 statement timeout；
- 单条查询目标 ≤2.5 秒；
- `recallOpportunityCandidates()` 冷启动目标 ≤5 秒；
- `/today` 完整 SSR 目标 ≤8 秒；
- 若当前数据库硬件无法达到目标，必须给出查询计划和明确阻断，不得把超时提高后声称完成。

## 四、P0：消除关注公司“假成功”

### 已复现问题

当前 Supabase 未应用 161–163，`company_watch_requests` 实际不存在，但：

- `PUT /api/preferences` 仍返回 `ok:true`；
- 页面显示“字节跳动：已纳入持续监控”；
- 页面显示“示例新公司XYZ：已记录，等待接入官方招聘源”；
- 数据库没有任何对应 request 行。

根因位于：

```text
app/api/preferences/route.ts
components/PreferenceForm.tsx
```

### 修复要求

1. 检查并处理 `sources`、`company_watch_requests` 的所有 select/upsert/delete error。
2. 只有 request 行真实写入并 read-back 成功后，才能返回 coverage success。
3. 不得根据内存计算结果直接伪造“covered / queued”成功状态。
4. 偏好本体已保存、coverage 同步失败时，返回诚实的部分成功结构，例如：

```json
{
  "ok": false,
  "preferences_saved": true,
  "coverage_synced": false,
  "error": "coverage_sync_failed"
}
```

前端必须显示：

```text
求职目标已保存，但关注公司状态同步失败，请重试。
```

不得显示“已保存目标”或任何 coverage badge。

5. `GET /api/preferences` 查询 coverage 失败时不得返回空数组假装“无关注公司”，应返回明确错误或 `coverage_available=false`。
6. `resolution_note` 必须返回给用户。管理员标记 unsupported 后，用户能看到对应人话说明。
7. 管理员标记 covered 时必须关联真实 enabled source：
   - API 接收并校验 `matched_source_ids`；
   - source 必须存在且 enabled；
   - 更新同 normalized company 的全部请求；
   - 没有关联 source 时不能仅把 status 改成 covered。
8. 用户请求内不得调用 Qianfan、Playwright、GitHub workflow 或 crawler。

## 五、P1：重做 Today 动作状态机

当前 `captureAndRemove()` 从 React `setState` updater 中同步返回局部变量，React 不保证该 updater 立即执行，可能导致岗位没有移除、toast 不出现。

主要文件：

```text
app/today-client.tsx
components/JobCard.tsx
lib/opportunities/action-input.ts
```

### 修复要求

1. 把 Today 队列移除、恢复、撤销失败回滚抽成可单测的纯 reducer 或纯状态函数，不再依赖 setState updater 的同步副作用。
2. 动作状态至少区分：
   - optimistic remove；
   - API committed；
   - API failed rollback；
   - undo optimistic restore；
   - undo committed；
   - undo failed re-remove。
3. 点“值得投 / 已投递 / 选择不适合原因”后：
   - 卡片立即移出；
   - 5 秒 toast 出现；
   - API 失败时卡片恢复原分区和稳定顺序；
   - 显示“操作失败，已恢复原状态”。
4. 点撤销后可以先乐观恢复，但若 `action=null` API 返回非 2xx 或网络错误：
   - 必须把卡片重新移出；
   - 显示明确撤销失败；
   - 不允许 UI 与数据库长期相反。
5. 同一岗位快速重复点击不能发出互相覆盖的并发请求。
6. “不适合”未选择原因或关闭面板时不得写入。
7. 事件只能在业务结果确定后按正确语义发出，payload 禁止 title、company、jd_url、email、resume、reason_text。

## 六、P1：补齐 `/saved` 的下线岗位历史

当前只有 `/applied` 使用 `job_snapshot`；`/saved` 只查询仍存在的 jobs，岗位被清理后会从“值得投”历史消失。

主要文件：

```text
app/saved/page.tsx
app/saved/saved-client.tsx
app/applied/page.tsx
lib/types.ts
```

### 修复要求

1. `/saved` 查询 `job_id, created_at, job_snapshot`。
2. 优先从权威 jobs 库读取实时岗位。
3. jobs 行不存在时，用 snapshot 展示：
   - company；
   - title；
   - location；
   - “原岗位已下线”状态。
4. 下线岗位不提供 `jd_url` 或任何失效官网链接。
5. 页面计数包含实时岗位和下线历史。
6. 对下线 saved 记录仍允许取消“值得投”，调用 `action=null`。
7. 更新 `JobAction` TypeScript 类型，使其包含 162 新增字段，避免继续依赖 `any`：

```text
reason_code
reason_text
job_snapshot
updated_at
```

## 七、P1：移除假计数、内部匹配分和旧产品文案

主要文件：

```text
app/landing-client.tsx
app/login/page.tsx
app/today/loading.tsx
app/jobs/loading.tsx
app/saved/loading.tsx
app/me/page.tsx
```

### 修复要求

1. 删除或改写以下硬编码展示：
   - 今日官方岗位 `24`；
   - 高匹配待处理 `11`；
   - 岗位匹配分 `82`；
   - 所有 `data-count` 业务数字动画。
2. 不得换成另一组假数字。
3. 可以保留静态产品示意，但只能使用无数字、不会被理解为实时数据的标签，例如：
   - “少量今日机会”；
   - “高匹配”；
   - “目标城市”；
   - “官方岗位详情”。
4. 登录页和 Landing 必须同步，不允许一个页面仍保留旧数字。
5. Loading 文案对齐真实页面：
   - Today：`今日机会 / 今天值得处理的官方岗位`，指标骨架 3 个；
   - Jobs：`搜索岗位 / 探索完整官方岗位库`，不得写刷新、发掘；
   - Saved：`值得投`，不得写“已收藏”；
   - Applied 保持“已投递”。
6. `/me` 中“我的收藏”改成“值得投”，避免信息架构口径回退。

## 八、P2：修复登录回跳

主要文件：

```text
middleware.ts
app/login/page.tsx
```

要求：

1. 未登录访问 `/today` 必须跳：

```text
/login?next=/today
```

2. 其他受保护页面保留 pathname 和 query。
3. 登录成功后优先回到合法 `next`。
4. `next` 只能接受站内单斜杠路径：
   - 必须以 `/` 开头；
   - 不能以 `//` 开头；
   - 不能接受协议、host 或反斜杠绕过；
   - 非法值回退 `/today`。
5. 邮箱密码登录、OTP 登录和密码重置成功后的跳转口径一致。

## 九、迁移与 API 诚实性

当前生产实测：

```text
user_radar_state: 不存在
notification_settings: 不存在
company_watch_requests: 不存在
job_actions: 缺少迁移 162 字段
set_job_primary_action: 不可用
```

修复要求：

1. 不修改已应用历史迁移；保留 161、162、163 文件名。
2. 增加迁移契约测试，至少验证：
   - 161 建立 radar state；
   - 162 删除跨库 FK、增加 snapshot/feedback、建立 RPC；
   - 163 建立 company watch requests 和 RLS。
3. `/api/opportunities`、Today SSR、`/api/radar/open`、动作 API、preferences API 必须检查依赖查询错误。
4. 缺表或缺 RPC 时返回稳定错误码，例如：

```text
radar_schema_unavailable
action_schema_unavailable
coverage_schema_unavailable
```

5. 前端展示诚实的“功能暂不可用”，不得显示成功或空数据。
6. 迁移只在测试 Supabase 应用后做 live 写类验收；没有迁移证据时，不得宣称 C/E 通过。

## 十、必须新增的测试

至少覆盖：

1. normalized company exact match：
   - `字节跳动有限公司` 与 `字节跳动` 命中；
   - `字节` 与 `字节跳动` 不命中；
   - 不同公司不得 substring 误合并。
2. coverage 任一数据库操作报错时：
   - API 不返回 `ok:true`；
   - 不返回伪造 coverage；
   - 前端不显示成功 badge。
3. 管理员 covered 必须有合法 enabled source IDs。
4. Today reducer：
   - optimistic remove；
   - API failure restore；
   - undo success；
   - undo failure re-remove；
   - 多岗位并发互不影响；
   - 分区和顺序不漂移。
5. saved snapshot：
   - live job 正常展示；
   - deleted job 用 snapshot；
   - deleted job 无链接；
   - deleted job 可取消 saved。
6. Landing/Login 静态检查：
   - 不含 `data-count="24"`、`11 个高匹配`、`82` 匹配分；
   - 不展示内部 score。
7. Loading 文案与导航口径。
8. `next` 参数安全校验和登录回跳。
9. opportunities route 的数据库错误返回 503，而不是成功空 Feed。
10. recall 查询生成规则和候选去重、cap、不限制旧 first_seen 的回归测试。

## 十一、完整验收命令

全部必须重新执行并记录真实结果：

```bash
cd /Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623

node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npx tsc --noEmit
npm run build
bash scripts/check-migrations.sh
git diff --check
```

另外执行：

```bash
node --test tests/opportunity-*.test.js tests/company-normalize.test.js
```

以及新增的真实只读性能验证：

```bash
npx tsx scripts/verify-opportunity-recall.ts
```

## 十二、迁移后的浏览器/live 验收

仅在测试 Supabase 已应用 161–163 后执行：

1. 未登录 `/today` → `/login?next=/today`。
2. 未完整画像 → onboarding，不展示岗位。
3. 完整画像 → Today 在性能预算内返回，不超时。
4. Today 全部岗位 active、summary ≥60、无重复、无已动作岗位。
5. 值得投 → 移出 Today → `/saved` 可见。
6. 已投递 → 移出 Today → `/applied` 可见。
7. 不适合未选原因不写；选原因后移出。
8. 三种动作均可 5 秒内撤销。
9. 人为让动作 API 失败，卡片和数据库状态均回滚。
10. 人为让 undo API 失败，卡片重新移出并提示失败。
11. 删除测试 jobs 行后，saved/applied 均显示 snapshot 和“原岗位已下线”，无失效链接。
12. 已覆盖公司产生真实 covered request 行。
13. 未覆盖公司产生真实 queued request 行。
14. 管理员没有关联 source 时不能标 covered。
15. 用户 A 的 action/watch request 不影响用户 B。
16. events payload 不含敏感字段。

## 十三、交付要求

完成后提交一份修复报告，必须包含：

1. 每个缺陷的根因；
2. 修改文件清单；
3. 新增测试及红绿证据；
4. 自动化门实际结果；
5. 召回 SQL 修复前后耗时和 query plan 摘要；
6. 是否应用了测试迁移；
7. 哪些 live 流程真实通过；
8. 哪些仍未验及原因；
9. `git status --short`；
10. 最终 commit 列表。

不得只回复“已完成”“测试通过”或引用旧测试结果。不得 push，等待独立验收。
