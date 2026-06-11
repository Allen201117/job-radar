# ③「职业路径」技术方案（求职雷达 PRD 阶段 2 雏形）

> 状态：已与用户确认方向，进入实现。
> 上位：`PRD.md` §8.4（个性化职业路径）、§13 阶段2。依赖模块 B 洞察层 + 模块 C 简历画像。
> 日期：2026-06-03。

## 0. 一句话
把用户画像（目标公司/岗位/阶段）与洞察层（四维）做**确定性匹配**，在独立 `/path` 页输出「时机 × 方向 × 路径 × 避坑」的个性化职业路径建议。**不接 LLM**（但输出为结构化，为未来「LLM 叙事层」预留——只润色、不新增事实）。

## 1. 锁定决策
1. **确定性引擎，无 LLM**。可靠性来自数据+规则；LLM 只提流畅度且在最高风险面引入幻觉，故留作后续可选叙事钩子。
2. **独立 `/path` 页**（nav 入口）。
3. 锚点 = `user_preferences.target_companies` + `candidate_profiles`(target_roles/seniority/target_locations)；叠加洞察层 + jobs 在招计数。不推断「当前公司」。

## 2. 页面分区
1. **画像摘要**：目标岗位 / 阶段 / 城市。无画像 → 空状态引导上传简历/设偏好。
2. **优先投递建议（核心）**：目标公司优先级表，每行 = 时机 badge（窗口期/全年滚动/可能非窗口期/未知）+ 在招岗位数（跳 /jobs）+ 一句性价比 + 一句避坑；排序：窗口期>滚动>未知>非窗口，再按在招数。目标为空 → 推荐种子里「当前窗口期 + 匹配阶段」的 ≤6 家。
3. **路径 / 跳板**：命中目标公司的 path 洞察。
4. **避坑提示**：目标公司 culture + 高强度 comp 洞察（复用抽屉卡语言、带 grade/来源）。
全部「据公开信息/仅供参考」归因。

## 3. 代码结构（隔离、可单测）
- `lib/career-path.ts`（纯函数核心）：
  - `parseRecruitingMonths(timeWindow)` → `{months:Set, rolling, negative, parseable}`；解析「每年 8–10 月」「全年滚动」「5–7 月 HC 偏紧(negative)」。
  - `timingStatus(timingItems, now)` → `{status:open|rolling|closed|unknown, label, detail}`；正窗口 in-range=open，负窗口(如微软 HC 偏紧) in-range=closed/caution，全年滚动=rolling，否则 unknown。多条取最优。
  - `buildCareerPath(profile, prefs, companies, now)` → `CareerPathReport`；每公司算 timing/comp_note/caution_note/job_count/rank_score+reasons，排序；汇总 path_notes、cautions；定 failure_reason。
- `lib/insight-bundle.ts`（小重构）：把 `/api/insights` 的「过校验门 + 按维度分组」抽成 `groupGatedInsights(rawRows, now)`，insights 与 career-path 共用。
- `app/api/career-path/route.ts`（GET, nodejs）：auth → 取 profile+preferences → `findCompanyProfile` 匹配 target_companies（空则取全部种子做 fallback 推荐）→ 批量取洞察（bundle 门）+ jobs active 计数（按 insight-match 归并）→ `buildCareerPath` → `{ok, report, is_recommended_fallback, failure_reason}`。
- `app/path/page.tsx` + `path-client.tsx`：渲染，暗色风格，复用 grade 芯片/来源链接语言。
- `components/Navbar.tsx` + `lib/i18n.ts`：加「职业路径」入口（Compass 图标，key `path`）。
- `lib/types.ts`：`CareerTimingStatus / CareerCompanyRec / CareerPathReport`。
- `tests/career-path.test.js`：月份解析（正/负/滚动/不可解析）、timingStatus、排序、空状态。

## 4. failure_reason
- `no_profile`（无画像且无目标公司）、`insight_unverified`（无可信洞察）；前端翻译成人话 + 引导。

## 5. 边界（YAGNI）
不接 LLM、不推断当前公司、不造跨公司路径图谱（只用现有 path 洞察）、不动 jobs 质量门、不改洞察 schema。

## 6. 实现顺序
career-path 纯引擎+类型+单测 → insight-bundle 抽取+insights 复用 → /api/career-path → /path 页+Nav+i18n → 回归(node --test + build) + live 验证(service role 跑引擎对真实数据 + 浏览器冒烟)。
