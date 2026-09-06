# `jobs.status_reason` 设计卡（待创始人拍板，**尚未动手**）

> 状态：**设计稿，未实施**。写卡人：admiring-kilby-ed1334 session（2026-09-05）。
> 边界：改的是**香港热表 jobs（45 万行）的结构**，超出「推 main」的授权范围，
> 必须创始人拍板后才动。总管已明确不放行。

## 0. 一句话

`jobs.status` 只说岗位「现在是什么状态」，不说「**为什么**变成这样」。
今天这次误报证明：缺了成因，正确的清理和真实的事故在下游长得一模一样。

---

## 1. 不做的代价（先看这段，它决定值不值）

**2026-09-05 完整事故链**（每一步都没人犯错，但差点酿成错误修复）：

1. hotjob 门 1 上线，拦下 7 个「官网不存在」的死租户源。
2. 这些源名下 **992 个 active 岗**被我标 `removed`（jd_url 点开是「官网不存在，无法继续访问!」）。
3. 做必投口径的 session 复核北极星，看到 **中国中化 388→0、中信银行信用卡中心 164→0**。
4. 它手里只有计数，`status='removed'` 不告诉它为什么 → **判成「供给回归」，准备转给抓取线去修**。
5. 而「修」的方向会是 **去恢复一批死链** —— 与「jd_url 准确性高于一切」正面冲突。
6. 最后靠总管**人肉读了 18 条 session 的 transcript**、对上「992 对 992」才拦下。

📌 **核心**：「整家公司归零」有两种成因、处置**完全相反**——
① 真回归（该去修抓取）② 正确清理（什么都不用做）。
**计数分不开这两者，只有成因能。** 而下游（北极星、ops-watchdog、审阅者）拿到的只有计数。

⚠️ 这个形状**不是孤例**，是本项目反复出现的一类病：
CLAUDE.md 已有的「列表里没有 ≠ 已撤岗」「接口返 0 不能证明对方没开」都是同一个根——
**状态本身不携带成因，看的人只能猜，而猜错的方向往往是"去恢复本该消失的东西"**。

**不做的代价 = 每次批量治理都要靠一个人肉总管去对账。** 今天有，平时没有。

---

## 2. 为什么现在还不急（诚实边界）

`ops_runs` 台账（2026-09-05 已落地）**已经覆盖了今天这个真实故障模式**：
批量操作由动手方写一行 `module='manual_cleanup'` + `reason_code` + 逐公司条数 + 回滚说明。

- ✅ 覆盖：**一次性批量**改 status / 删行（今天出事的正是这类）。
- ❌ 不覆盖：**逐行的自动流转**（sweep 判死一个岗、list-absence 撤一个岗、重抓复活一个岗）。
  这些每天几千行，不可能一行一条台账；要知道「这一个岗为什么没了」只能靠 `status_reason`。

**所以这不是急事，是该做对的事。** 建议排在「有人真的开始按岗位级别追因」时做，
或与下一次 jobs 表结构改动**搭车**（避免为一列单独走一次 45 万行的迁移）。

---

## 3. 枚举值域

新增列 `status_reason text`，**带 CHECK 白名单**（与 `status` 同风格），允许 NULL（存量与未知）。

| status | status_reason | 含义 | 写入方 |
|---|---|---|---|
| `expired` | `detail_closed` | 逐岗 detail 探活确认撤岗（hotjob state=1017 / wt req_state=9501 / workday 404） | `enrich_backlog` / `enrich.py` / `jobs_db.mark_expired` |
| `expired` | `spa_detail_gone` | 浏览器审计：SPA 页面渲染出「职位不存在/已下线」 | `audit_dead_links.py` |
| `expired` | `list_absent` | list-absence：源列表返全集且该岗缺席 | `jobs_db.sweep_absent_jobs` |
| `removed` | `portal_gone` | 整个租户门户已不存在（hotjob 门 1 / 飞书租户 404） | 批量治理脚本 |
| `removed` | `channel_unpublished` | 渠道未发布，页面永远转圈（hotjob 门 2） | 批量治理脚本 |
| `removed` | `bulk_collapse` | 门店批量同质副本折叠 | `collapse_bulk_duplicates.py` |
| `removed` | `attribution_wrong` | 归属核验不通过（国聘张冠李戴那类） | `audit_iguopin_attribution.py` |
| `removed` | `list_missing` | 抓取漏看（可复活的弱信号，现有 `removed` 默认语义） | `jobs_db` upsert |
| `active` | `NULL` | 在招无需理由 | — |

⚠️ **值域要小、要正交**。宁可先上 5 个再加，不要一次铺 15 个——
枚举一旦被写进 45 万行就很难改名（参考 CLAUDE.md「改 CHECK 是全量重建」那条碑）。

⚠️ `error` 状态目前库里 0 行，先不给它 reason。

---

## 4. 所有写入点清单（2026-09-05 实测枚举，共 11 处）

**Python（爬虫侧，`JOBS_DATABASE_URL` 直连）**
1. `crawler/jobs_db.py:81` — upsert 的 `_update_set_clause`，status CASE（**最危险的一处，见 §5**）
2. `crawler/jobs_db.py:353` — `sweep_absent_jobs` → `expired`
3. `crawler/jobs_db.py:394` — `d.setdefault("status","active")` 插入默认
4. `crawler/enrich_backlog.py:174` — JobClosedError → `expired`
5. `crawler/audit_dead_links.py:338` — SPA 审计 → `expired`
6. `crawler/collapse_bulk_duplicates.py:93` — 折叠 → `removed`
7. `crawler/audit_iguopin_attribution.py:117` — 归属错 → `removed`

**TypeScript（app 侧，`lib/jobs-store/`）**
8. `lib/jobs-store/write.ts:81` — upsert 的 status CASE（**必须与 ①字节级同口径**）
9. `lib/jobs-store/write.ts:179` — `markJobExpiredById`（展示时探活）→ `expired`

**删行（不是改 status，但同样让岗位消失）**
10. `.github/workflows/purge-expired.yml:44` — `delete from jobs where status='expired'`
11. `crawler/gap_funnel.py:181` / `crawler/campus_board_verify.py:79` — 验收不过删整源的岗

⚠️ 第 10 项意味着 **`expired` 的 reason 活不过当天**（purge 会删行）。
所以 reason 对 `expired` 的价值主要在**当天的可观测**；长期审计价值在 `removed`。
若要长期留证，需要另立 `job_status_events` 表（**本卡不含，属于范围扩张**）。

---

## 5. upsert 语义 —— 最容易埋雷的一处

**结论先行：`status_reason` 必须与 `status` 绑成一对同进同退，绝不能独立走 COALESCE。**

现有 status 写法（`jobs_db.py:81`，`write.ts:81` 同口径）：

```sql
status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE %s END
```

即 **expired 黏住**（detail 探活确认撤岗的岗，列表重抓不许复活——wt 52% / hotjob 71% 的列表
仍夹带已关闭岗，裸 `status=%s` 会把 sweep 判死的岗每天刷回 active）。

### 🕳 雷点：把 `status_reason` 也塞进 `_PRESERVE_IF_EMPTY` 是**错的**

`_PRESERVE_IF_EMPTY` 的写法是 `COALESCE(NULLIF(%s,''), 列)`，它只在**新值为空**时保留旧值。
但列表重抓时 adapter 完全可能带一个**非空**的默认 reason（比如 `list_missing`）——
此时 `COALESCE` 不起作用，会把一个 `status` 仍被 CASE 保持为 `expired` 的岗，
其 reason 覆盖成 `list_missing` ⇒ **status 说「探活确认撤岗」，reason 说「抓取漏看」，自相矛盾。**

（这正是总管提示的「对非空派生值 COALESCE 不起作用」，与 2026-06-20 summary 被抹掉那个坑
同源但**不同解**：summary 的正解是 COALESCE，status_reason 的正解不是。）

### ✅ 正解：同一个 CASE 的两个分支

```sql
status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE %s END,
status_reason = CASE WHEN jobs.status = 'expired' THEN jobs.status_reason ELSE %s END
```

**不变量：`status` 保留时 `status_reason` 必须一起保留；`status` 改变时 `status_reason` 必须一起改变。**
两者永远不得由不同的表达式独立决定。

⚠️ 占位符计数：两列各消费一个 `%s`，与 `_row_tuple(job, cols)` 的顺序对齐——
`_update_set_clause` 现有注释已强调「每列恰好消费一个 %s」，加列时别打破。

⚠️ **两端必须字节级同口径**（`crawler/jobs_db.py` 与 `lib/jobs-store/write.ts`）。
项目已有先例：canonical_jd_url 归一逻辑活在三处、drift 会导致去重失效。

### 回归测试（缺一不可）
- `crawler/test_jobs_db_upsert.py`：expired 岗被列表重抓后，`status` 与 `status_reason` **双双不变**。
- 新增变异测试：把 `status_reason` 的 CASE 换成 COALESCE，上面那条**必须变红**
  （否则等于没测到，参考 `tests/geo.test.js` 做过变异验证的做法）。

---

## 6. 迁移与回滚

**迁移**（走 `jobs-db/schema.sql` + `gh workflow run jobs-db-migrate`，**不是** supabase/migrations）：

```sql
alter table jobs add column if not exists status_reason text;
alter table jobs add constraint jobs_status_reason_check
  check (status_reason is null or status_reason in (...));
```

- ⚠️ **加列本身要快**：`add column` 带 NULL 默认在 PG 11+ 是元数据操作，不重写表。
  **但 CHECK 约束会全表扫 45 万行** → 建议 `not valid` 先加、再 `validate constraint`，避免长锁。
- ⚠️ 不回填存量：50,736 行 `removed` + 480 行 `expired` 的历史成因**已经不可考**，
  硬塞一个猜的值比 NULL 更糟（本项目碑：「没验证的断言比没有断言更糟」）。
  NULL 的语义就是「本列上线前的旧数据」。
- ⚠️ 上线顺序：**先推代码、再加列**？不行——代码写这一列时列还不存在会炸。
  正确顺序是 **先加列（可空、无约束）→ 再推代码 → 观察一轮 → 最后加 CHECK**。
  （对照 2026-09-05 geo 回填踩的坑：顺序反了会被正在跑的 CI 用旧代码刷回去。）

**回滚**：`alter table jobs drop column status_reason;`
—— 纯新增列、无任何读取方依赖它做判断（**这是设计约束：不许让任何筛选/排序/北极星依赖它**，
它只作诊断用途），所以 drop 即完全回滚，不影响任何现有链路。

---

## 7. 明确不做的（防范围膨胀）

- ❌ 不建 `job_status_events` 历史表（要长期留证再单独立项）。
- ❌ 不让任何**用户可见**的查询依赖 `status_reason`（它是运维诊断字段，不是产品字段）。
- ❌ 不回填存量。
- ❌ 不在本卡内改 `ops_runs` 台账规矩（那条已独立生效，且**继续保留**——
  两者互补：台账管「一次批量操作」，reason 管「单个岗位」）。

---

## 8. 验收（做的时候照这个验）

1. 列已加、CHECK 已 validate、`\d jobs` 可见。
2. 上面那条**变异测试**：把 CASE 改成 COALESCE，`test_jobs_db_upsert` 变红。
3. live：找一个 `expired` 岗，跑一次该源的列表重抓，回读确认 `status` 与 `status_reason` 都没变。
4. live：跑一次 `collapse_bulk_duplicates --apply`（小公司），回读确认新 removed 行带 `bulk_collapse`。
5. 四件套 + `npm run lint` 全绿。

---

## 9. 相关记忆 / 碑

- `job-radar-crawler-health-audit` §「指标掉了有两种成因，处置相反」（本卡的直接起因）
- `job-radar-summary-wipe-rootcause`（COALESCE 保留的**正例**，与本卡的**反例**对照看）
- `job-radar-dead-job-resurrection-rootcause`（status CASE / expired sticky 的由来）
- CLAUDE.md「列表里没有 ≠ 已撤岗」「expired 死岗 = 永久删除回收空间」
