# 个人机会雷达 A–E 缺陷修复 · 复验交接单（给验收 agent）

> 你上一轮验收 A–E 写出了缺陷清单 `2026-06-23-radar-pivot-acceptance-remediation-prompt.md`。本轮已按它逐条修复。
> 本单是**复验指南**：确认每个缺陷是否真的关闭，并完成我（开发方）因环境受限**没能做的 live 验证**。
> 不是重新设计、不加功能。**F（邮件/通知 API/消费漏斗/迁移 164）仍不做**。

## 0. 在哪 / 提交范围

- Worktree：`/Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623`，分支 `draft/radar-pivot-0623`，HEAD=`9f7146a`，**未 push**。
- 本轮修复提交（在你上轮之后新增）：
  ```
  5b4428b P0-1 召回超时 — 砍跨区传输量
  768b526 P0-2 关注公司假成功 + §9 诚实 schema 码
  d7fb166 P1-1 Today 动作状态机改纯 reducer
  cd6c070 P1-2 /saved 下线岗快照 + JobAction 类型
  b57016f P1-3 去假数字/旧文案 + P2 登录回跳
  53e204e §9.2 迁移契约测试
  9f7146a 修复报告
  ```
- 深度细节见同目录 `...-remediation-report.md`（根因/改动/门结果）。验收基线手册见 `...-acceptance-AtoE.md`。
- 硬约束（继续遵守）：**不 push、不 merge main、不打印 .env/密钥；未经用户授权不对生产应用迁移/建索引/写测试数据；可在测试库应用迁移做写类验收。**

## 1. 先跑自动化门（应全绿；我实测如下，请复跑）

```bash
cd /Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623
node --test tests/*.test.js          # 我实测 448 pass / 0 fail
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"   # 409 OK
npx tsc --noEmit                     # 0 error
npm run build                        # 成功
bash scripts/check-migrations.sh     # 168 通过
git diff --check                     # 干净
```
任一不绿 = 直接判不通过并贴输出。

## 2. 逐缺陷复验（对照你上轮清单）

> 图例：🟢=可纯代码/单测确认；🔵=须 live（已应用迁移 + 正常网络/可登录环境）。

### P0-1 召回超时（remediation §三）
- 改动：`lib/jobs-store/opportunities.ts`（截断 summary `left(...,500)` + 排除词进 SQL + 三分支并行 + 城市/公司走 search_doc GIN + 保留 order by/cap 4000/去重/candidate_capped）、`lib/jobs-store/client.ts`（pool error handler）、`lib/opportunities/service.ts`（`hydrateFullSummaries` 给展示卡回填完整 summary）、`lib/opportunities/eligibility.ts`（companyHit→normalizeCompany exact）。
- 🟢 代码核查：召回 SQL 无 `location ilike`（改 GIN）；无 first_seen 硬窗（role/company 分支不含 first_seen 过滤，仅 city 分支按"近7天新增"含）；cap 仍 4000、`candidate_capped` 由去重前总数>4000 得出；companyHit 用 normalizeCompany exact（见 eligibility 单测）。
- 🔵 **性能门（必须你来跑，我沙箱网络被限速测不准）**：`npx tsx scripts/verify-opportunity-recall.ts`（环境先 `set -a; source .env.local; set +a`）。固定画像（算法/上海/字节跳动+示例新公司XYZ/互联网/daily5）。门槛：单条召回 SQL ≤2.5s、`recall` 并行总 ≤5s；并据此推断 `/today` SSR ≤8s。未达标→脚本提示贴 `EXPLAIN (ANALYZE)` 判断 plan vs 传输，**不得靠抬 timeout 蒙混**。
- 🔵 降级诚实：jobs 库不可用/超时时 `/api/opportunities`→503（非 `{ok:true,sections:空}`）、`/today`→明确"机会队列暂时无法更新"、`/jobs` 不弹未捕获 Runtime（诚实错误面板）。

### P0-2 关注公司假成功（remediation §四）
- 改动：`app/api/preferences/route.ts`（syncCoverage 查所有 error + read-back 构建 coverage + schema 缺失码）、`components/PreferenceForm.tsx`（部分成功文案/coverage_available/resolution_note，不伪造 badge）。
- 🟢 代码核查：syncCoverage 每个 select/upsert/delete 都检查 `.error`；coverage 来自 read-back 而非内存；PUT 覆盖失败返回 `{ok:false, preferences_saved:true, coverage_synced:false, error}`；GET 失败返回 `coverage_available:false`。
- 🔵 live（迁移未应用时复现旧 bug 已不再）：① 迁移**未**应用 → 保存偏好：偏好存上，但页面显示"求职目标已保存，但关注公司状态同步失败，请重试"，**不显示任何 covered/queued badge**，DB 无 request 行。② 迁移应用后 → 已覆盖公司(如字节跳动)显示"已纳入持续监控"且有真实 request 行；未覆盖公司"已记录，等待接入"且有真实 queued 行；保存秒回、不触发抓取。

### P0-2.7 管理员 covered 必须关联真实 enabled source（remediation §四.7）
- 改动：`app/api/company-watch/admin/route.ts`。
- 🟢 代码核查：PATCH status=covered 时校验传入 matched_source_ids（存在且 enabled）或按归一公司名自动关联 enabled sources；都没有→`covered_requires_source`；非 covered 清空 matched_source_ids。
- 🔵 live：管理员对"无任何 enabled source"的公司标 covered → 应被拒（covered_requires_source），不能空标。

### P1-1 Today 动作状态机（remediation §五）
- 改动：新增 `lib/opportunities/today-reducer.ts`（纯 reducer）；`app/today-client.tsx` 改 useReducer。
- 🟢 单测：`tests/opportunity-today-reducer.test.js`（8 例）覆盖 乐观移除/API失败回滚/落定/撤销成功/撤销失败重移除/多岗并发/顺序不漂移/幂等。
- 🔵 live：值得投/已投递/选不适合原因 → 卡片立即移出 + 5s toast；动作 API 人为失败 → 卡片回原分区原顺序 + "操作失败，已恢复原状态"；撤销 → 恢复；撤销 API 人为失败 → 重新移出 + "撤销失败"；同岗快速重复点击不并发互覆盖；"不适合"未选原因不写。

### P1-2 /saved 下线岗历史（remediation §六）
- 改动：`app/saved/page.tsx`、`app/saved/saved-client.tsx`、`lib/types.ts`（JobAction 补 reason_code/reason_text/job_snapshot/updated_at + JobSnapshot 类型，不再 any）。
- 🟢 代码核查：/saved 查 job_id/created_at/job_snapshot，jobsByIds(activeOnly=false)；不存在→snapshot 展示"原岗位已下线"无 jd_url；计数含 live+下线；下线项有"取消值得投"(action=null)。
- 🔵 live：删掉一条测试 saved 岗的 jobs 行 → /saved 仍显示该条(snapshot + 原岗位已下线 + 无链接)，且可取消；live 岗正常展示。

### P1-3 假数字/内部分/旧文案（remediation §七）
- 改动：`app/landing-client.tsx`、`app/login/page.tsx`、`app/{today,jobs,saved}/loading.tsx`、`app/me/page.tsx`。
- 🟢 单测：`tests/no-fake-counts.test.js`（Landing/Login 无 data-count="24"/11/82 假数字与匹配分）、`tests/loading-copy.test.js`（today "今天值得处理的官方岗位"；jobs "探索完整官方岗位库" 且无"刷新/发掘"；saved "值得投" 非"已收藏"）。
- 🔵 目检：Landing 与登录页无任何被当作实时数据的数字；/me "值得投"。

### P2 登录回跳（remediation §八）
- 改动：新增 `lib/safe-next.ts`；`middleware.ts`、`app/login/page.tsx`。
- 🟢 单测：`tests/safe-next.test.js`（safeNextPath：接受 /today、/jobs?x=1；拒绝 //evil、协议、host、反斜杠、控制字符、空、非串、无前导斜杠 → /today）。
- 🔵 live：未登录访问 /today→/login?next=/today；其他受保护页保留 pathname+query；邮箱/OTP/改密登录成功后回到合法 next、非法回退 /today。

### §9 诚实 schema 码 + §9.2 契约测试
- 🟢 单测：`tests/migration-contract.test.js`（161 radar state、162 删 FK+快照/反馈列+set_job_primary_action RPC、163 watch+RLS）。
- 🟢 代码核查：动作 RPC 缺失→action_schema_unavailable(503)；radar 表缺失→radar_schema_unavailable(503)；coverage 表缺失→coverage_schema_unavailable；均不假成功/假空。
- 🔵 live：迁移未应用时上述路由返回对应 503/诚实结构，前端不显示成功。

## 3. 我（开发方）明确**没做**的验证 —— 请你在真实环境补齐

1. **召回性能门**：沙箱网络对香港库严重限速(110 行 7.5–36s 高方差)，沙箱内 fetch 计时不可信。EXPLAIN 服务端 plan 已确认快(22–188ms)；传输量已削减；但 ≤2.5/5/8s 门**未实测达标**，须你跑 `verify-opportunity-recall.ts`（正常网络/生产）。
2. **全部写类 live 流程**：我未对生产/测试库应用迁移 161/162/163，也无法在沙箱登录/监听端口，故 P0-2 / P0-2.7 / P1-1 / P1-2 / §9 的 🔵 项**一个都没 live 跑过**。须你在测试 Supabase 应用 161/162/163 后，按基线手册 `...-acceptance-AtoE.md` §12 完整走一遍（含用户 A/B 隔离、events 无 PII）。
3. **§10 中依赖 DB/路由运行时的端到端断言**（coverage 出错不返回 ok:true、admin covered 需 source、saved live/deleted 渲染、opportunities 503 非空 Feed、recall 去重/cap 实查）：本轮以"路由内已实现 + 可单测的纯逻辑/契约测试"覆盖其可单测部分，端到端留你 live 确认。

## 4. 回报要求

给结论，含：① 自动化门复跑结果；② 每个缺陷 🟢/🔵 项的 通过/失败/未验(原因)；③ 性能脚本实测每分支与总耗时 + 是否达标(+不达标的 EXPLAIN)；④ 是否应用了测试迁移、哪些 live 流程真过；⑤ 仍未验项与原因；⑥ 残留缺陷(根因+复现+实际vs期望，分必须改/建议改)；⑦ git status --short。
**不得只回"已完成/测试通过"，不得引用旧结果，不得 push。**

---

## 5. 复验轮 2 — 你上轮 6 个阻断项的处置（commit `308291e`，HEAD 仍未 push）

> 自动化门已复跑：node --test **453** / crawler 409 / tsc 0 / build / check-migrations 168 / git diff --check 全绿。

| # | 你上轮阻断项 | 处置 | 复验方式 |
|---|---|---|---|
| 1 | 真库性能门失败（company 110 行 22s、服务端仅 4ms） | 🟡 **代码已改**：三并行分支（最多 3 次跨区 SSL 握手）→ **合并成一条 `search_doc` OR 查询（同一 GIN BitmapOr）= 单连接单往返**，直击「服务端快但连接/跨区慢」的真因。`lib/jobs-store/opportunities.ts` recallViaStore。 | 🔵 **必须你复验**：正常网络/部署路径跑 `verify-opportunity-recall.ts`，确认 ≤2.5/5/8s。沙箱对 HK 限速测不准，我无法判定真实达标；若仍超标，多半是 Vercel↔HK 跨区延迟的基础设施问题（超本 Spec 范围，需用户定 region/连接池）。 |
| 2 | 线上迁移 161–163 未应用（PGRST205） | ⚪ **非代码缺陷**：因未 push，迁移没自动应用。 | 🔵 需用户授权：push（自动 apply）或在测试库手动 apply 161/162/163，再按手册 §5 走写类。 |
| 3 | 行业门未复用权威 `jobIndustryAllowed()` | 🟢 **已修**：`eligibility.ts industryState` 拒绝判定改为直接调 `jobIndustryAllowed()`；allowed 后才用同源 `classifyCompanyIndustry` 细分 match/unknown（仅供打分/degrade，不改拒绝口径）。 | 🟢 读 `eligibility.ts`（约 line 74）确认调用 jobIndustryAllowed；node --test opportunity-eligibility 全绿。 |
| 4 | 动作埋点在 API 成功前发 + acting 防不住连点 | 🟢 **已修**：`JobCard.tsx callActionApi` 把 `track()` 移到 **fetch 成功之后**；新增 `actingRef`（useRef）在入口同步去重，挡同一渲染周期重复请求。 | 🟢 读 `JobCard.tsx`（callActionApi）确认 track 在 try 成功分支内、actingRef 守卫；🔵 live 时连点/断网复测不重复发、不记成功。 |
| 5 | `coverage_schema_unavailable` 漏判 PGRST205 | 🟢 **已修**：抽 `lib/opportunities/schema-errors.ts`（`isMissingRelation` 认 PGRST205/42P01、`isMissingFunction` 认 PGRST202/42883 + 文本兜底），preferences/radar/job-actions 三路由统一复用；**新增 `tests/schema-errors.test.js`(5 例)**。 | 🟢 跑 `node --test tests/schema-errors.test.js`；读三路由确认复用同一 helper。🔵 live：缺表时 PUT /api/preferences 返回 `coverage_schema_unavailable`（非 coverage_sync_failed）。 |
| 6 | `candidate_capped` 截断恰好时误判 false | 🟢 **已修**：合并查询后 `capped = rows.length >= limit`（命中 limit 即截断=true）；Supabase 回退同口径（branchCapped）。 | 🟢 读 `opportunities.ts` recallViaStore 末行；🔵 live：用极宽画像命中 4000 行确认 candidate_capped=true。 |

仍未由我 live 验证（同 §3）：性能真实达标、全部写类流程（迁移未应用 + 沙箱断网）。请在真实环境补齐后再判通过/不通过。

---

## 6. 测试库验收路径（用户已拍板：不 push，用测试库验）

> 两条独立验证，互不依赖。在**正常网络**机器上做（不要在受限沙箱里量性能）。

### 6A. 性能（不需要任何迁移）
召回打的是**香港 jobs 库**（与 Supabase 用户表无关），所以只要 `JOBS_DATABASE_URL` + 正常网络即可：
```bash
cd <worktree>; set -a; source .env.local; set +a
npx tsx scripts/verify-opportunity-recall.ts
```
- 脚本已与最新实现同口径（**单条合并 search_doc OR 查询**，warm-up 后取 3 次中位）。门槛：合并召回中位 **≤5000ms**（据此 + 引擎纯 JS 推断 /today SSR ≤8s）。
- 若仍 FAIL：贴 `EXPLAIN (ANALYZE)`。**plan 快但总慢 = 跨区传输/延迟**（本机→香港 与 Vercel→香港 都受此影响）→ 属基础设施层（定 Vercel region / 上连接池 pgBouncer-Supavisor），超本 Spec 代码范围，回报给用户定夺，不要在代码里抬 timeout 蒙混。
- ⚠️ 注意：本机→香港 的延迟**未必等于** Vercel→香港；本机 PASS 不完全代表生产 PASS，但本机 FAIL 基本能定位是 plan 还是传输。

### 6B. 写类（需要一套带全 schema 的测试 Supabase）
写类（值得投/不适合/撤销/关注公司覆盖/radar state）写 **Supabase 用户表**，需要把迁移应用上去：
1. 备一套**测试 Supabase**（不要用生产）。取其直连串（端口 5432，含密码）。
2. 应用**全部**迁移（不只 161-163；测试库要有完整 schema 才能跑）——用仓库脚本一把过：
   ```bash
   SUPABASE_DB_URL="<测试库直连串>" bash scripts/db-migrate.sh
   ```
   （脚本按序 apply 001→163，幂等；161/162/163 即本轮新表/列/RPC。）
3. 在 worktree `.env.local` 把 `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY`/`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` 指向**测试 Supabase**；`JOBS_DATABASE_URL` **保持指向香港库**（岗位用真实数据，动作 API 会拿真岗校验存在性后把 job_actions 写进测试 Supabase）。
4. 在测试 Supabase Auth 建测试账号 `test@jobradar.local / test123456`。
5. `npm run dev` → `localhost:3000` 登录，按 §5 的 🔵 项（C 动作闭环 / E 关注公司 / §5.3 越权）逐条走，并抽查 `events` 表无 PII。
6. 复验本单 §5 表里 P0-4/5/6 的 🔵：动作失败不记成功事件、缺表前各路由返回对应 `*_schema_unavailable`、极宽画像命中 4000 行时 candidate_capped=true。

应用迁移后，§2.1 说的「写类未验」即可全部转为真实结论。回报仍按 §4。
