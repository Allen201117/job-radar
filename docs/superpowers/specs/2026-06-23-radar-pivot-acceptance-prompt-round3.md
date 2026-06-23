# 第三轮验收启动 Prompt（整段粘给独立验收 agent）

> 用法：把下面「===」之间的整段复制给一个独立验收 agent 即可启动。它自带定位与步骤，依赖的细节在仓库三份文档里。

===

你是**独立验收 agent**。任务：对「个人机会雷达 A–E 转型」的**第二轮缺陷修复**做复验，目标是**找出仍不通过的阻断项**（不是确认通过）。结论只许基于你**亲自跑出的证据**——不得引用历史结论、不得只回「已完成/测试通过」、不得用「代码看着对」冒充 live 通过。

## 代码位置与硬约束
- Worktree：`/Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623`，分支 `draft/radar-pivot-0623`，HEAD 应为 `076f487` 一带，**未 push**。
- 硬约束：**不要 push、不要 merge 到 main、不要打印或提交 .env/密钥**；**未经用户授权不对生产库应用迁移或写数据**（可对**测试库**应用迁移）。

## 先读这三份（权威依据）
1. 基线验收手册 `docs/superpowers/specs/2026-06-23-radar-pivot-acceptance-AtoE.md`：A–E 全量验收项 + §2 产品红线 + §5.3 越权核查 + §7 生产只读核查。
2. 复验交接单 `docs/superpowers/specs/2026-06-23-radar-pivot-reverify-prompt.md`：**§5 = 上轮 6 个阻断项的逐条处置表**（标了 🟢可读/单测确认、🟡代码已改待 live、⚪需授权）；**§6 = 用户已拍板的「测试库验收」步骤（6A 性能 / 6B 写类）**。
3. 设计 Spec `2026-06-23-personal-opportunity-radar-pivot-design.md`：口径有疑问回查，不要自行放宽。

## 执行（按序，边做边记实际输出）
1. **自动化门**（必跑）：
   ```
   cd /Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623
   node --test tests/*.test.js                                          # 期望 453 pass / 0 fail
   python3 -m unittest discover -s crawler -t crawler -p "test_*.py"    # 期望 OK
   npx tsc --noEmit                                                     # 期望 0 错
   npm run build                                                        # 期望成功
   bash scripts/check-migrations.sh                                     # 期望 168 通过
   git diff --check                                                     # 期望干净
   ```
   任一不绿 → 直接判不通过并贴输出。
2. **复验上轮 6 个阻断项**（对照 reverify §5 表，逐条给「已关闭/未关闭/未验」）：
   - 🟢 ③ 行业门：读 `lib/opportunities/eligibility.ts` 的 `industryState`，确认拒绝判定**直接调 `jobIndustryAllowed()`**（不再另造）；跑 `node --test tests/opportunity-eligibility.test.js`。
   - 🟢 ④ 埋点：读 `components/JobCard.tsx` 的 `callActionApi`，确认 `track()` 在 **fetch 成功分支之后**、且入口有 `actingRef` 同步去重。
   - 🟢 ⑤ schema 缺失：读 `lib/opportunities/schema-errors.ts` + 三路由（preferences/radar/job-actions）复用它；跑 `node --test tests/schema-errors.test.js`。
   - 🟢 ⑥ candidate_capped：读 `lib/jobs-store/opportunities.ts` `recallViaStore` 末行 `rows.length >= limit`。
   - 🟡 ① 性能：按 **§6A**，在**正常网络**机器上 `set -a; source .env.local; set +a` 后 `npx tsx scripts/verify-opportunity-recall.ts`。贴三次耗时+中位+PASS/FAIL。FAIL → 贴 `EXPLAIN (ANALYZE)`，判定是 plan 还是传输/跨区（plan 快总慢=跨区延迟，属基础设施层，回报用户定，**不接受抬 timeout 蒙混**）。注意本机→香港 ≠ Vercel→香港，本机 PASS 不完全代表生产。
   - ⚪ ② 迁移：见步骤 3。
3. **写类 live**（reverify §6B）：
   - 有测试 Supabase → `SUPABASE_DB_URL="<测试库直连串>" bash scripts/db-migrate.sh` 应用全部迁移 → worktree `.env.local` 的 4 个 Supabase 变量指向测试库（`JOBS_DATABASE_URL` 仍指香港）→ 测试库 Auth 建 `test@jobradar.local/test123456` → `npm run dev` 登录 → 走基线手册 §5 的 **C 动作闭环 / E 关注公司 / §5.3 越权**，并抽查 `events` 表无 PII（email/resume/reason_text/标题/公司名/jd_url）。
   - 重点复验：动作 API 人为失败时**不发成功事件**、卡片回滚；缺表时各路由返回对应 `*_schema_unavailable`(503) 而非假成功；极宽画像命中 4000 行时 candidate_capped=true。
   - **没有测试库就如实标「写类未验（无测试环境）」**，不要伪造。
4. **§2 红线**复核：用无关岗位填满队列 / 露内部分数 / 把不可确认岗伪装「今天确认」/ 负反馈自动改用户偏好——任一出现即判不通过。

## 回报格式（必须齐全）
① 自动化门每条实际结果；② 6 阻断项逐条（已关闭/未关闭/未验+原因）；③ 性能中位耗时 + 是否达标（+不达标的 EXPLAIN 与定位）；④ 是否应用了测试迁移、哪些写类 live 真过；⑤ 仍未验项 + 原因；⑥ 残留/新发现缺陷（根因 + 复现步骤 + 实际 vs 期望，分「必须改/建议改」）；⑦ `git status --short` + `git log --oneline -6`。
最终给一句**通过 / 不通过**结论。**不得 push。**

===
