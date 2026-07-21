# 校招洞察（Campus Recruitment Insights）P2 设计

> 状态：**设计定稿**（2026-07-21，5 个未决项已与创始人 brainstorm 拍板）→ 下一步 writing-plans → 实现
> 2026-07-20 起草 · 2026-07-21 定稿 · 关联：[[job-radar-campus-zone]]（P1 已上线）、主设计 `docs/superpowers/specs/2026-07-20-campus-recruitment-zone-design.md`（§8 P2 展望）

## 0. 一句话

P1「校招专区」`/campus` 已上线（公司卡 + 诚实窗口徽章 = "此刻开没开"事实层）。**P2 给这个面补上"该什么时候投"的时间/批次洞察**：往年提前批/正式批几月开、往年几月结束、当前是不是黄金期，卡片上直接显一行、点进抽屉看时间轴。红线不变：可靠度分层、诚实标"据往年+年份"、宁缺不编。

## 1. 背景与目标

- **产品**：求职雷达，公开企业官网岗位雷达。P1 窗口徽章（🟢招聘中 / ⚪当前没看到 / ⚙️待接入 / ⏳数据待更新）是"此刻在招没在招"的**事实层**。
- **P2 目标**：补校招求职者最大的**信息差**——
  1. **时间信息**：往年提前批/正式批几月开、往年几月招满/结束、**招聘黄金期**。
  2. **批次时机**：把提前批/正式批当作结构化的时间维度（"提前批约 7 月、正式批 8–9 月"）。
  3. **显式展示**：时间信息一部分**直接显示在洞察抽屉外面**（校招卡片上一行），点进抽屉看时间轴详情。
- **红线**（继承 P1 + 产品 DNA）：可靠度分层、诚实标注来源与年份、宁缺不编。

## 2. 已有可复用的零件（别重造）

| 零件 | 位置 | P2 怎么用 |
|---|---|---|
| 洞察系统 Module B | `insight_items` 表（迁移 013/014），维度含 `timing` | 抽屉展示复用；但 timing 只有散文、无结构化芯片，P2 另建结构化底座喂它 |
| 时效字段 + 校验门 | `insight_items.time_window/valid_from/valid_until`；`lib/insight-verification.ts` | 时效表达 + 新鲜度分级复用 |
| **招聘窗口时间引擎** | `lib/career-path.ts`：`parseRecruitingMonths()`(:35 文本→月份集)、`timingStatus()`(:76) | 月份解析/黄金期判定的**思路**复用（P2 新纯函数吃结构化 month_start/month_end，不重解析文本） |
| **10 家头部种子数据** | `014_seed_career_insights.sql`（timing 维度，payload.phase 存"秋招提前批7月/正式批8-9月/春招3-4月"字符串） | P2 迁移解析成结构化 observation 灌新表当 base |
| 洞察抽屉 | `components/CompanyInsightDrawer.tsx`（timing 分区、`PayloadChips` 只处理 hiring/listing） | 抽屉时间轴挂在 timing 分区顶部；`/api/insights` 响应扩 `recruitment_cycles` 喂它 |
| 公司归一匹配 | `lib/insight-match.ts` | 观测按公司名/别名匹配到校招卡的公司 |
| LLM 洞察管线 | `crawler/insight_engine.py`(timing prompt) + `app/api/insights/admin/ai-draft` | P2d 可选：产往年规律 draft（必人工核验才展示） |
| P1 校招专区 | `app/campus/`、`lib/campus-zone.ts`、`lib/jobs-store/read.ts` 的 `getCampusZone` | 卡片时间线行 + SSR 读观测挂在这里 |

**关键现状**：时间窗能力（种子 + career-path 引擎 + LLM prompt）都有，但**孤立在 `/path` 页 + 只 10 家 + 非结构化字符串**。P2 = 结构化 + 扩覆盖（塌陷行业优先）+ 接进校招专区主路径。

## 3. 可靠度分层（三层，P1 已做第一层）

| 层 | 信息 | 可靠度 | 标注 | 状态 |
|---|---|---|---|---|
| ① 事实 | 此刻窗口开没开（🟢/⚪徽章） | 最高（纯抓取派生） | 直接展示 | ✅ P1 已上线 |
| ② 往年规律 | 往年提前批/正式批月份、黄金期、往年结束 | 中 | **"据往年 + 具体届别年"**，人工核验 | 🔜 **P2 本期** |
| ③ 今年精确日期 | 今年 X 月 X 日截止/开放 | 最难 | 只在有官方校招公告源时显示，拿不到绝不编 | P3 |

**季节感知是"解释层"，不污染"事实层"**：卡上 P1 徽章说"此刻在招/没看到"（事实）；P2 在下方另起一行"据 2026 届往年 · 提前批约 7 月…现处黄金期"（据往年）——两者视觉/语义分开，往年规律绝不改写此刻事实态。

## 4. 决策定稿（5 个未决项，2026-07-21 与创始人拍板）

### D1（原 Q1）数据覆盖策略 = **塌陷行业优先**

- 迁移把现有 10 家互联网头部种子（`014` 的 phase 串）解析成结构化 observation 灌新表当 base。
- **优先给供给塌陷行业（传媒 / 物流 / 教育 / 金融）的必投头部公司**建往年规律，与"供给轨补源"同向发力（时间洞察 + 补校招源互相强化）。
- 供给方式 = **admin 手工录入 + 核验过门**为主；LLM 辅助草稿（D-supply P2d）为可选加速。
- **诚实边界**：塌陷行业的往年规律本就更难查证——查不到官方/可信规律的观测停在 `draft`、不展示。覆盖 = 过核验门的部分，宁缺不编。

### D2（原 Q2）卡片时间线行措辞与视觉 = **紧凑一行 · 事实优先**

- 徽章行下方**浅色小字一行**：`据2026届往年 · 提前批约7月 · 正式批8–9月 · 现处黄金期`。
- `据XX届往年` 前缀 + 浅色弱化，与上方实时徽章（🟢事实层）视觉分离，避免被当成"今年确切日期"。
- 只在该公司有 verified 且未过期观测时显示；无则不显示、不占位、不编。

### D3（原 Q3）新表 ↔ 老 timing 的接法 = **新表当唯一真相源，单向派生，不双写**

- `recruitment_cycle_observations` 是校招时间/批次的**结构化事实底座**。
- 卡片时间线行 + 抽屉结构化时间轴**直接读新表**。
- 老的 timing 文字洞察（`/path` 页、抽屉散文）**原样保留、不动、不反向同步**——各司其职：新表管结构化事实，老 insight_items 管散文叙事。
- **理由**：双写必漂移；新表本就是为"可版本化、绑年份、留证据"而设计，让它当源最干净。

### D4（原 Q4）批次差异范围 = **P2 只做批次时机，难度差异推后**

- P2 把"提前批约 7 月 / 正式批 8–9 月 / 黄金期 / 往年结束"这些**时间事实**做扎实（卡片 + 抽屉时间轴）。
- `batch` 枚举用于**结构化时间**，不做"提前批 vs 正式批 该先投哪批"的难度/流程/HC 经验洞察——那属经验型（grade=experience，需 ≥2 源 + judge 共识），推 P3 或单独轨。

### D5（原 Q5）失效与滚动 = **过期退役不删，年份显式绑定，滚动=追加**

- 往年规律 `valid_until` = 下个招聘季启动前（如 2026 秋招规律 → `valid_until = 2027-06-30`）。
- 过期巡检把 verified 观测退役（不再展示）但**不删**——留作历史底座。
- 年份归属靠 `grad_class`（"2027届"）+ `season` 显式绑定；每年滚动 = **新增一条 observation**（immutable，不覆盖旧的），卡片只展示当前 verified 且未过期的那条。

## 5. 数据模型：`recruitment_cycle_observations`（Supabase 洞察层新表）

> 放 Supabase（不在香港 jobs 库）：属结构化事实/洞察层、低量、可版本化，与 `insight_items`/`company_profiles` 同库同 RLS 模式。FK `company_profiles(id)`。

**字段**（接手 session 按此写迁移；每条 = `(届别, 季, 批次, 事件, 时间)` 一个原子事实）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | uuid pk | `gen_random_uuid()` |
| `company_id` | uuid NOT NULL | FK `company_profiles(id)` ON DELETE CASCADE |
| `grad_class` | text NOT NULL | 毕业届别，如 "2027届"（**"据往年"必绑此，不含糊说"往年"**） |
| `season` | text NOT NULL | CHECK IN ('秋招','春招') |
| `batch` | text NOT NULL | CHECK IN ('提前批','正式批','补录','实习转正') |
| `event` | text NOT NULL | CHECK IN ('开放','截止','黄金期','结束') |
| `time_expr_type` | text NOT NULL | CHECK IN ('精确日期','日期范围','月','历史规律') |
| `value_text` | text NOT NULL | 展示串："约7月" / "8-9月" / "全年滚动" |
| `month_start` | smallint | 1–12，喂"现处黄金期"计算；rolling/精确日期时可空 |
| `month_end` | smallint | 1–12 |
| `date_start` | date | 仅 `time_expr_type='精确日期'`（P3 用） |
| `date_end` | date | 同上 |
| `confidence` | text | CHECK IN ('high','medium','low') DEFAULT 'medium' |
| `evidence_url` | text | 证据链接 |
| `evidence_excerpt` | text | 证据短摘要（禁整段原文，同 insight_sources 合规） |
| `evidence_fetched_at` | timestamptz | 证据抓取时间 |
| `source_kind` | text | official_site / official_notice / manual_curation / llm_draft / public_aggregate |
| `verify_status` | text NOT NULL | CHECK IN ('draft','verified','rejected') DEFAULT 'draft' |
| `valid_until` | date | 失效时间（见 D5） |
| `superseded_by` | uuid | 自引用 FK，修订链：新观测指向它取代的旧观测 |
| `created_by` | text | admin email / 'seed' / 'llm' |
| `created_at` / `updated_at` | timestamptz | DEFAULT now() |

**不变量（务必守）**：
- **事实字段 immutable**：`grad_class / season / batch / event / time_expr_type / value_text / month_* / date_* / evidence_*` 一经写入不 UPDATE。改错 → **新增一条 + `superseded_by` 指向旧的**；仅 `verify_status / valid_until / superseded_by / updated_at` 允许改。写路径（admin API）强制这条纪律。
- **"据往年"必绑 `grad_class`**（2024 规律不能说成泛"往年"；区分"2027 届招聘"与"2026 年发生的招聘"——届别由 grad_class，自然年由 season+month 表达）。
- **LLM 只提取候选 + 标注证据片段**（写 `draft`）；无官方原文 / 无法定位公司+届别 / 日期冲突 → 禁止发布为日期事实。`time_expr_type='精确日期'` 只接受官方校招公告或官方招聘页可复查证据（P3）。

**RLS**（镜像 insight_items）：
- 读：仅 `verify_status='verified'` AND (`valid_until IS NULL` OR `valid_until >= current_date`)。
- 写：admin / service_role。

**索引**：`(company_id, verify_status, valid_until)`、`(grad_class)`。

## 6. 派生 / 读层（D3 落地）

- **纯函数 `lib/recruitment-cycle.ts`**（无 LLM/网络/DB，node --test）：
  - `campusTimelineSummary(observations, now) → { gradClassLabel, batchBits: string[], phaseLabel } | null`：
    - 过滤 verified + 未过期；按批次序（提前批 < 正式批 < 补录 < 实习转正）排。
    - 组展示串 `["提前批约7月","正式批8–9月"]`。
    - 用 `month_start/month_end` 对比 `now().month` 算当前阶段：now 落某批次窗口→"现处提前批/正式批"；晚于全部→"往年这时已近尾声"；早于全部→"往年提前批约 X 月启动"。
    - 无 verified 观测 → 返回 `null`（卡片不显示）。
  - 月份/黄金期比较逻辑思路复用 `career-path.ts`（吃结构化 month，不重解析文本）。
- **SSR 读 `getRecruitmentCyclesForCompanies(companies) → Map<company, Observation[]>`**（Supabase）：campus 页服务端读，公司归一匹配复用 `lib/insight-match`，与 `getCampusZone` 的岗位聚合 merge。放 `lib/insights-store`（或 campus 读层旁）。

## 7. 展示（两处）

**A. 校招卡片上（抽屉外，D2）**：P1 窗口徽章下方一行浅色小字，如 `据2026届往年 · 提前批约7月 · 正式批8–9月 · 现处黄金期`。只在有 verified 观测时显示。视觉与实时徽章分离。

**B. 洞察抽屉内（时间轴）**：`CompanyInsightDrawer` 的 timing 分区**顶部**加结构化时间轴组件（各批次×事件的时间 + 证据来源 + "据 X 届"），散文 timing 洞察保留在下方。`/api/insights` GET 响应扩一个 `recruitment_cycles` 字段喂它（drawer 已 client-fetch 该接口，不新增往返）。

## 8. 数据供给（D1：塌陷行业优先）

三层来源（合规同 Module B v2.0）：
1. **迁移种子**：`014` 的 10 家 timing phase 串解析成结构化 observation（`created_by='seed'`, verified，绑当前届别）。
2. **admin 手工录入 + 核验（P2 主路径）**：优先塌陷行业（传媒/物流/教育/金融）必投头部。`/admin/insights` 加"招聘周期"管理面（列 draft、verify/reject、改 valid_until），走 `/api/campus-cycles/admin`（service-role，requireAdmin，过校验门 + 强制事实字段 immutable）。
3. **LLM 辅助草稿（P2d，可选加速）**：复用 `insight_engine.py` timing prompt + `ai-draft`，产 `draft`（verify_status=draft），只提候选、必人工核验才 verified 展示；不进 cron、不按用户触发（控账单）。

## 9. 失效与滚动（D5）

- 每年招聘季前，`campus-cycle-staleness-sweep`（或复用 `insight-staleness-sweep.yml`）把 `valid_until < current_date` 的 verified 观测标退役（RLS 读已天然过滤，无需额外态；退役即"读不到"，行保留不删）。
- 新一届滚动 = admin/LLM 新增下一届 observation（新 `grad_class` + `valid_until`），旧的自然过期。

## 10. 非目标（P2 不做）

- 通知/推送（整个校招专区本期都不做）。
- 🔥"提前批刚开"的 first_seen 突增徽章（first_seen 被 6/15 重建污染，与本 P2 洞察是两回事）。
- 今年精确日期全覆盖（P3，且只认官方源）。
- **提前批 vs 正式批的难度/流程/HC 差异**（D4：经验型，推 P3）。
- 海外校招洞察（先国内）。

## 11. 测试

- **纯函数优先** `tests/recruitment-cycle.test.js`：`campusTimelineSummary`（时间轴摘要 / 现处黄金期 / 尾声 / 未开始 / 多批次排序 / 年份绑定展示 / 过期与未 verified 过滤 / 无观测返回 null / 边界）。
- **迁移种子解析**：10 家 phase 串 → 结构化 month/batch/season 的解析正确性（可在纯函数层测解析器）。
- **admin 路由**：鉴权（requireAdmin）+ 事实字段 immutable 约束 + 校验门。
- 不改现有 `recruitmentCategory` / `campus-zone.ts` 既有函数则其现有测试不受影响；若微调需同步。

## 12. 落地顺序（供 writing-plans 细化）

- **P2a**：建 `recruitment_cycle_observations` 表（迁移 + RLS + 索引）+ 迁 10 家种子进来 + admin 录入/核验入口（管理面 + `/api/campus-cycles/admin`）。
- **P2b**：`lib/recruitment-cycle.ts` 纯函数 + `getRecruitmentCyclesForCompanies` 读层 + 校招卡片时间线行（展示 A）。
- **P2c**：`/api/insights` 扩 `recruitment_cycles` + 抽屉结构化时间轴（展示 B）。
- **P2d（可选跟进）**：LLM 辅助草稿管线（复用 ai-draft）扩塌陷行业覆盖 + 失效巡检接入。
