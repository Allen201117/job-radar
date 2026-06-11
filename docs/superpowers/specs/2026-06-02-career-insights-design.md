# 模块 B「职业洞察」技术方案（求职雷达 v2 二期）

> 状态：已与用户确认方向，进入实现。遇到问题随开发调整。
> 上位文档：`PRD.md`（§7 合规、§8 模块 B、§11 数据模型、§12 失败模式、§13 路线图、§14 边界）。
> 日期：2026-06-02。

## 0. 一句话

把四类「职业信息差」（timing / compensation_intensity / path / culture）做成**一套统一洞察引擎**，靠**人工策展 seed + 轻量 admin 录入**进库（不接 LLM、不爬社区），每条带 `grade / 来源 / 时效 / 归因`，与官方岗位层**严格分离**地呈现在 web 产品中。后端先跑通，再适配前端暗色风格。

## 1. 关键决策（已锁定）

1. **统一引擎**：四个维度共用 schema / 校验 / API / 前端表现，只在 `dimension` 枚举、分级口径、文案 rubric 上区分。
2. **数据来源**：人工策展 seed + admin 录入，**不接 LLM、不爬社区、不绕反爬**。§8.2 验证流水线落地为「录入规则 + 自动校验门」。
3. **上线节奏**：后端统一引擎 + 四维 schema 一次到位；首批种子四维一次铺满 10–20 家。
4. **铁律**：洞察层与官方岗位层数据通道 / 信任级别 / UI 必须分离（PRD §14）。

## 2. 维度难度 / 风险排序

| 维度 | grade 主体 | 难度 | 说明 |
|---|---|---|---|
| timing 时机类 | fact | ⭐ | 公开可推（财年 / 校招公告 / 官网），做准做深 |
| compensation_intensity 性价比类 | fact+experience | ⭐⭐ | 薪资带部分公开，强度 / 门槛多经验，带样本归因 |
| path 路径类 | experience | ⭐⭐⭐ | 跳槽链路 / 对口公司 / 内推，结构化为公司→公司边 |
| culture 文化避坑类 | experience/rumor | ⭐⭐⭐⭐ | 负面评价多，名誉权风险最高，做浅最重免责 |

## 3. 数据模型（migration `013_career_insights.sql`）

- **company_profiles**：`id, company(唯一), display_name, aliases text[], summary, last_verified_at, created_at/updated_at`
- **insight_items**：`id, company_id FK, dimension(timing|compensation_intensity|path|culture), grade(fact|experience|rumor), title, content(归因式), sample_size, payload jsonb, time_window, valid_from, valid_until, last_verified_at, deidentified bool, status(active|disputed|retired), created_at/updated_at`
- **insight_sources**：`id, url, publisher, source_kind(official_filing|official_site|campus_announcement|public_aggregate|community_deidentified), excerpt(短摘要), collected_at, deidentified bool, created_at`
- **insight_item_sources**：多对多 `(item_id, source_id)` 复合主键
- **insight_disputes**：`id, item_id FK, reporter_user_id, reason, contact, status(open|upheld|rejected), created_at, resolved_at`

### RLS
- company_profiles：authenticated 读；admin/service 写。
- insight_items：authenticated 读 **且仅 `status='active' and deidentified=true`**；admin/service 写改。
- insight_sources：authenticated 读 **仅 `deidentified=true`**；admin/service 写。
- insight_item_sources：authenticated 读；admin/service 写。
- insight_disputes：登录用户可 insert（reporter=auth.uid() 或 null）；本人读自己的；admin 读全部 + 改状态。

## 4. 校验与合规（`lib/insight-verification.ts`，纯函数可单测）

- **grade 门**：`fact` 须 ≥1 有效来源；`experience` 须 `sample_size ≥ 5` 且来源 ≥2 个不同 publisher；`rumor` 默认拦截（不写 active）。
- **去标识门**：item 与其引用 source 必须 `deidentified=true` 才可展示。
- **时效门**：强制 `time_window` 或 `valid_*`；`valid_until < 今天` → `insight_outdated`，降权 / 标「可能已过时」。
- **归因 lint**：content 必须归因式（「据 N 位反馈 / 据公开数据」），禁止产品断言（rubric + 测试卡口）。
- **failure_reason**（§12）：`insight_unverified`（样本不足 / 未交叉）、`insight_outdated`（仅过期）。

## 5. API（Next.js App Router, `runtime="nodejs"`, `{ok, failure_reason}`）

- `GET /api/insights?company=...`：匹配 company_profile（normalize + aliases）→ 返回按 dimension 分组的 active+校验通过 items + 来源；无则 failure_reason。
- `POST /api/insights`（admin）：录入一条 insight，走校验门，不过门返回原因。
- `POST /api/insights/dispute`：登录用户提申诉。

## 6. 前端（与官方岗位视觉分离）

- **JobCard 招聘窗口 badge**：取公司 timing 洞察显示状态（带 grade 芯片 + tooltip 来源 / 时间）。
- **公司洞察抽屉**：从 JobCard 打开，四维分组，每条带 grade 芯片 / 归因 / time_window / last_verified / 来源链接 / 「这条有误?」申诉入口；用与岗位卡不同的视觉语言（色条 + 「社区聚合·非官方」标识）。
- 暗色主题、复用 `.y-*` / tailwind token，不动设计 token。

## 7. 种子数据（migration `014_seed_career_insights.sql`）

候选 10–20 家：字节、腾讯、阿里、美团、拼多多、京东、华为、百度、快手、小红书、微软中国、苹果中国、西门子、比亚迪、宁德时代。
- timing 以 fact 做准；comp/path 以 experience 带样本归因；culture 做浅最重免责。
- **诚实声明**：sandbox 断网，seed 为**待用户核实的策展草稿**（每条带来源 URL + `last_verified=seed 日`），上线前需用户确认来源真实性——这是 PRD「做准 20 家」的信任前提。

## 8. 测试

- `tests/insight-verification.test.js`、`tests/insight-match.test.js`（复用 scoring transpile 模式）。
- 回归四件套：`node --test tests/*.test.js` + crawler unittest + `npm run build` + `git diff --check`。
- migration / RLS / live API 需用户本机（sandbox 无 Supabase）。

## 9. 不做（边界）

不接 LLM；不爬社区 / 不绕反爬；不存 UGC 整段原文；insight 不指向具体自然人；洞察不污染 jobs 层；简历模块维持原边界。

## 10. 实现顺序

013 schema → types → verification + match 纯函数 + 单测 → /api/insights + dispute → 014 四维种子草稿 → 前端抽屉 + JobCard badge → 回归四件套。
