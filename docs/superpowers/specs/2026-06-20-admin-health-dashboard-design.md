# 管理员数据健康面板设计

## 目标

新增仅管理员可访问的 `/admin/health` 页面，聚合香港 PostgreSQL 的岗位质量指标与 Supabase 的抓取、刷新、发现和洞察指标。默认观察窗口固定为近 7 天。

## 数据边界

- 香港 PostgreSQL 只查询 `jobs`。有效在招岗位数必须调用 `count_valid_active_jobs()`。
- Supabase 查询 `sources`、`crawl_runs`、`discovery_runs`、`insight_items`、`insight_disputes`。
- 两库并行读取，任何一侧失败时只让对应区块显示错误，不让整页失败。

## 指标口径

### 岗位库与失活

- 有效在招：`count_valid_active_jobs()`。
- 今日新增：`first_seen_at >= 当日 00:00（Asia/Shanghai）`。
- 今日更新：`last_seen_at >= 当日 00:00` 且 `first_seen_at < 当日 00:00`。
- 薄卡占比：active 中 `summary` 为空或去空白后少于 60 字的比例。
- expired/removed 占比：全部岗位中两类状态合计占比。
- 从未探活占比：active 中 `enrich_checked_at is null` 的比例。

### 抓取

- 每个 source 近 7 天按 `crawl_runs.source_id` 聚合。
- 成功率：`success / (success + partial_success + failed)`；`skipped` 不进入分母。
- partial 比例：`partial_success / (success + partial_success + failed)`。
- 展示运行次数，避免小样本比例误导。

### 刷新与发现

- 从 `discovery_runs` 分别聚合 `mode='company_refresh'` 与其他发现模式。
- 平均耗时只统计同时有 `started_at`、`finished_at` 的终态运行。
- 失败原因优先取 `failure_reason`，为空时取 `diagnostics.failure_reason`，仍为空时归为 `unknown`。

### 洞察

- active 洞察总数。
- active 洞察按 `dimension` 分布。
- 申诉总数和 open 申诉数。

### 待埋点

零结果搜索率、洞察抽屉打开率、简历解析成功率先显示固定占位，明确标记“待埋点”，不以现有事件近似替代。

## 查询与性能

- 香港 PostgreSQL 使用一条条件聚合 SQL；依赖现有 status、first_seen_at 和有效岗位部分索引。
- Supabase 新增只授予 `service_role` 的 `admin_health_snapshot(interval)` RPC，在数据库内聚合并返回小型 JSON。
- 复用现有 `crawl_runs(source_id, started_at)`、`discovery_runs(created_at)` 与洞察 status 索引，不新增重复索引。
- 页面服务端查询使用 `Promise.allSettled` 并行执行。

## 访问控制与页面

- 页面入口复用 `isAdmin()`；非管理员重定向 `/`。
- 页面沿用 `ProductPage`、`ProductHero`、暖纸 surface 样式。
- `loading.tsx` 复用 `MetricTilesSkeleton` 和 `PanelSkeleton`。
- 管理员工具继续不出现在普通导航中。

## 测试与验收

- 纯函数测试覆盖百分比、耗时、失败原因和 Supabase RPC payload 的规范化。
- 源码约束测试确认页面鉴权、有效岗位函数和 loading 骨架存在。
- 执行 `node --test tests/*.test.js`、`npm run build`、`git diff --check`。
- 不 push；真实数字依赖部署环境已配置两库连接与迁移已应用。
