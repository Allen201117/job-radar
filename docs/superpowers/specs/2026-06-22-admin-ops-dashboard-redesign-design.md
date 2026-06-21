# 管理员运营看板重构设计

> 日期：2026-06-22 ｜ 对象：`/admin/health` ｜ 目标读者：非技术 owner 日常运营监测

## 1. 背景与目标

当前 `/admin/health`（任务 3 初版）的问题：

- **术语多**：`expired / removed / never_checked / partial_success / adapter` 等，非技术 owner 看不懂。
- **有空占位**：「产品使用指标」整块是「待埋点」，看着像没做完。
- **信息密度低、缺"每日视角"**：看不出"今天各模块各干了多少活、跑没跑成"。

**目标**：重构成**一眼看懂、方便日常运营监测**的看板，涵盖产品核心运营数据 + 各功能模块每日战报，且**每个数字都准确、有明确来源**。

## 2. 范围（已与 owner 确认：供给侧优先 + 用户数现成的）

- **本版做**：① 今日健康 ② 各模块每日战报 ③ 岗位库体检 ④ 用户与业务（现成数据）。
- **本版不做**（需新埋点攒数据）：洞察抽屉打开率、零结果搜索率等 → 看板上以「积累中」占位，不空着误导，也不勉强用别的数据硬凑。

## 3. 信息架构（4 块，从上到下 = 从"今天"到"长期"）

### ① 今日健康（顶部 KPI 条 + 一句红绿灯）

3 秒看完今天健不健康：

| 指标 | 大白话 | 数据来源 |
|---|---|---|
| 能投岗位 | 真实可投的高质量岗位总数 | `count_valid_active_jobs()`（香港库） |
| 今日新进 | 今天新入库的岗位 | `jobs.first_seen_at >= 今日0点`（香港库） |
| 今日下架 | 今天确认撤掉的死岗 | 见 ② 死岗模块（台账） |
| 有效率 | 能投 ÷ 在招（薄卡拉低它） | 上面两者算 |

红绿灯综合判断：抓取今天跑了没 + 能投岗位有没有异常暴跌 → ✅健康 / ⚠️注意 / 🔴出事。

### ② 各模块每日战报（核心新增）

一个后台模块一张卡，每张显示 **今日处理量 + 运行状态灯 + 上次运行时间**：

- 状态灯：🟢 今天跑了且有产出 / ⚪ 今天没跑 / 🔴 跑了但全失败。

| 模块（大白话） | 今日指标 | 数据来源 |
|---|---|---|
| 🕷 岗位爬取 | 运行 N 次 / 抓到 Y / 新增 Z / 失败的源 | `crawl_runs`（今日，已有 `jobs_found`/`jobs_added`/`status`）+ `jobs.first_seen_at` |
| ⚰️ 死岗清理 | 探活 X / 判死 Y / 清除 Z | **`ops_runs` 台账（新建）** + `jobs.status` 反推交叉验证 |
| 📄 JD 富化 | 补正文 X / 当前薄卡 Y | `jobs.enrich_checked_at`（今日）+ `ops_runs` |
| 🧭 职业洞察 | 新增 X 条 / 富化 Y 家公司 / 退役 Z 条过期 | `insight_items.created_at`、`company_profiles.insight_checked_at`/`t3_checked_at`、`insight_items(status=retired).updated_at` + `ops_runs` |
| 🔍 刷新 / 发现 | 运行 N 次 / 产出 Y | `discovery_runs`（今日，已有 `results_count`/`mode`） |

### ③ 岗位库体检（中期健康，每周看）

- **岗位构成**：在招 / 已撤岗 / 已下线 占比（`active`/`expired`/`removed` → 中文）。
- **薄卡占比**（无 JD 正文）、**待探活占比**（`enrich_checked_at` 为空，应持续下降）。
- **各招聘源近 7 天成功率表**：揪出一直飘红的坏源（沿用现有表，术语→人话）。

### ④ 用户与业务（现成数据）

- 总用户数 / 今日新注册（`profiles.created_at`）。
- 设了求职偏好的用户数（`user_preferences`）。
- 收藏 / 投递 总量与今日量（`job_actions.action` + `created_at`）。
- 简历解析：今日次数 / 成功率 / AI vs 规则（`events` 表，任务 4 埋点）。
- 洞察：active 总数 / 今日新增 / 待处理申诉。
- 「积累中」占位：洞察打开率、零结果搜索率（待埋点，本版不做）。

### ⑤ 后台模块命名对照（看板里彻底去黑话）

看板里**只出现右边的人话名 + 一句说明**，技术名只在本表留档。②的「每日战报」按**功能**聚合成 5 张卡（一张卡可含多个后台任务）：

| 看板显示名（人话） | 一句话：干嘛的 | 背后的后台任务（技术名，看板不显示） |
|---|---|---|
| 🕷 **岗位抓取** | 每天去各企业官网抓新发布的岗位 | `daily-crawl` |
| 📄 **详情补全** | 给只有标题的"空壳岗"补上职位描述正文 | `enrich-backlog` |
| ⚰️ **死岗治理** | 核查岗位还在不在招、撤掉的清理回收 | `liveness-sweep`（在招核查）+ `dead-link-audit`（网页岗死链巡检）+ `purge-expired`（永久清除） |
| 🧭 **职业洞察** | 给公司补职业洞察、过期的自动下架 | `insight-backlog`（采集）+ `insight-staleness-sweep`（保鲜） |
| 🔍 **刷新 / 发现** | 用户点按钮临时找新公司、新岗位 | `refresh` / `discovery` |

- 每张卡顶部：**人话名 + 一句"它干嘛"** + 今日处理量 + 运行状态灯 + 上次运行时间。
- "死岗治理"卡内再分三行（核查 / 判死 / 清除），但卡名是 owner 一眼懂的"死岗治理"。
- ③「岗位库体检」里招聘源表：**主显示公司名 + 成功率**，技术抓取方式（`adapter` 如 workday/moka）弱化为灰色小字备注，owner 不用懂也能看。

## 4. 数据准确性架构

### 4.1 新增「模块每日台账」表 `ops_runs`（Supabase）

**为什么需要**：死岗清除是 `DELETE`（删了就没）、判死/退役是改状态——这些"今天处理了多少"无法可靠地从结果表反推。台账让每个后台模块**跑完自报成绩**，是②的权威来源。

```
ops_runs(
  id, module text,            -- 'liveness_sweep' / 'dead_link_audit' / 'purge_expired'
                              -- / 'enrich_backlog' / 'insight_backlog' / 'insight_staleness' / 'discovery' ...
  run_date date,              -- 北京时区当天
  metrics jsonb,              -- 各模块自定义：{checked, expired, removed, deleted, enriched, new_insights, ...}
  status text,                -- success / partial / failed
  started_at timestamptz, finished_at timestamptz, created_at timestamptz
)
索引：(module, run_date desc)
```

- 各 workflow 收尾处加一行 `insert ops_runs(...)`（不影响它原本干活）。
- **岗位爬取复用现有 `crawl_runs`**（已细到逐源 `jobs_found`/`jobs_added`），不重复写台账。
- 看板"今日战报" = `crawl_runs`（岗位）+ `ops_runs`（其余模块）聚合。

### 4.2 跨库 + 降级（沿用初版做法）

- 岗位/计数走香港库（`lib/jobs-store`）；`crawl_runs`/`discovery_runs`/`insight_*`/`events`/`ops_runs` 走 Supabase。
- `Promise.allSettled` 并行，一个库挂了另一个照常显示（沿用 `ErrorPanel` 优雅降级）。

### 4.3 准确性验证（实现后必做，写进验收）

实现完成后跑一次**盘点脚本**，把看板每个数字与库里真实 `count` 逐一核对，确认口径一致，再交付。

## 5. UI / 交互

- 沿用暖纸编辑部风格 + 现有 `ProductChrome`/`MetricTile`/`surface`/`Skeletons` 组件与 `loading.tsx`。
- **去术语**：所有英文状态/字段一律译中文人话。
- 顶部「页面生成时间」+ 各模块卡「上次运行时间」。
- 仅管理员（`isAdmin` 门，沿用）；移动端沿用现有响应式。

## 6. 实现拆解

1. 新迁移：`ops_runs` 表 + 索引；admin 聚合函数扩展或新增（`security definer` + 仅 `service_role`，沿用 158 模式）。
2. 各 workflow 加台账写入（`liveness-sweep` / `dead-link-audit` / `purge-expired` / `enrich-backlog` / `insight-backlog` / `insight-staleness-sweep` / `discovery`）。
3. 后端聚合：扩展 `lib/admin-health.ts` + `getJobsHealthSnapshot`（香港库今日聚合）+ Supabase 侧今日聚合。
4. 前端：重写 `app/admin/health/page.tsx` 为 4 块新结构。
5. 测试：纯函数单测（今日战报聚合 / 红绿灯判断 / 术语映射）；准确性核对脚本。

## 7. 待实现时一次性核准（诚实标注，放在实现第 0 步盘点脚本里确认）

- `events` 表确认有 `created_at`（按天聚合用）。
- 各 workflow 脚本结构 → 确定台账写入接入点与各模块 `metrics` 字段。
- 探活改状态时是否更新时间戳 → 决定"判死量"靠台账还是可反推。
- 各模块历史无台账数据 → 台账上线前的"今日战报"先靠现有表尽量反推，台账积累后转为权威源。

## 8. 非目标（本版不做）

- 新前端埋点（打开率/搜索率）；图表库引入（先用现有卡片/表格/占比条，不上重型 charting）；实时刷新（页面级 force-dynamic 即可，不上 websocket）。
