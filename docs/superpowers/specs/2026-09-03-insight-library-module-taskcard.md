# 任务卡：洞察库独立模块（职业洞察 v3 第二阶段）

> **给接手的新 session**：这是一张自包含任务卡。先完整读完本文，再读 §0 列的三份前置文档。
> 本轮之前的所有实测结论都在里面，**别重新调研，也别推翻已验证的结论**。

---

## 0. 前置必读（按顺序）

1. `docs/superpowers/specs/2026-09-03-insights-v3-scope-and-model.md` —— v3 立项 spec。
   **§1.5「范畴的诚实边界」是全部方案的前提，不认它就会再做一个 v2。**
2. 仓库根 `CLAUDE.md` 的「工程化底线：本产品不是 demo」段（2026-09-03 新立）+「模块 B 职业洞察层」段。
3. `supabase/migrations/204_insight_subjects_and_structured_items.sql` 与 `205_backfill_insight_assertion.sql`。

**代码基线**：分支 `claude/insights-v3-scope`（工区 `.claude/worktrees/insights-v3-scope`）。
⚠️ **该分支尚未推 main**，接手时先 `git fetch origin && git merge origin/main` 再干活。

---

## 1. 创始人给的锚点（这是本模块的立身之本）

> **「每一条健康的职业洞察，和一条岗位一样重要。我们的产品是在岗位信息和洞察信息两个维度上的，
> 因此应该有『岗位库』和『洞察库』这两个概念。」**

推论（做任何取舍时回来对照这条）：
- 洞察**不是岗位卡的附属品**。现在它只活在岗位卡点击展开的抽屉里，这是把它当配菜。
- 洞察需要**自己的库、自己的页面、自己的治理后台**，与岗位库平级。
- 「健康」是限定词：**不健康的洞察不配算数**（无来源、无时间窗、无范围、绝对化措辞的一律不进库不展示）。

---

## 2. 本轮要做什么

### 2.1 主线：洞察库独立页面（新建）

参照 `/jobs`（岗位库）的形态，做 `/insights`（洞察库）：

| 能力 | 要求 |
|---|---|
| 列表与筛选 | 按 **公司 / 业务线 / 维度 / 断言强度（事实·数据·说法）/ 指标 metric_key / 时效** 筛。**筛选项必须来自枚举，不是自由文本**——这正是迁移 204 建 `metric_key` 枚举的目的。 |
| 排序 | 新鲜度、样本量、公司在招规模 |
| 三档视觉 | 复用已做好的 `assertionChip`（fact 绿 / signal 蓝 / claim 灰），别再造一套 |
| 主体下钻 | 公司 → 业务线两级（`insight_subjects`），点公司能看到它下面各业务线的洞察 |
| 空状态 | **不显示「暂无数据」**，显示贡献入口（见 §2.3） |
| 与岗位库互链 | 洞察条目 → 该公司/业务线的在招岗位；岗位卡 → 洞察库对应主体页 |

⚠️ **性能红线（本仓库踩过的坑，别重犯）**：
- 首屏**不要逐条下发**全部洞察。参照 `/campus` 的做法（`lib/campus-facets.ts`）：首屏只下发**聚合分面**，
  展开某公司时再按「公司 + 维度」按需取。`/campus` 曾因逐条下发 16,494 条岗位导致首屏 10.1s / 2.09MB。
- 跨用户一致的重活走 `unstable_cache`（跨实例共享），**别用进程内 Map**（serverless 多实例命中率≈0）。
- 列表查询先看 EXPLAIN 确认走索引；迁移 204 已为 `metric_key` / `assertion` / `subject_id` 建了部分索引。
- Supabase 单次 select 最多 1000 行且**静默截断**，任何「拉全表」必须走 `lib/supabase-paginate.ts`。

### 2.2 前后端联调（创始人明确要求「考虑怎么联调达到最好的展示效果」）

先定契约再动手，建议顺序：
1. **定读模型**：`/api/insights/library` 返回什么形状（分面 + 分页条目 + 主体树）。写进本文件当契约。
2. **后端先出真数据**：先让接口能返回真实数据（哪怕前端还没做），用 curl 验证形状与耗时。
3. **前端按契约渲染**，不等后端全做完。
4. **联调验收看三件事**：首屏字节数、TTFB 与 responseEnd 的差（差大 = SSR 本身慢，不是取数慢）、筛选切换的交互延迟。

### 2.3 第三层「两手抓」（创始人拍板）

> 「一边我们自己补，一方面开放用户贡献入口。」

- **我们自己补**：T3 检索改成**按业务线定向**（`{公司} {业务线} 加班` 而非 `{公司} 加班`），结果挂到 `subject_id` 上。
  T3 现有优化已上线（首源够用即停、域名黑名单、判官 evidence_kind 分档），在此基础上加主体维度。
- **用户贡献入口**：洞察库与抽屉里，凡「强度 / 年终奖 / 晋升 / 面试」无可信内容的位置，
  显示 **「你在这家公司待过？说一句真实体验，解锁其他人的说法。」**
  对标机制：Glassdoor 互惠墙（看评价须先贡献）、Levels.fyi offer 截图验证。
  现有 `insight_submissions` 表与 `/api/insights/submit` 已存在，聚合门槛 `FIRST_PARTY_MIN_COUNT=5`
  在内测期等于锁死，**建议降到 3 并做分级验证标记**（企业邮箱 / 脱敏 offer / 工牌）。

### 2.4 治理后台

`/admin/insights` 增加：
- `insight_subjects` 治理页：下架噪声主体（置 `status='rejected'`，**保留行不删**，抽取器据此跳过）、合并别名。
- 按 `metric_key` / `assertion` 批量筛选与下架（这是枚举化的直接收益）。
- `pending_review` 条目的人工审核入口（目前积压无人可见）。

---

## 3. 已经做完的（别重做）

分支 `claude/insights-v3-scope` 上已提交：

| 提交 | 内容 |
|---|---|
| 迁移 204 | `insight_subjects` 表（公司×业务线，`rejected` 保留行=治理入口）+ `insight_items` 五列（`subject_id`/`assertion`/`metric_key`/`metric_value`/`scope`）+ 枚举约束 + 三条筛选索引 |
| 迁移 205 + 护栏 | **1,619 条假「事实」降级**（active 6,253 里 1,619 条来自搜索却标 fact，真官方事实仅 265 → 85% 名不副实）；`normalize_assertion` 纯函数钉死「public_web 永远只能是 claim」 |
| `crawler/bu_extract.py` | 业务线抽取器。38,491 条真实标题验证，噪声率 14% → **6.6%**（过 <10% 验收线）。抽出真业务线：字节 Seed(229)/飞书(397)/火山引擎(363)/TikTok Shop(921)、蚂蚁 OceanBase/网商银行、快手 主站/电商/生活服务、腾讯 微信视频号/光子 |
| 展示层 | 三档芯片 + claim banner + 展示门（claim 必须有时间窗 + ≥2 域名；fact 混非官方来源即降级）+ 绝对化措辞禁用 + 派生项带 `sample_n` |

**未做（本轮接手）**：P0-3 业务线级信号派生（每个 subject 算 hiring_volume_30d / trend / city_share / function_share / exp / edu / open_age）、洞察库页面、治理后台、贡献入口、T3 按业务线定向。

---

## 4. 硬约束（违反即返工）

1. **诚实边界**：用户最关心的四件事（强度/薪资/晋升/面试）里，岗位库**只能答「稳定性」**（招聘量 30/90 天趋势）
   与「好不好进」（门槛分布 + 在架时长）。**强度/晋升/面试完全不在岗位数据里**；薪资 `salary_text` 覆盖仅 1.8%。
2. **❌ 已证伪，别再试**：「JD 正文有公司自述的工作制/福利」。实测 388,651 个有正文在招岗：
   弹性工作 0.05%、双休 0.56%、加班 0.26%、股票 0.18%、年终奖 0.07%。
   根因=写福利是第三方平台形态，**企业官网 JD 只写职责与要求**。
3. **样本量硬门 + UI 显示 n**：业务线 n≥20 / 公司分布 n≥10 / 趋势两期各 n≥10；**n<10 禁百分比**；
   不足即整字段省略（不显示 0）。实测规模差异：字节 20,642 岗 / 腾讯音乐 265 岗 / 拼多多 29 岗。
4. **三档承诺不许混**：fact 只授予官方来源；搜索来源一律 claim，不得升格。
5. **写 `insight_items` 有三个出口**：`crawler/insight_backlog.py` / `insight_sweep.py` / `official_annual_report.py`。
   改写入契约前先 `grep -rln 'table("insight_items")'` 找全，**上一轮就漏了年报那个**。
6. **前端**：用 `app/globals.css` 的语义类（`t-*` / `ink-*`），字重只用 400/500/600/700；
   日期走 `formatDateLabel`（钉死 Asia/Shanghai，否则 SSR 与浏览器时区不一致触发 React #418）；
   异步操作按「点击反馈分档」给中间态与结果态，失败不许静默。
7. **看线上前端一律走创始人已登录的 Chrome**（`mcp__claude-in-chrome__*`，生产站 https://www.myjobradar.top）。
   禁止起本地 dev server、禁止建临时预览页、禁止用内置浏览器。移动端把 Chrome 窗口缩到 ~400px 看断点。

---

## 5. 验收标准

1. `/insights` 首屏 **< 1s**、传输体积 **< 300KB**（对照 `/campus` 优化后 174KB）。
2. 能用页面筛出「近 30 天招聘量增长 >30% 且有薪资数据的业务线」——**枚举化数据模型的价值验证**。
3. 洞察库与岗位库双向可跳转，且计数一致（同一公司在两边看到的在招岗数相同）。
4. 三档承诺在页面上一眼可辨；无范围的 claim 展示数 = 0。
5. 治理后台能把一个噪声业务线一键下架，且下次抽取不再抽回来。
6. 四件套 + lint 全绿；迁移 CI 自动 apply 成功。

---

## 6. 建议的推进顺序

1. 先把 `claude/insights-v3-scope` 分支**合并推 main 并验证**（迁移 204/205 上线、假事实降级生效）——先止血。
2. P0-3 业务线级信号派生（有了数据，页面才有东西可展示）。
3. `/api/insights/library` 读模型 + 分面（定契约、后端先出真数据）。
4. `/insights` 页面（列表 → 筛选 → 主体下钻 → 与岗位库互链）。
5. 贡献入口 + 治理后台。
6. T3 按业务线定向检索。

---

## 7. 已交付（2026-09-03 第二阶段，全部已上 main 并线上验证）

### 7.1 读模型契约（`GET /api/insights/library`）

**列表**（无 `subject` 参数时）：

```jsonc
{
  "ok": true,
  "total": 1529,          // 当前筛选下的主体数
  "page": 1,
  "page_size": 24,
  "index_built_at": "2026-09-03T08:47:44.231Z",  // 索引重建时刻；连续两次请求应当**相同**，变了=缓存没命中
  "subjects": [ /* LibrarySubject，见下 */ ],
  "facets": {             // 每个分面都在「其它筛选已生效、本分面自己不生效」的集合上计数
    "kind":      [{"key":"company","count":1044}, {"key":"business_unit","count":485}],
    "assertion": [{"key":"signal","count":1433}, {"key":"claim","count":377}, {"key":"fact","count":18}],
    "dimension": [{"key":"hiring","count":1458}, …],
    "metric":    [{"key":"hiring_volume_30d","count":1433}, …],
    "industry":  […],
    "freshness": [{"key":"fresh","count":1468}]
  }
}
```

`LibrarySubject`：

```jsonc
{
  "id": "uuid", "company_id": "uuid", "company": "字节跳动", "industry": "互联网/科技",
  "kind": "business_unit",            // 或 "company"
  "name": "飞书", "job_count": 397,
  "assertion_counts": {"fact": 0, "signal": 7, "claim": 2},
  "dimensions": ["hiring", "compensation_intensity"],
  "item_count": 9,                     // **过了展示门之后**的条数；必须等于展开后看到的条数
  "last_verified_at": "2026-09-03T…", "freshness": "fresh",
  "metrics": [["hiring_volume_30d", 47, 397, "signal"], …],   // 元组！见下
  "cards":  [{"metric_key":"…","metric_value":47,"metric_unit":"个","sample_size":397,
              "assertion":"signal","content":"近 30 天新挂出…（基于 397 个在招岗）。","scope":{}}]
}
```

⚠️ **`metrics` 是元组 `[metric_key, metric_value, sample_size, assertion]`**，不是对象。
理由是量出来的：对象形态 1,600 主体 × 7 指标实测 1,716KB，顶穿 Vercel 数据缓存 2MB 上限 →
**静默不缓存**，每请求重建索引（线上实测 ~10s/次，且不报错）。元组化后 983KB。
下标常量与访问器（`M_KEY` / `metricKey()` …）与打包逻辑**同文件**，防两端口径漂移。

⚠️ `cards`（带正文）**不在缓存索引里**，只为当前这一页的 24 个主体现取 → 首屏体积不随洞察库规模增长。

**展开单个主体**：`?subject=<uuid>` → `{ ok, subject, items: InsightItemView[] }`，
`items` 与索引计数走**同一道展示门**，所以卡面写几条、展开就是几条。

**筛选参数**：`q` / `company` / `kind` / `dimension` / `assertion` / `industry` /
`metric` + `metricMin` + `metricMax` / `has`（可重复）/ `freshness` / `sort` / `page`。
未知取值一律丢弃而不是原样透传（否则会静默筛出 0 条，用户读成「没有数据」）。

### 7.2 线上实测数字（生产站，2026-09-03）

| 项 | 数字 |
|---|---|
| 主体 | 1,529（公司 1,044 + 业务线 485） |
| 派生 signal 条目 | 9,652（0 失败） |
| 每日快照 | 1,590 行（趋势的时间序列从今天开始积累） |
| 假「事实」降级 | 1,619 → 0；active fact 从 1,914 降到 295 |
| `/insights` 首屏 | **592–602ms**（热）/ 211KB —— 验收线 <1s、<300KB |
| `/api/insights/library` | 442–686ms（热），27KB/页 |
| 业务线抽检噪声率 | 13% → ~2%（两轮降噪，逐类钉了回归断言） |

### 7.3 本轮**没做**的（留给下一棒）

1. **T3 检索按业务线定向**（任务卡 §2.3 上半）：仍是 `{公司} 加班` 而非 `{公司} {业务线} 加班`，
   结果也还没挂 `subject_id`。这是「说法」层唯一没动的部分。
2. **`hiring_trend_30d_pct` / `hiring_trend_90d_pct` 现在恒为 0 条**，这是**刻意的**：
   趋势只能由 `insight_subject_daily` 的跨日快照得出，而快照今天才开始记。
   ⚠️ 别改回「用 jobs.first_seen_at 分窗口算」——expired 岗每日 purge，
   「30-60 天前」的窗口只剩活到今天的那部分，相除会系统性把环比算高。
   30 天后这两个指标会自己出现，无需改代码。
3. **`salary_range_k` 只有 27 个主体**：全库 395,969 个在招岗里只有 7,160 个写了薪资、
   仅约 1,645 个能解析成明确区间（spec §1.5 的「薪资覆盖 1.8%」在库里逐字成立）。
   这不是解析器的问题，是源头就没有。
4. **筛选条件没有同步进 URL**：目前不可分享、不可收藏、刷新即重置。
5. **贡献入口只到「提交」为止**：聚合门槛 `FIRST_PARTY_MIN_COUNT=5` 未按任务卡建议降到 3，
   分级验证标记（企业邮箱 / 脱敏 offer / 工牌）未做。
