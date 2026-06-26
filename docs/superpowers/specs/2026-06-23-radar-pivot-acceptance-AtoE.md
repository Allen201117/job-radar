# 个人机会雷达转型 · 验收手册（Workstream A–E）

> 给「验收 agent」用：照此独立验收，不需先读全部源码。
> 被验对象：求职雷达「岗位聚合 → 个人机会雷达」转型的 **A/B/C/D/E** 五个 workstream（**F 邮件+消费指标本轮未做**，见 §6）。
> 权威设计：`docs/superpowers/specs/2026-06-23-personal-opportunity-radar-pivot-design.md`（下称 Spec）+ `docs/产品转型方案-从岗位聚合到个人机会雷达.md`。
> 验收结论以「Spec 条款 + 本手册步骤」为准；有歧义回去查 Spec，不要自行扩大或放宽。

---

## 0. 一句话背景

把 `/today` 变成唯一主产品「今日机会」：用户设一次目标，系统每天从已保鲜的官方岗位库里，用**硬门 + 可解释排序**生成「值得今天处理的少量机会队列」，并把 crawler / 源 / 刷新等技术链路从前台收起。判定准确性 = 产品命脉，验收重点就是它。

---

## 1. 被验代码在哪

- **Worktree**：`/Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623`
- **分支**：`draft/radar-pivot-0623`（基于 origin/main 的 `ab3cade`）
- **提交**（`git log --oneline`）：
  - `4972ec5` 文档（两份设计文）
  - `86d7b90` A 引擎纯函数 + 数据模型 + 召回
  - `0a23bf4` B+C 今日机会 Feed + 动作闭环
  - `f6a3014` D 信息架构降级主动爬取
  - `38ff930` E 关注公司与覆盖请求
- ⚠️ **不要在旧分支 `claude/compassionate-ardinghelli-b8a957` 上验**（它落后 main 18 提交、缺迁移 160/行业门）。
- ⚠️ 验收期间**不要 push、不要 merge 到 main**（push = 上线 + 自动跑迁移，需用户拍板）。

---

## 2. 环境前提

| 项 | 说明 |
|---|---|
| Node/npm、Python3.11 | 运行单测 / build / crawler 单测 |
| `.env.local` | 须在 worktree 根（`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`，香港库走 `JOBS_DATABASE_URL`）。缺了就从主仓库 `/Users/bytedance/Desktop/求职雷达/.env.local` 复制（**只 cp，不要打印内容**）。 |
| `node_modules` | worktree 独立，没有就先 `npm install --prefix <worktree>` |
| 测试账号 | `test@jobradar.local` / `test123456`（需已在 Supabase 建好） |
| 沙箱限制 | 沙箱可能禁端口/断网 → live 登录、连库、起 dev server 多半要在**用户本机**跑；自动化门（§3）不需要网络。 |

> ⚠️ **build 与 dev 不要同时跑**（会改写 `.next` 导致 dev 静态资源 404）。先 build 验证，要做浏览器走查就 build 完重启 `npm run dev`。

### 2.1 写类流程的关键前提：迁移必须先应用

本轮新增迁移 **161 / 162 / 163**（`supabase/migrations/`）。它们建了 `user_radar_state`、`notification_settings`、`company_watch_requests` 表，给 `job_actions` 加了负反馈列、删了跨库外键、加了 `set_job_primary_action` RPC。

- **读类**（Today Feed 渲染、Jobs、Landing、导航）**不强依赖**这些迁移，可直接验。
- **写类**（值得投/不适合/已投递、保存偏好的覆盖同步、关注公司队列）**依赖**这些迁移；未应用前会报错（表/函数不存在）。
- 迁移是 **push 到 main 时由 `.github/workflows/migrate.yml` 自动应用**的。验收写类前二选一：
  1. 让用户 push（迁移自动上生产）后，在线上或本机连生产库验；**或**
  2. 在一个测试 Supabase 上手动 apply `161/162/163`（`psql $SUPABASE_DB_URL -f supabase/migrations/16x_*.sql`，仅测试库），本机 dev 指向它验。
- 若两者都不便，则只完成 §3 自动化门 + §5 读类走查 + §7 代码结构核查，并在报告里写明「写类未 live 验证（迁移未应用）」。**不要**把"代码看着对"冒充 live 通过。

---

## 3. 自动化回归门（必跑，先决条件）

在 worktree 根依次执行，记录实际输出：

```bash
cd /Users/bytedance/Desktop/求职雷达-wt-radar-pivot-0623
node --test tests/*.test.js                                            # 期望：pass 426 / fail 0
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"      # 期望：OK（约 409 tests）
npx tsc --noEmit                                                       # 期望：退出码 0、无 error TS
npm run build                                                          # 期望：成功，列出所有路由
bash scripts/check-migrations.sh                                       # 期望：通过（168 个迁移、前缀无新增重复）
git diff --check                                                       # 期望：无空白错误（工作树应是干净的）
```

引擎纯函数可单独细看（共 60+ 用例，覆盖 Spec §18）：
```bash
node --test tests/opportunity-*.test.js tests/company-normalize.test.js
```
对应：`opportunity-freshness`(§18.2)/`-profile`(§18.1)/`-eligibility`(§18.3)/`-scoring`(§18.4)/`-grouping`(§18.5)/`-api-security`(§18.6, 输入校验部分)/`company-normalize`(§18 公司归一)。

**任一不绿 = 验收不通过**，记录失败项与输出后即可回报。

> 说明：API 路由本体（需 Next 运行时）未单测；其输入校验逻辑抽到 `lib/opportunities/action-input.ts` 已单测；401/越权由 `requireUser`/`requireAdmin` + RPC `auth.uid()` + RLS 保证（见 §5.3 手工核查）。

---

## 4. 产品不变量（红线，看到违反即判不通过）— Spec §2

逐条对照（多数可在 §5/§8 的走查与只读核查中确认）：

- **质量**：Today 只出 `status='active']`；JD 正文有效长度 ≥60；`jd_url` 过官方质量门；active `canonical_jd_url` 唯一约束未被移除；不把无法确认在招的岗伪装成"今天确认"。
- **匹配诚实**：排序为确定性规则、**不接 LLM**；不显示虚假百分比准确率；只展示档位+具体原因、不露内部权重；硬条件明确不符的不进 Today；信息缺失与明确不符区分对待；**列表不足宁可少，绝不用无关岗位填满**。
- **用户控制**：负反馈**不自动改用户偏好**；不做自动投递；打开官网不自动标"已投递"。
- **架构边界**：jobs 仍在独立 PG；未在本轮迁 jobs 表；未引入 Redis/向量库/消息队列/新搜索服务；Opportunity Engine 权威实现只在 TS `lib/opportunities/`。

---

## 5. 人工验收 · 按 Workstream（核心）

> 起 dev：`npm run dev` → `http://localhost:3000`，用测试账号登录。读类可直接走；写类先确认 §2.1 迁移已应用。

### A. 机会引擎（Spec §6）— 主要靠单测 + 只读核查
- [ ] §3 中 `opportunity-*` 单测全绿（硬门顺序、Score V2 权重、freshness SLA、分区/封顶、原因生成）。
- [ ] 抽查 `lib/opportunities/eligibility.ts`：硬门顺序 = active→summary≥60→source 停用→freshness(stale/unknown 拒)→排除词→已动作→方向→城市→阶段→学历→行业；命中目标公司绕过行业拒绝。复用既有 `keywordMatchTier/recruitmentCategory/educationMatch/jobIndustryAllowed/normalizeChinaCity/excludeJobs`，**没有另造近似规则**。
- [ ] `scoring.ts` 档位边界：≥70 高匹配 / ≥45 相关 / 30–44 拓展 / <30 不展示；Today 主队列最低 45。

### B. 今日机会 Feed（Spec §4/§7）
- [ ] **未登录**访问 `/today` → 跳 `/login?next=/today`。
- [ ] 登录但**画像不全**（没设目标城市或没设岗位/关键词/公司）→ 显示 onboarding（标题「先告诉我们你想找什么」+「设置求职目标」「上传简历生成画像」两按钮），**不展示任何随机岗位**。
- [ ] 画像完整 → 顶部三指标只有「自上次查看新增 / 高匹配待处理 / 今天确认仍在招」（**没有**已收藏/已投递/已忽略）。
- [ ] 队列按固定分区出现：**新出现 / 高匹配待处理 / 可以拓展看看 / 等待再次确认**；主队列（前三区合计）**不超过每日上限（≤30）**。
- [ ] 每张卡片有匹配档位 + **最多 4 条具体原因**（方向/城市/阶段/行业/公司/技能/新鲜度），**不出现"未知"作为正向理由**，**不露内部分数**。
- [ ] Today 页**没有** crawler / 刷新按钮 / 发掘按钮 / 抓取数量 / source 数量 / workflow 状态。
- [ ] 「等待再次确认」区只在 verified 队列 <5 时出现，且每条标明"最近一次确认已超过常规更新周期"。

### C. 动作闭环与负反馈（Spec §8）— 写类，需迁移已应用
- [ ] 点「值得投」→ 卡片离开 Today + 底部可撤销 toast（5s）；之后 `/saved`（已改名「值得投」）能看到它。
- [ ] 点「已投递」→ 离开 Today；`/applied` 能看到。
- [ ] 点「不适合」→ **必须先选一个原因**（方向不对/城市不合适/…），未选不写入；选后卡片移出 + 可撤销 toast。
- [ ] toast「撤销」5 秒内点 → 岗位恢复回队列。
- [ ] 打开官网（卡片标题或「查看官网」）→ **瞬开**新标签（不卡顿、不被校验阻塞）。
- [ ] 失败回滚：断网点动作 → toast「操作失败，已恢复原状态」且卡片状态回退（可在 devtools 模拟 `/api/job-actions/*` 失败）。

### D. 信息架构（Spec §3/§9/§12/§7.6）
- [ ] 顶部导航顺序 = **今日机会 / 搜索岗位 / 关注与偏好 / 值得投 / 已投递**；**没有**「职业路径」「个人主页」一级入口；「个人主页」在右上角**账号下拉菜单**里；登录后点 Logo → `/today`。
- [ ] `/jobs`：Hero 改「探索完整官方岗位库」；**没有**「查已有/刷新对口公司/发掘新公司」三磁贴；有一个「搜索」按钮，改筛选会自动搜；空结果文案给「放宽筛选条件 / 添加关注公司」，**不引导联网发掘**。
- [ ] 手动抓取仅在 `NEXT_PUBLIC_MANUAL_CRAWL_UI=true` 时，于 `/jobs` 底部「高级工具」折叠区出现（默认环境**看不到**）。
- [ ] Landing（`/`）：主标题/CTA/四卖点为机会雷达口径（企业官网直达 / 持续确认仍在招 / 按你的目标筛选 / 每天只给少量机会）；**没有**「800+ 源」「发掘新公司」「AI 自动化」当主卖点。
- [ ] `/applied` 对**已被清理的岗位**显示「原岗位已下线」且不给失效链接（历史不丢）。

### E. 关注公司与覆盖请求（Spec §10）— 写类，需迁移已应用
- [ ] `/preferences` 有独立「关注公司」块 + 新增「目标行业」项；每日上限输入范围 5–30。
- [ ] 填一个**已覆盖**公司（库里有 enabled source，如 `字节跳动`）保存 → 立即显示「已纳入持续监控」。
- [ ] 填一个**未覆盖**公司（如「示例新公司XYZ」）保存 → 立即显示「已记录，等待接入官方招聘源」；**不触发任何浏览器/抓取等待**（保存秒回）。
- [ ] 管理员（`profiles.role='admin'`）打开 `/sources` → 有「用户希望监控的公司」队列，按人数排序，可标记「确认入口中/已覆盖/暂不支持(填说明)」；标记后该公司在用户偏好页状态相应变化。
- [ ] 文案里**不出现** adapter 名 / parser 状态 / source URL / GitHub Actions / 抓取堆栈。

---

## 5.3 安全/越权手工核查（Spec §15/§18.6）
- [ ] 未登录直接 `curl` `GET /api/opportunities`、`POST /api/radar/open`、`PUT /api/job-actions/<uuid>` → 均 **401**。
- [ ] 用户 A 登录，尝试对 A 不拥有的 job 之 action：写入由 `set_job_primary_action` 用 `auth.uid()` 落在 A 名下，**改不到别人**；`company_watch_requests` 用户只能读自己的（RLS）。
- [ ] `PUT /api/job-actions/<uuid>` 传 `action:"ignored"` 不带 `reason_code` → **400**；`reason_text` >200 → **400**；非法 jobId → **400**。
- [ ] 事件 payload 不含 email / resume / reason_text / 岗位标题 / 公司名 / jd_url（抽查 `events` 表新写入行）。

---

## 6. 本轮不做（不要当缺陷报）

- **F 邮件每日摘要 + 管理员消费漏斗指标**：迁移 164 / `/api/notification-settings` / `/api/internal/opportunity-digest` / `.github/workflows/opportunity-digest.yml` / `lib/opportunities/email.ts` / admin 漏斗（Spec §11/§13.2）——**用户明确本轮不做**。
- 连带：`/api/preferences` GET 暂未返回 `notification_settings`（Spec §4.4 列了，等 F 一起补）。
- 因此 Spec §21 完成定义里的第 12 条（管理员真实漏斗）与 §20 场景 5（邮件摘要）、§19 生产核查第 8/9 条**本轮不验**。
- 后台 `/api/refresh`、`/api/discovery/*`、`useDiscoveryPoll`、`CompanyRefreshRecipe` 应**仍存在未删**（核查文件在即可，这是有意保留）。

---

## 7. 生产只读核查（push 上线后做，Spec §19，去掉 F 项）

连生产（香港 jobs 库 + Supabase）只读核对一个真实用户的 Today：
1. `/api/opportunities` 返回的 job **全部 `status='active'`**。
2. Today 每个 job 的 summary 去空白长度 **≥60**。
3. Today 无 `canonical_jd_url` 重复。
4. Today 不含该用户已 saved/ignored/applied 的岗。
5. freshness 档位与 `last_seen_at` + source `crawl_method` 推导一致（http 18/36h、playwright 36/72h、manual 72/144h）。
6. 用户 A 的反馈不影响用户 B 的队列。
7. `company_watch_requests` 行归属正确（user_id 对得上）。

> 连库只读查询走 `db-report` 风格的只读 psql 或 REST；沙箱里连库需绕代理（见记忆 `job-radar-live-db-access-from-sandbox`）。

---

## 8. Spec §21 完成定义对照（A–E 范围）

逐条打勾（第 12 条属 F，本轮 N/A）：
1. 登录用户默认进今日机会 ☐  2. Today 不依赖主动爬取 ☐  3. 每岗过质量/相关/freshness 准入 ☐  4. 稳定分区且 ≤30 ☐  5. 可完成值得投/不适合/已投递 ☐  6. 不适合原因结构化 ☐  7. 未覆盖公司形成异步请求 ☐  8. Jobs 不再平铺三链路 ☐  9. 手动刷新/discovery 后台未删 ☐  10. 新 API 有 ownership/auth（单测+手工）☐  11. 回归门全过 ☐  12.（F，N/A）  13. 文案不承诺全市场/自动投/保面试 ☐  14. 无 mock/假计数/「pending 即成功」☐

---

## 9. 怎么回报

给一份结论，包含：
1. **自动化门**：每条命令的实际结果（通过/失败 + 关键输出）。
2. **人工走查**：A–E 每个勾选项的「通过 / 失败 / 未验(原因，如迁移未应用)」。
3. **§21 对照表**：哪些满足、哪些不满足。
4. **缺陷清单**：每条带「Spec 条款 + 复现步骤 + 实际 vs 期望」，区分「必须改 / 建议改」。
5. **未验范围**：明确写出因环境（迁移未应用/沙箱断网/未 push）没 live 验证的部分——**不要用"代码看着对"冒充 live 通过**。

发现违反 §4 红线（尤其"用无关岗位填满"、露内部分数、把不可确认岗伪装"今天确认"、负反馈自动改偏好）→ 直接判该项不通过。
