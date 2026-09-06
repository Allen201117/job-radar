# 2026-09-06 生产只读计数与取证口径

对应 [主报告](../2026-09-06-first-principles-review.md)。以下为数据角色负责的 07:32Z 快照及近 7 天窗口；后续匹配专项查询和登录 GET 是另一批样本，不能混成同一个事务快照。

## 取数边界与证据

- GitHub 只读诊断：本次手动触发的 `db-report` 为 run **34019410735**，2026-09-06 07:32:06Z 发起，07:32:40Z 成功结束。该 workflow 对 jobs 库使用既有严格 TLS 只读通道。
- Supabase 只读 REST：2026-09-06 约 07:32Z 后，以稳定排序和分页读取 `sources`、`crawl_runs`、`ops_runs`、`events`、`job_actions`、偏好及洞察聚合；未输出个人标识、简历正文、连接信息或凭据。
- 数据角色没有执行本机 jobs PG 直连及 EXPLAIN：本地虽存在 jobs 库配置，但严格 TLS 所需 CA/SNI 配置未提供；未降级 TLS 或绕过现有 `jobs_db.connect` 安全通道。

## 当前岗位库（db-report run 34019410735）

| 指标 | 数值 |
|---|---:|
| jobs 库大小 / jobs relation | 1,935 MB / 1,729 MB |
| active / removed / expired | 455,584 / 50,723 / 19 |
| 有效 active（正文 >=60 字） | 439,822（96.54%） |
| 薄卡 active | 15,762（3.46%） |
| 24h 内 seen 的 active | 321,212（70.51%） |
| 从未 liveness 检查 | 105,028（23.06%） |

最新 db-report 的 liveness 年龄桶（互斥，快照时点）：

| 年龄 | active 数 |
|---|---:|
| <=24h | 215,232 |
| 24–72h | 21,550 |
| 72h–7d | 15,032 |
| >7d 且已检查 | 98,742 |
| 从未检查 | 105,028 |

报告中另一个相邻查询显示 never=105,054，系同一 workflow 内两条 SQL 的数秒采样差异；年龄桶使用后一条可闭合的 105,028。

## 源配置与最近 7 天供给动作

当前 `sources` 共有 1,567 条：enabled 1,351、disabled 216。字段实际名为 `crawl_method`：

| crawl_method | 全部 | enabled | enabled 占比 |
|---|---:|---:|---:|
| http | 837 | 760 | 56.25% |
| playwright | 730 | 591 | 43.75% |

这是源配置分布，不能替代真实成功抓取的运行时 HTTP 占比；`crawl_runs` 未保存该维度，故运行时比例未知。

近 7 天窗口：2026-08-30T07:32:06Z 至 2026-09-06T07:32:06Z。

| 数据源 | 样本 | 结果 |
|---|---:|---|
| `crawl_runs` 全量稳定分页 | 46,035 行 | success 41,619；partial 1,013；failed 553；skipped 2,850；unfinished 14；jobs_found 13,679,001；created 122,790；updated 13,555,445 |
| `ops_runs.daily_crawl` | 175 台账行 | success 174、failed 1；sources_total 30,482；success 26,899；partial 661；failed 272；empty 1,505；jobs_found 9,288,591 |

以上是重复抓取、写入和台账工作量，并非新增或唯一 active 岗位数。

## 最近 7 天 liveness

来自 `ops_runs.liveness_sweep` 的 640 条台账：566 success、74 partial；checked 1,475,190，alive 1,449,099（98.23%），expired 11,422（0.77%），missing 4,482（0.30%），failed 7,932（0.54%），enriched 2,255（由 checked 减各结果桶得到），skipped 370。

主要 adapter 的 checked / expired / failed：

| adapter | checked | expired | failed |
|---|---:|---:|---:|
| workday | 687,694 | 758 | 43 |
| wt | 135,417 | 1,433 | 7,616 |
| hotjob | 105,143 | 763 | 44 |
| greenhouse | 88,857 | 615 | 21 |
| amazon | 88,120 | 1,622 | 0 |
| smartrecruiters | 60,813 | 3 | 0 |
| successfactors | 60,062 | 0 | 3 |
| apple | 33,943 | 356 | 159 |
| iguopin | 20,350 | 4,296 | 0 |

`liveness-sweep` 单 adapter 输入阈值为 50,000、workflow 设置 `max-parallel: 4`。本窗口台账最大单行 checked=49,996，等于或超过 50,000 的 checked 行均为 0；但 checked 不是候选队列深度，候选项可能在进入 checked 前被跳过或筛除。因此现有台账没有队列深度实测，不能判断 50,000 阈值是否限制了实际候选量。

GitHub 侧 19 个已完成 liveness workflow 全部 success；created→updated 的平均 74.5 分钟、中位 71.9 分钟、p95/最大 140.4 分钟。它们包含 551 个完成 adapter job，均 success，失败/取消为 0；最长单 job 为 apple 88.9 分钟，未见超过 4 小时。该结果只证明单 workflow 内并行上限=4；未测得跨 workflow 的精确全局并发。

上述 640 条 `ops_runs` 台账与 19 个 GitHub completed workflow 属于不同采样口径和窗口：前者记录 sweep 执行结果（含 partial），后者记录当前列出的 workflow/job 完成状态。两者不能合并计算统一成功率。

当前 db-report 的年龄覆盖只提供全库累计桶（<=24h、<=72h、<=7d、never），即 215,232 / 236,782 / 251,814 / 105,028。adapter 维度仅提供 active、有效正文、never checked、<=24h checked；没有按 adapter 输出 24–72h、72h–7d、>7d 的年龄桶，也没有 A/B/C stale 复检分组或结果。

同一 db-report 快照中，按 active 排名前五 adapter 的核验覆盖如下：

| adapter | active | never checked | <=24h checked |
|---|---:|---:|---:|
| beisen | 102,976 | 44,640（43.35%） | 2,850（2.77%） |
| workday | 102,001 | 0（0.00%） | 88,808（87.07%） |
| moka | 49,472 | 11,989（24.23%） | 2,756（5.57%） |
| wt | 19,217 | 0（0.00%） | 18,854（98.11%） |
| hotjob | 15,352 | 0（0.00%） | 15,350（99.99%） |

这张表仅描述当前 active 库的最后核验时间，不能替代本周 liveness 执行成功率或候选队列深度。

## 用户需求和行为（匿名聚合）

事件近 7 天共 965：

| 事件 | 次数 |
|---|---:|
| page_view | 369 |
| search_result | 177 |
| job_click | 127 |
| radar_feed_opened / radar_open | 68 / 68 |
| radar_onboarding_required | 42 |
| job_action | 35 |
| opportunity_official_opened | 13 |
| insight_drawer_open | 12 |
| opportunity_click | 12 |

一次全量 `job_actions` 快照为 665 条：viewed 522、ignored 69、saved 62、applied 12；其中近 7 天 viewed 96、saved 13、ignored 8、applied 7。该表在读取期间仍有实时写入，后续快照已变为 681，不能将差额解读为回归。

偏好匿名覆盖（51 条偏好记录）：角色/关键词/目标公司至少一项已填 39；目标地点已填 40；技能已填 1；阶段为空 21、校招 18、实习 6、社招 6；求职范围 domestic 36、all 10、overseas 5。

已生成 28 份匿名真实画像回放输入：target_roles 数量分布为 0/1/2/3/4 = 11/11/2/1/3；阶段为空/实习/校招/社招 = 4/7/12/5；12 份有地点；范围 domestic 27、overseas 1。文件只含类别、布尔和计数，不含 user_id、邮箱或简历文本；本数据采集步骤未执行 live jobs 回放，后续专项的 17 份核心链结果另列，不能混算。

历史 `job_actions.job_snapshot` 中有 143 个非空岗位快照，143 个均含 jd_url。本数据角色因严格 TLS 直连不可用，未完成 “旧快照 jd_url 对应当前不同 job id” 的跨库确认。

## GitHub 运营状态

- 最新 `ops-watchdog`：run **34014201740**，2026-09-06 05:31:30Z–05:33:11Z，workflow 自身 success，但日志报告 15 项发现：包括 14 条未完成 crawl 记录、部分自动扩源链路零产出、7 个持续失败 source，以及 dead-link-audit/enrich-crawl 的已取消 job。绿灯仅表示 watchdog 成功完成检查，并不表示业务无问题。
- 备份/PITR issue **#3** 仍为 OPEN；创建和最后更新均为 2026-07-11。最后评论的临时例外已于 2026-07-18 失效，未见更新的备份、PITR、恢复演练或容量证据。

## 活跃洞察聚合

active `insight_items` 14,538：grade=fact 11,202、experience 3,336；assertion=signal 10,824、claim 3,336、fact 378。experience 且 assertion 为空为 0。

sample_size>=5 的 13,715 条中，按 `insight_sources.deidentified=true` 计有效绑定源：0 个 10,824、1 个 9、至少 2 个 2,882。零源项均为 derived signal；排除 signal 后，有 sample>=5 的 2,891 条中 0 源为 0、1 源为 9、至少 2 源为 2,882。

## 局限

- 数据角色未执行本机 jobs PG 的连接数、`pg_stat_activity` 或 EXPLAIN，避免在未配置严格 TLS CA/SNI 时削弱现有安全约束。
- 自定义域 stats 的单样本 200 为 4.85 秒（validActive=439,822、recent24h=321,212、sources=1,351）；原 Vercel 域 curl 35 秒超时，浏览器桥接 tab 也超时或空白。这批访问只能说明当时该路径无法完成 E2E，不构成生产 500；后续登录 GET 已成功，见匹配取证。
- 数据角色只准备匿名画像输入。后续匹配角色完成了其中 17 份核心链回放，详细输入边界、连接方式与登录 GET 见 [匹配取证](matching-measurements.md)，不得把核心链等同完整用户体验。
