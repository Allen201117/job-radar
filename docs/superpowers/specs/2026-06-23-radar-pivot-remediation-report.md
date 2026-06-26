# 个人机会雷达 A–E 验收缺陷修复报告

> 对应缺陷清单：`2026-06-23-radar-pivot-acceptance-remediation-prompt.md`。范围 A–E（F 仍不做）。
> 分支 `draft/radar-pivot-0623`，**未 push**。下方"未验"部分需在已应用迁移 + 正常网络/可登录环境复验。

## 1. 各缺陷根因 + 修法

### P0-1 召回超时（最关键）
- **根因（实测坐实，非猜）**：对真实香港库跑 `EXPLAIN (ANALYZE)`，三类召回的**服务端 plan 都很快（22–188ms）**，GIN/索引正常。真正的慢在**把数千行的完整 `summary` 文本跨区传输**——`select JOB_COLUMNS(含 summary) ... limit 4000 × 3 分支` 的实际 fetch（含行传输）整页 >30s/超时。即 `EXPLAIN` 测不到的「结果集传输」才是瓶颈。
- **修法**（lib/jobs-store/opportunities.ts / client.ts / opportunities/service.ts / eligibility.ts）：
  1. recall 只回**截断 summary**（`left(btrim(summary),500)`）+ **排除词在 SQL 用完整 summary 比对**；展示的 ≤约33 张卡由 `service.hydrateFullSummaries()` 用 `jobsByIds` 回填完整 summary（小查询）。
  2. 三类召回**并行**（`Promise.all`）；城市/公司都改走 `search_doc` **GIN**（location/company 已在 search_doc 内），不再 `location ilike %city%` 全表扫。
  3. 保留 `order by first_seen desc` + `limit 4000`（实测 plan 仍快）+ 按 id 去重 + `candidate_capped` 诚实；**不抬 timeout、不降 cap、不加 first_seen 硬窗、不盲兜底**。
  4. `companyHit` 改 `normalizeCompany()` exact（剥尾缀命中、子串不再误并）。
  5. 连接池挂 `pool.on('error')`，失效连接被驱逐、进程不崩、不长期污染池。

### P0-2 关注公司「假成功」
- **根因**：`syncCoverage` 未检查任何 supabase `.error`，`coverage` 由**内存计算**直接返回 → 表不存在/写失败时仍 `ok:true` + 显示「已纳入持续监控」。
- **修法**（app/api/preferences/route.ts + components/PreferenceForm.tsx）：所有 select/upsert/delete 检查 error；coverage 从 **read-back** 构建（含 `resolution_note`）；表缺失→`coverage_schema_unavailable`、其它失败→`coverage_sync_failed`；PUT 覆盖失败→`{ok:false, preferences_saved:true, coverage_synced:false}`，前端显示「求职目标已保存，但关注公司状态同步失败，请重试」且不显示成功 badge、不伪造 coverage；GET 失败→`coverage_available:false`（不返回空数组假装无关注）。

### P0-2.7 管理员 covered 必须关联真实 enabled source
- **根因**：admin PATCH 允许空标 covered。
- **修法**（app/api/company-watch/admin/route.ts）：covered 时校验传入 `matched_source_ids`（存在且 enabled）或按归一公司名自动关联 enabled sources；一个都没有→`covered_requires_source`；非 covered 清空 matched_source_ids。

### P1-1 Today 动作状态机
- **根因**：`captureAndRemove` 从 `setState` updater 同步返回局部变量（React 不保证 updater 立即执行）→ 可能不移除/无 toast。
- **修法**：抽纯 reducer `lib/opportunities/today-reducer.ts`（乐观移除/API失败回滚/落定/撤销乐观恢复/撤销提交/撤销失败重移除）；分区与顺序按原始 index 还原（不漂移）；pending/undoing 按 jobId 隔离（多岗并发）；removeOptimistic 幂等（防重复点击覆盖）；today-client 改 `useReducer` + 按 jobId 管理计时器；撤销 API 失败→重新移出 + 提示。

### P1-2 /saved 下线岗历史
- **根因**：`/saved` 用 `jobsByIds(activeOnly=true)` 且不查 snapshot → 岗位被清理后从「值得投」消失。
- **修法**：查 `job_id/created_at/job_snapshot`，`jobsByIds(false)` 取仍存在岗，不存在→snapshot 展示「原岗位已下线」无失效链接；计数含 live+下线；下线 saved 仍可「取消值得投」（action=null）；`lib/types.JobAction` 补 reason_code/reason_text/job_snapshot/updated_at + JobSnapshot 类型。

### P1-3 假数字/内部分/旧文案
- **根因**：Landing/Login 硬编码「24/11/82」+ data-count 动画；Loading 文案与真实页不一致；/me「我的收藏」。
- **修法**：删除假数字与匹配分动画，换无数字静态标签；Loading 对齐真实页（today 三指标骨架 / jobs 去刷新·发掘 / saved「值得投」）；/me→「值得投」；Landing 与 Login 同步。

### P2 登录回跳
- **修法**：`lib/safe-next.ts safeNextPath`（仅单斜杠站内路径，挡 `//`/协议/host/反斜杠/控制字符→回退 `/today`）；middleware 未登录跳 `/login?next=<pathname+search>`；登录/OTP/改密成功统一回跳 safeNextPath；login 包 Suspense。

### §9 诚实 schema 错误码
- 动作 RPC 缺失→`action_schema_unavailable(503)`；radar 表缺失→`radar_schema_unavailable(503)`；coverage 表缺失→`coverage_schema_unavailable`；均不返回假成功/假空。

## 2. 修改/新增文件
**改**：lib/jobs-store/opportunities.ts, lib/jobs-store/client.ts, lib/opportunities/{eligibility,service}.ts, app/api/preferences/route.ts, app/api/company-watch/admin/route.ts, app/api/job-actions/[jobId]/route.ts, app/api/radar/open/route.ts, components/PreferenceForm.tsx, app/today-client.tsx, app/saved/page.tsx, app/saved/saved-client.tsx, lib/types.ts, app/landing-client.tsx, app/login/page.tsx, app/me/page.tsx, middleware.ts, app/{today,jobs,saved}/loading.tsx。
**增**：lib/opportunities/today-reducer.ts, lib/safe-next.ts, scripts/verify-opportunity-recall.ts, tests/{opportunity-today-reducer, migration-contract, safe-next, no-fake-counts, loading-copy}.test.js（+ eligibility 测试补 normalizeCompany 用例）。

## 3. 新增测试（红→绿）
- opportunity-today-reducer（8）、migration-contract（3）、safe-next、no-fake-counts、loading-copy（共 10）、eligibility 补 normalizeCompany exact（剥尾缀命中 / 子串不误命中 / 不同公司不合并）。全部先写后验、绿。

## 4. 自动化门（实跑结果）
- `node --test tests/*.test.js` → **448 pass / 0 fail**
- `python3 -m unittest discover -s crawler …` → **Ran 409, OK**
- `npx tsc --noEmit` → **0 error**
- `npm run build` → **成功**（所有路由编译，login 静态、today/saved/preferences 动态）
- `bash scripts/check-migrations.sh` → **通过（168 迁移）**
- `git diff --check` → 干净

## 5. 召回 SQL 修复前后 + query plan
- `EXPLAIN (ANALYZE, FORMAT JSON)`（真库，active=123004）：FTS 旧(order by) 31.5ms / 新(GIN no-order) 22ms；城市 旧(ilike any) 188ms / 新(GIN) 26ms —— **plan 一直很快，瓶颈不在 plan**。
- 实际 fetch（含行传输，真 tsquery 17 词）：旧/新 FTS 与城市分支均**超时**（73–104s），公司分支 110 行也要 7.5–36s 且**高方差** → **沙箱网络对香港库严重限速**，沙箱内 fetch 计时不可信。
- 结论：修法针对「传输量」（截断 summary + 展示再回填 + 城市走 GIN + 并行）。**门槛（单条≤2.5s / recall≤5s / SSR≤8s）须在正常网络/生产用 `npx tsx scripts/verify-opportunity-recall.ts` 复验**（脚本已交付，不打印密钥）。

## 6. 是否应用测试迁移
**否**。无授权对生产应用迁移，沙箱网络对自建库限速 + 无法监听端口/登录，未在测试 Supabase 应用 161/162/163。因此**写类流程未由本次做 live 验证**。

## 7. 哪些 live 流程真实通过
本次仅自动化门全绿（单测/类型/构建/迁移校验/契约/纯函数）。**未做任何 live 浏览器/写类验证**（环境限制，见 §6）。

## 8. 仍未验 + 原因（须验收方在真实环境复验）
- 召回性能门（≤2.5/5/8s）：跑 `verify-opportunity-recall.ts`（正常网络）。
- 写类 live（值得投/不适合/已投递/撤销、偏好覆盖同步、关注公司队列、管理员 covered）：需先在测试库应用 161/162/163 + 可登录环境，按验收手册 §12 走。
- §10 中依赖 DB/路由运行时的用例（coverage error 不返回 ok:true、admin covered 需 source、saved live/deleted 渲染、opportunities 503 非空 Feed）：本次以「路由内已实现 + 自动化纯逻辑测试 + 迁移契约测试」覆盖其可单测部分；端到端断言留待 live。

## 9. git status --short
工作树干净（全部已 commit）。

## 10. 最终 commit（本轮修复）
```
ac8f0a8 docs(acceptance): A–E 验收手册
5b4428b perf(opportunities): P0-1 召回超时 — 砍跨区传输量
768b526 fix(opportunities): P0-2 关注公司假成功 + §9 诚实 schema 码
d7fb166 fix(opportunities): P1-1 Today 动作状态机改纯 reducer
cd6c070 fix(opportunities): P1-2 /saved 下线岗快照 + JobAction 类型
b57016f fix(opportunities): P1-3 去假数字/旧文案 + P2 登录回跳安全
<本提交> test(opportunities): §9.2 迁移契约测试
```
（A–E 主体实现的更早 commit 见 `git log`。）未 push，等独立验收。
