# 校招专区：默认态改成「全部校招岗」，必投 30 家降为一个入口

日期：2026-09-18 · 状态：已实现（本分支）

## 1. 为什么改

创始人口径：**「校招专区不能只做 30 家必投公司，这本质上不合理。校招专区提供的岗位应该是所有校招岗位（= 一个校招岗位库）。如果用户有必投 30 家的聚焦诉求，给他一个入口进『必投 30 家』视图；没有的话，默认展示正常的岗位库，只不过是校招岗位库。」**

现状（改动前）：`/campus` 只有一种形态 —— 按用户行业从必投清单里挑出约 30 家公司，渲染成公司卡片网格，展开某家才看得到岗位。库里的其余绝大部分校招岗**在这个页面上根本不存在**。

真库数字（2026-09-18 直查香港 jobs 库，见 §7）：

| 口径 | 岗位数 | 公司数 |
|---|---:|---:|
| `status=active ∧ job_scope=domestic ∧ recruitment_category='校招'` | 75,744 | 1,003 |
| 同上 **∧ `recruitment_explicit`**（= 本产品「校招」筛选的真实口径） | **69,138** | **978** |
| 再过当季届别门（`grad_class is null or >= 2027`） | **66,051** | — |
| 实习（explicit） | 27,108 | 577 |
| 实习过届别门 | 26,590 | — |

必投看板覆盖 ~30 家。**差了两个数量级。**

## 2. 目标与非目标

**目标**
1. `/campus` 默认态 = 全部校招岗（校招 / 实习两种模式），服务端分页、筛选下推 SQL、可按匹配度 / 最新排序。
2. 「必投 30 家」保留现有全部形态（公司卡 / 窗口徽章 / 时间线 / 「对你有货」排序 / 展开分页），降为专区顶部一个明显入口，可来回切。
3. 用户上次选的视图记 `localStorage`。
4. 移动端与暗色模式都对。

**非目标（这次不做）**
- 不动爬虫、不动必投清单口径（`lib/must-apply-list.json` 是北极星，一个字不改）。
- 不新造第二套筛选器、不新造第二套岗位卡。
- 不做一次性全站改版、不引入新依赖。
- 不改 `recruitment_category` / `recruitment_explicit` 的分类口径（见 §6 诚实边界）。

## 3. 取数：复用 `/api/jobs/search`，不扩 `/api/campus-zone/jobs`

两条路都评估过，结论是**复用 `/api/jobs/search`，改动最小且性能可控**。

**为什么不是 `/api/campus-zone/jobs`**：它是为「必投看板展开某家公司」造的，天生带三条绑死的约束——
① 公司范围由服务端按登录用户的必投行业解析，不在清单里直接 403（`company_out_of_scope`），这正是要打破的那条边界；
② 只接四个筛选项（城市 / 学历 / 职能 / 届别），没有关键词、经验、公司类型、资本来源、发布时间、排序；
③ 没有打分排序（`toScoredJob` 把 `match_score` 填 0）。
把它扩成全库检索 = 把 `lib/jobs-store/search.ts` 那一整套（FTS / 粗排窗口 / 精筛分层 / 诚实计数）重写一遍。

**为什么 `/api/jobs/search` 正好合适**：
- `jobType` **已经是物化列的精确 SQL 下推**（`appendRecruitmentPrefilter`：`recruitment_explicit and recruitment_category = '校招'`，与 JS 的 `jobFilterMatch` 逐字同义，不是近似超集）。
- **往届门已经在这条路上**（`appendCurrentSeasonWhere`，只作用于校招/实习），与必投看板 `getCampusZone` 是同一条口径 —— 两个视图不会一个显示 2026 届残岗、另一个不显示。
- 求职范围（`job_scope`/`target_regions`）、排除词、忽略/已投递隐藏、公司散列、诚实计数（`formatMatchTotal` + `exactTotalWhenCapped`）全都现成。
- 前端 `useJobFilters` + `JobFilters` + `JobCard` 整套可以原样复用，零新增筛选器。

**性能**：`jobType` 下推把候选集从 49.3 万在招行收到 6.9 万，比 `/jobs` 的无筛选默认态窄得多。线上匿名实测（2026-09-18，`x-vercel-id` 前缀 `hkg1`，见 §7）TTFB **1.0~1.9s**，与 CLAUDE.md 记的 `/jobs` 冷路径 14~16s 不是一个量级。

**绝不做的事**：不在 SSR 里下发任何岗位行。CLAUDE.md「校招专区首屏」那条立的碑（16,494 条逐条序列化 → 单页 2.09MB / responseEnd 10.1s）在 6.6 万条上只会更糟。全部校招岗视图**挂载后**才发第一次请求，首帧是骨架屏。

## 4. 形态

```
/campus
├─ ProductHero「校园招聘」
│   └─ 校招岗位库计数条：「校招 66,051 个在招 · 实习 26,590 个」（精确数，见 §5）
├─ 视图切换 Segmented：[ 全部校招岗 ] [ 必投 30 家 ]      ← localStorage 记住
├─ 校招 / 实习 Segmented（两个视图共用同一个 mode 状态）
└─ 视图 A：全部校招岗（默认）
   │   JobFilters（jobType 锁定，不渲染招聘类型控件）
   │   计数行：「N 个匹配岗位 · 已展示 M」（撞上限走「N+」）
   │   JobCard 列表 + 加载更多 + 展示时探活
   └─ 视图 B：必投 30 家 —— 现有 CampusBoard，一行代码没改
```

### 4.1 mode 与 jobType 的关系（唯一真相）

`mode` 是两个视图共用的一个状态：

| mode | 视图 A（全部） | 视图 B（必投） |
|---|---|---|
| `campus` | `filters.jobType = "校招"` | 取 `campusFacets` / `campusTotal` 桶 |
| `intern` | `filters.jobType = "实习"` | 取 `internFacets` / `internTotal` 桶 |

映射表 `CAMPUS_MODE_JOB_TYPE` 与强制函数 `withCampusMode()` 放在 `lib/campus-zone.ts`（纯函数，有单测）。

⚠️ **`jobType` 在视图 A 里必须是「粘住的」**：一旦被清空，这个页面就会开始显示社招岗 —— 不报错、不崩，只是专区静悄悄地不再是校招专区。三条泄漏路径全部堵死，每条都有断言：
1. 筛选条 / 筛选弹窗里的「招聘类型」控件 → `JobFilters` 新增 `lockedJobType` prop，两处都不渲染；
2. 已选条件 chip 行里的 `jobType` chip（点一下就清掉）→ `collectActiveChips` 在 `lockedJobType` 时跳过它；
3. 「重置全部 / 清空全部」→ 视图 A 传自己的 `onClearAll` / `onClearOne`，二者都经 `withCampusMode()` 把 `jobType` 写回去。

`useJobFilters` 这个共享 hook **一行不改**（`/jobs` 也在用它）——`onClearAll` / `onClearOne` 本来就是 `JobFilters` 的 prop，视图 A 用 hook 暴露的 `setFilters` 自己实现即可。

### 4.2 视图选择的持久化

`localStorage["campus-view"]`，值 `all` | `must`。
- **默认 `all`**（创始人定的新默认）。
- 读取放在 `useEffect` 里，不放 `useState` 初始值 —— 服务端渲染不出 localStorage，放初始值会 hydration 不一致（CLAUDE.md 因为同类问题立过 SSR 日期时区那块碑）。代价是老用户首帧看到「全部」再切到「必投」，没有布局跳动（两个视图共用同一个页头与切换条）。
- 读写都包 `try/catch`：隐私窗口 / 站点数据被清时 `localStorage` 会抛，不能让页面跟着挂。

### 4.3 移动端与暗色

- 视图切换 / 模式切换用 `@/components/ui` 的 `Segmented`（`ariaLabel` 是必填 prop，`btn-ink-sm` / `btn-soft` 明暗双套令牌）。
- `JobFilters` 在 <lg 自动切成「搜索框 + 筛选按钮 + 底部 Sheet」，`JobCard` 本来就是响应式的 —— 视图 A 不写任何新的响应式分支。
- 计数条用 `.t-*` 字阶 + `.ink-*` 墨色，不写 inline hex。

## 5. 头部的「校招岗位库」计数为什么要单独算

`/api/jobs/search` 的 `total` 是**可翻页条数**，候选撞窗口上限时它只是「取到这么多」。实测 `jobType=校招&sortBy=newest`：`total=1000, capped=true, exactTotal=null` → 按 `formatMatchTotal` 只能显示「1000+」。

`exactTotal` 在这里拿不到，原因是 `exactTotalWhenCapped` 的第 ④ 道门：库里还有 **2,954 行 `recruitment_category is null`**（尚未分类），它们走的是「信号超集」兜底分支，那条不是充分条件 → 主动弃权。这是**对的**（宁可说「1000+」也不给一个证明不了的数字），不要去拆这道门。

所以头部另给一个**库存量级**的精确数，和 `/jobs` 的 `JobLibraryStat` 是同一个先例：

```sql
select
  count(*) filter (where recruitment_category = '校招') as campus,
  count(*) filter (where recruitment_category = '实习') as intern
from jobs
where status = 'active' and recruitment_explicit
  and recruitment_category in ('校招','实习')
  and (grad_class is null or grad_class >= $当季届别)
  and <appendJobScopeWhere>
```

- 口径与 `appendRecruitmentPrefilter` + `appendCurrentSeasonWhere` **逐条对齐**（`recruitment_explicit` 这一条不能少，少了就是 75,744 而列表只给得出 69,138，两个数字打架）。
- 实测 `Parallel Seq Scan` 515ms / 13.3 万 buffers。**必须缓存**：`unstable_cache` 300s，key 只含求职范围（`job_scope` + `target_regions`），不含任何用户私有字段 → 跨用户共享安全。
- 两个数字一条 SQL 出，不发两次。
- 这个数**不参与**列表计数行，两处措辞刻意不同：头部是「库里现在有多少在招校招岗」，列表行是「你当前这组筛选匹配到多少」。

### 5.1 头部计数 vs 列表候选：双向对拍（2026-09-18 全库实测，校招桶）

两个数字必须不打架，而「差多少」有**两个方向**、后果完全不同，所以两个方向各跑一个计数（不报净值）：

| 方向 | 含义 | 实测 |
|---|---|---:|
| **A：列表有、头部无** | 列表能返回的比头条数字多 → 头条**偏小**（少说了） | **2,292** |
| **B：头部有、列表无** | 头条算了但列表返不回来 → 头条**偏大**（吹了，更伤） | **0** |

头部 66,051 / 列表候选 68,343。差额全部来自 A —— 那 2,292 行是 `recruitment_category is null` 走「信号超集」兜底分支进来的。

**刻意不把它们算进头部**：那条超集被文档明确定性为「只能当超集用、不能当等价判据」（live 实测它捞进来的 43% 会被 JS 扔掉）。算进去就会把 B 变成正数 —— **宁可少说 3.4%，不可多说一个**。这与 `exactTotalWhenCapped` 第 ④ 道门是同一条原则。

📌 下次改 `countCampusLibrary` 或 `appendRecruitmentPrefilter` 的任何一边，重跑这张对拍表，**B 必须仍为 0**。

## 6. 诚实边界（写给下一个人）

1. **75,744 ≠ 列表能给出的 69,138。** 差的 6,606 行是 `recruitment_category='校招'` 但 `recruitment_explicit=false` 的岗 —— 分类器判它像校招，但它没有「自报家门」的硬信号。`lib/job-filter.ts` 的既有规则是「选校招/实习 + 岗位无显式信号 → 淘汰，不放行冒充」，这是精度红线（不然一堆默认社招岗涌进来冒充校招，正是「筛实习却全是社招」那个老问题）。**本次不动它**；要动是另一个课题，且必须先逐条核过那 6,606 行。
2. **「1000+」不是 bug。** 见 §5。想让它变成确定数字，唯一正当路径是把那 2,954 行的 `recruitment_category` 算出来，不是放宽计数门。
3. **视图 B 的数字和视图 A 的数字本来就不同**：B 是「必投清单 ∩ 你的行业」的 ~30 家，A 是全库。同一家公司在两处的计数可能不同 —— B 走分面快照（10 分钟）+ `getCampusFreshStats` 现算，A 走检索。这不是漂移，是两个不同的问题域；界面上各自写清楚自己在数什么。
4. **视图 A 没有「届别」筛选项。** 往届岗已被 `appendCurrentSeasonWhere` 在 SQL 里挡掉，剩下的 73% 是 `grad_class is null`（留白 ≠ 隐藏），给一个「全是空值」的下拉没有意义。视图 B 保留届别筛选（它的分面里确实有这个维度）。
5. **视图 A 刻意不按偏好预填城市 / 关键词**（`/jobs` 会预填）。专区的承诺是「这是全部校招岗」，一进来就被关键词硬筛掉一半会让用户以为库里就这么点。个性化交给 `sortBy=match`（**软排序，不藏东西**），不交给硬筛。`jobType` 是唯一的预置项，因为它定义的是「这个页面是什么」，不是「帮你缩小范围」。
6. **不要给视图 A 加新筛选项而不归类。** `lib/job-filter.ts` 的 `SQL_PUSHED_FILTER_KEYS` / `JS_ONLY_FILTER_KEYS` / `NON_FILTERING_FILTER_KEYS` 三张表是 `tests/ux-hardening-contract.test.js` 硬校验的，漏归类只会让计数退回「N+」（fail-safe），但也是回归。

## 7. 验证口径（先量后改）

**改前实测（2026-09-18）**

线上 `https://www.myjobradar.top/api/jobs/search`（匿名可 curl），`x-vercel-id` 前缀均为 `hkg1`：

| 请求 | TTFB | 服务端分段（`x-jobs-search-timing`） |
|---|---:|---|
| `jobType=校招&sortBy=match&limit=20` | 1.63s | `path=scan rows=1000 fetch=644 score=26 tail=572` |
| `jobType=校招&sortBy=newest&limit=20` | 1.07s | `path=scan rows=1000 fetch=557 score=16 tail=13` |
| `jobType=实习&sortBy=match&limit=20` | 1.42s | `path=scan rows=1000 fetch=497 score=7 tail=507` |
| `jobType=校招&city=北京&sortBy=match&limit=20` | 1.94s | `path=fts rows=8000 fetch=1463 score=112 tail=13` |

⚠️ **上表是匿名路径**（`/campus` 要登录，真实用户走的是登录路径）。登录 + `sortBy=match` 走的是
`prescoreOrderBy` 粗排 + 1000 窗，候选 SQL 直接在库上量过（产品方向画像 + 北京/上海）：

| 候选查询 | in-DB 耗时 | 计划 |
|---|---:|---|
| 冷（首次，`read=70062`） | **2.13s** | BitmapOr(GIN `jobs_search_doc_gin` + `jobs_status_first_seen_idx`) → top-N heapsort |
| 温（`read=3620`） | 1.13s | 同上 |
| 热 | **0.24s** | 同上 |

索引是走到的（不是全表扫），大头在 Bitmap Heap Scan 取 10,015 行的随机 I/O —— 这台是 2C2G 轻量服务器，
buffer cache 命中率决定档位。**没有方向词的画像**粗排只剩城市 / 7 天两项，量级同 `/jobs`（CLAUDE.md 已记）。

头部计数 SQL：`EXPLAIN ANALYZE` 515ms / `shared hit=63290 read=70062`（Parallel Seq Scan）→ 故缓存 300s。

**验收（本分支实测）**
- `node --test tests/*.test.js` **1323 pass / 0 fail**（改前基线 1309，新增 14 条）；
  `python3 -m unittest discover -s crawler` **2352 OK**；`npx tsc --noEmit` 干净；
  `npx eslint … lib app components` 退出码 0；`npm run build` 成功（/campus 首屏 JS 9.58 kB / 332 kB）；
  `git diff --check` 干净。
- 新增纯函数（`withCampusMode` / `campusResetFilters` / `CAMPUS_MODE_JOB_TYPE` / `isCampusView`）与三条泄漏路径的契约断言进 `tests/campus-all-jobs.test.js`。
- 契约断言必须覆盖「`jobType` 粘不住」这一类 —— 它是**静默**失效（页面照常渲染，只是混进社招岗），靠人肉走查发现不了。

**还没验的（不许说「做完了」的那部分）**
- **没做登录态真人走查**：`/campus` 要登录，沙箱 Chrome 无登录态、也不允许输密码；本分支未部署，本地 dev 又会写线上库。视觉（移动端 / 暗色）目前只能靠「用的全是既有原语」推断，**不是实测**。
- 「必投视图不再整棵重挂」是靠代码形态断言钉的（`renderMustApplyBoard()` 而非组件标签），**没有跑过真实交互**确认滚动位置不丢。
- 登录态 TTFB 是**从库上推**的（候选 SQL 0.24~2.13s + 传 1000 行 + JS 打分），**没有端到端量过**。
