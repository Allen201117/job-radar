# 关键词筛选精准度修复 — 设计

> 2026-06-11 · 状态：已批准方向，实施中

## 问题（已实测复现）

用户痛点：输入 `pm` 筛选，结果里混进算法工程师、数据分析师等无关岗位。三个获取岗位的方式（本地看板 / 已知源刷新 / 官方源发现）准确率都很低。公司筛选只能下拉勾选、不能输入。

### 根因（确定性复现）

关键词匹配器 `lib/china-keyword-expansion.js` 的 `jobMatchesChinaKeyword`：
1. 把用户输入扩展成整组同义词（`pm` → `[产品经理, 产品, product, pm, po, ...]`）；
2. 拿这组词去撞岗位的**全字段文本**（标题 + 公司 + 城市 + 类型 + **摘要正文** + 薪资）。

问题在裸泛词 **"产品"**：几乎所有研发岗 JD 正文都写"负责 XX **产品**的算法/数据"，于是泛词撞正文 → 算法岗被误判为 `exact` 命中。实测：

| query=`pm` | 旧结果 | 期望 |
|---|---|---|
| 算法工程师（摘要含"产品"） | exact ❌ | null |
| 数据分析师（摘要含"产品"） | exact ❌ | null |
| 算法工程师（**空摘要**） | null ✅ | null |
| 真·产品经理 | exact ✅ | exact |

空摘要那条反证了罪魁是"同义词撞正文"。

三条链路（看板 `jobFilterTier`、`/api/search` live、`/api/discovery`）都调同一个 `jobMatchesChinaKeyword`，所以一处修复三处生效。

公司筛选：`components/JobFilters.tsx` 用 `<select>`，且 `jobs-client.tsx` 里是 `job.company !== filters.company` 全等匹配。

## 方案：职能门 + 二元分层（保留现有 exact/related 架构与 UI）

实施中发现「只列泛词锚点」只能治单向（pm→算法），治不了对称的反向（算法→产品经理：PM 岗正文写"了解算法"也会被误召）。
因为"算法"是高区分度具体词、必须保留正文召回，无法靠锚点拦。最终落地为更通用的**职能门**：

- **标题命中**：始终算数（标题是岗位职能的权威信号）。
- **正文命中**：过「职能门」才算——`classifyJobFunction(岗位)` 须 ∈ 查询命中的职能集合（查询无职能信号时，如纯公司名/散词搜索，放行不误伤公司检索）。
  - 治跨职能污染**双向**：算法岗正文写"产品"≠产品岗（职能=研发≠产品，正文命中被拦）；产品岗正文写"算法"≠算法岗（同理）。
- **泛词锚点（标题专属）**：只保留 `工程师 / engineer / 研发 / developer / 软件 / software`——这两组 `function=null`，职能门覆盖不到，且天然极泛 → 只匹配标题，永不撞正文。其余泛词（产品/数据/测试/设计…）全交给职能门，无需逐词维护清单。

判定（沿用单元间 AND、单元内 OR 的组合意图）：
```
bodyAllowed = 查询无职能  ||  classifyJobFunction(岗位) ∈ 查询职能集合
unit 命中 ⇔ ∃ term ∈ unit: 命中标题 || ( bodyAllowed && term 非泛锚点 && 命中正文 )
所有 unit 命中 ⇒ exact
```
`related`（同职能兜底）层完全不动——精挑的 `JOB_FUNCTION_RULES` + 兄弟组排除，继续作召回网，在看板下方"相关岗位"栏单独展示。

### 推演（双向精准 + 召回，已实测）
- `pm` → 算法/数据岗（正文"产品"）：职能研发/数据 ∉ {产品} → 正文命中被拦 → 排除 ✅
- `pm` → 2024校招（正文"**产品经理**"，职能=产品）：同职能 + 具体词正文命中 → 保留 ✅
- `算法` → 产品经理（正文"了解算法"，职能=产品）：产品 ∉ {研发} → 拦 → 排除 ✅（对称 bug 一并修）
- `算法` → 资深工程师（正文"负责推荐**算法**"，职能=研发）：同职能正文命中 → 保留 ✅
- `工程师` → `Backend Engineer`（标题）：锚点命中标题 → 保留 ✅（跨语言召回不丢）

所有既有测试（keyword-match-tier / china-job-intent / cross-language-recall / china-keyword-expansion）在新规则下均通过——它们的召回用例全是标题命中，无一依赖"泛词撞正文"。

## 公司筛选改可输入
- `JobFilters.tsx`：`<select>` → 文本 `<input>` + `<datalist>`（原生 combobox，已知公司自动补全，允许自由输入）。
- `jobs-client.tsx`：公司匹配 `!==` 全等 → 大小写不敏感**子串**（输"字节"命中"字节跳动"）。

## 改动面（覆盖用户说的「三种获取方式」全部）
- `lib/china-keyword-expansion.js`：加 `TITLE_ONLY_ANCHORS` + `queryFunctions` + 职能门重写 `jobMatchesChinaKeyword`。→ 治 **本地搜索看板** + **联网发现 `/api/discovery`**（共用 `filterJobsByQueryAndCity`）。
- `crawler/china_keyword_expansion.py`：同口径 Python 移植——`KEYWORD_GROUP_FUNCTIONS` + `classify_job_function` + `keyword_match_units` + `job_matches(title, body, query)`；`crawler/discovery.py` 的 `job_matches_query` 改传 title/body 分离调用。→ 治 **刷新公司库 `/api/refresh`**（CompanyRefreshRecipe）+ SPA 发现路径。
- `components/JobFilters.tsx` + `app/jobs/jobs-client.tsx`：公司 `<select>`→可输入 combobox（input+datalist）+ 大小写不敏感子串匹配。
- `app/api/search/route.ts`：`fetchCached` 结果过 `filterJobsByQueryAndCity`，与新匹配器对齐（消除"已知源刷新"宽 SQL 正文泄漏）。
- 测试：`tests/keyword-match-tier.test.js`（JS 双向精度+召回）+ `crawler/test_china_keyword_expansion.py`（Python job_matches + classify）。

## 不做（YAGNI / 越界）
- 不引入 LLM / 向量召回（Phase 1 边界）。
- 不改 exact/related 二元架构与排序 UI。
- 不补 Python 端缺失的 JS 21/22 组（工程师/软件 跨语言英文标题召回）——pre-existing gap，与本次精度修复无关，留作后续 parity。
