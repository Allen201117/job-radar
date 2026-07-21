# 校招洞察（Campus Recruitment Insights）P2 设计

> 状态：设计草案，交给下个 session 接手（先 brainstorm 未决项 → writing-plans → 实现）
> 2026-07-20 · 关联：[[job-radar-campus-zone]]（P1 已上线）、主设计 `docs/superpowers/specs/2026-07-20-campus-recruitment-zone-design.md`（§8 P2 展望）

## 0. 给接手 session 的话

**这是 P2，P1 已上线 main。** 先读本文件 + 主设计 spec + 记忆 [[job-radar-campus-zone]]，把「未决项」（§8）跟创始人 brainstorm 清楚，再 writing-plans。不要一上来写代码。P1 的「面」已经建好（`/campus` 页 + 诚实窗口徽章），P2 是给这个面**补上"该什么时候投"的时间/批次洞察**。

## 1. 背景与目标

- **产品**：求职雷达，公开企业官网岗位雷达。P1「校招专区」`/campus` 已上线：按用户行业锁定必投清单公司，聚合校招岗，诚实窗口徽章（🟢招聘中 / ⚪当前没看到 / ⚙️待接入 / ⏳数据待更新）。窗口徽章是 P1 做的「**此刻开没开**」事实层。
- **P2 目标**：补校招求职者最大的**信息差**——
  1. **时间信息**：往年提前批/正式批几月开、往年几月招满/结束、**招聘黄金期**。
  2. **批次差异**：提前批 vs 正式批的难度/流程/HC 差异（"该先投哪批"）。
  3. **显式展示**：时间信息一部分要**显示在洞察抽屉外面**（校招专区卡片上直接一行），点进抽屉看详细。
- **不变的红线**：可靠度分层、诚实标注来源与年份、宁缺不编（继承产品 DNA 与 P1）。

## 2. 已有可复用的零件（别重造）

| 零件 | 位置 | P2 怎么用 |
|---|---|---|
| 洞察系统 Module B（公司洞察） | `insight_items` 表（迁移 013/014），维度 `timing/compensation_intensity/path/culture` | `timing` 维度就是「招聘时机」，P2 的展示层复用它 + 抽屉 |
| 时效字段 + 校验门 | `insight_items.time_window/valid_from/valid_until`；`lib/insight-verification.ts` 的 `hasTimeWindow()` | 观测的时效表达复用 |
| **招聘窗口时间引擎** | `lib/career-path.ts`：`parseRecruitingMonths()`（:35 文本→月份集）、`timingStatus()`（:76 判 open/rolling/closed）、`buildCareerPath()`（:129） | 解析"每年7-9月"这类文本、判当前是否黄金期，**直接复用，别重写** |
| **10 家头部种子数据** | `014_seed_career_insights.sql`（32 处提前批/正式批/秋招/春招），payload.phase 存"秋招提前批7月/正式批8-9月/春招3-4月" | P2 的数据起点；但只 10 家、且是展示字符串非结构化 |
| 洞察抽屉 | `components/CompanyInsightDrawer.tsx`（有 timing 分区，`CalendarBlank` 图标，渲染 content + time_window 文本） | 抽屉内详细展示复用；**注意**：现在 `PayloadChips` 只处理 hiring/listing，timing 没结构化芯片——P2 要补 |
| LLM 洞察管线 | `crawler/insight_engine.py:117` timing prompt（"校招/社招节奏与月份窗口"）、`app/api/insights/admin/ai-draft` | 生成"往年规律"候选草稿（必人工核对过门）复用 |
| P1 校招专区 | `app/campus/`（page/client/loading）、`lib/campus-zone.ts`（纯函数）、`lib/jobs-store/read.ts` 的 `getCampusZone` | P2 时间信息展示挂到公司卡上（抽屉外那一行）+ 抽屉 |

**关键现状**：时间窗能力（种子数据 + career-path 引擎 + LLM prompt）都有，但**孤立在 `/path` 页 + 只 10 家 + 非结构化**。P2 = 结构化 + 扩覆盖 + 接进校招专区主路径。

## 3. 可靠度分层（三层，P1 已做第一层）

| 层 | 信息 | 可靠度 | 标注 | 状态 |
|---|---|---|---|---|
| ① 事实 | 此刻窗口开没开（🟢/⚪徽章） | 最高（纯抓取派生） | 直接展示 | ✅ P1 已上线 |
| ② 往年规律 | 往年提前批/正式批月份、黄金期、往年结束、批次差异 | 中 | **"据往年 + 具体年份"**，人工核验 | 🔜 **P2 本期** |
| ③ 今年精确日期 | 今年 X 月 X 日截止/开放 | 最难 | 只在有官方校招公告源时显示，拿不到绝不编 | P3 |

**季节感知是"解释层"，不污染"事实层"**：卡上 P1 徽章说"此刻在招/没看到"（事实）；P2 在旁边另起一行"按往年这时候是提前批黄金期/已进尾声"（据往年）——两者视觉/语义分开，不能让往年规律改写此刻事实。

## 4. 数据模型：招聘周期观测表（新表，可版本化）

**决策**：新建 `recruitment_cycle_observations`，**不塞进 `insight_items`**。理由：insight_items 适合承载"展示型洞察条目"，但批次/时间是**需要版本化、可追溯、按年份滚动**的结构化事实底座；混进 insight_items 会让"据往年"的年份归属、原始证据留存、LLM/人工修订追溯都变脏。insight_items 的 `timing` 维度**引用/派生自**本表，作展示。

**表结构（字段清单，接手 session 按此写迁移）**：
- `id`, `company_id`（FK company_profiles）
- `recruit_year`（招聘年度，如 2027）+ `grad_class`（毕业届别，如 "2027届"）——**必须分清"2027届招聘"与"2026年发生的招聘"**
- `batch`（批次枚举：提前批 / 正式批 / 补录 / 实习转正 …）
- `event`（事件枚举：开放 / 截止 / 黄金期）
- `time_expr_type`（时间表达类型：精确日期 / 日期范围 / 月 / 历史规律）
- `value_start` / `value_end`（起止值，按 time_expr_type 解释）
- `confidence`（置信度）
- `evidence_url` + `evidence_fetched_at`（证据链接 + 抓取时间）
- `verify_status`（人工核验状态：draft / verified / rejected）
- `valid_until`（失效时间，过期巡检退役）
- `created_at` / `updated_at`

**不变量（务必守）**：
- **原始 observation 不可覆盖**（immutable）；展示结论从中派生。LLM/编辑改错要能追溯 → 修订走新增 observation + verify_status，不原地改历史。
- **"据往年"必须绑定 `recruit_year`**（2024 规律不能含糊说"往年"）。
- **LLM 只提取候选 + 标注证据片段**（写 draft）；**无官方原文 / 无法定位公司+届别 / 日期冲突 → 禁止发布为日期事实**。精确日期（time_expr_type=精确日期）只接受官方校招公告或官方招聘页可复查证据。

## 5. 展示（两处）

**A. 校招专区卡片上（抽屉外，用户要的"显式")**：
- P1 窗口徽章下方一行"时间线"：如 `据2026往年 · 提前批约7月 · 正式批8-9月 · 当前处黄金期`（据往年标注 + career-path `timingStatus` 算"当前处黄金期/尾声"）。
- 只在有 verified 观测时显示；无则不显示（不占位、不编）。

**B. 洞察抽屉内（详细）**：
- 复用 `CompanyInsightDrawer` 的 timing 分区；补一个**结构化时间线芯片/时间轴**（现在 timing 只有纯文本，`PayloadChips` 只处理 hiring/listing → P2 要给 timing 加结构化渲染），展示各批次/事件的时间 + 证据来源 + "据X年"。

## 6. 数据供给（怎么把观测填进表）

三层来源（合规同 Module B v2.0）：
1. **人工策展**：头部公司往年规律（10 家种子扩到必投头部），admin 录入过校验门。
2. **LLM 辅助草稿**：复用 `crawler/insight_engine.py` timing prompt + `ai-draft` route，产出 draft（verify_status=draft，**必人工核对**才 verified 展示），只提候选不发布日期事实。
3. **官方源（P3 的精确日期）**：官方校招公告/招聘页可复查证据，才允许 time_expr_type=精确日期。

## 7. 非目标（P2 不做）

- 通知/推送（整个校招专区本期都不做）。
- 🔥"提前批刚开"的 first_seen 突增徽章（P1 已砍到"有稳定基线后"，与本 P2 洞察是两回事，别混）。
- 今年精确日期全覆盖（那是 P3，且只认官方源）。
- 海外校招洞察（先国内）。

## 8. 未决项（接手 session 先跟创始人 brainstorm 清楚再动手）

1. **往年数据从哪来、覆盖多少家**：10 家种子 → 扩到必投头部多少家？纯人工策展成本 vs LLM 辅助草稿的信任度权衡？先做哪几个行业（对齐 P1 供给的塌陷行业？还是先覆盖率好的互联网/汽车）？
2. **卡片那一行时间线的具体措辞与视觉**：怎么在"据往年"和"信息有用"之间平衡，不让用户误当成今年确切日期？
3. **`recruitment_cycle_observations` 与 `insight_items` timing 维度的具体接法**：是 timing 维度完全改由本表派生，还是并存双写？迁移与回填怎么做（10 家种子怎么迁进来）？
4. **批次差异（提前批 vs 正式批难度/流程）的信息来源与合规**：这属于"经验型"洞察（grade=experience），要走 Module B 的 ≥2 源 + judge 共识门，数据从哪来？
5. **失效与滚动**：往年规律的 `valid_until` 怎么定？每年招聘季滚动时怎么更新年份归属？

## 9. 落地顺序建议（供参考，接手 session 定）

P2a：建 `recruitment_cycle_observations` 表 + 迁 10 家种子进来 + admin 录入/核验入口 → P2b：career-path 引擎读本表算"当前黄金期/尾声" + 校招专区卡片时间线行 → P2c：洞察抽屉 timing 结构化渲染 → P2d：LLM 辅助草稿管线（复用 ai-draft）扩覆盖。
