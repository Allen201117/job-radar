# 2026-09-07 岗位与洞察生命周期：只读调度证据

取证时刻：2026-09-07T02:20:00Z。范围为最近 24 小时 GitHub Actions 的 completed 状态与经日志筛出的匿名业务计数；未触发 workflow、未直连 PG、未读取环境变量值或凭据。

## 洞察链路

| 链路 | 最新 completed run（UTC） | 状态 | 日志中的业务结果 |
|---|---|---|---|
| T2 官方事实 refresh（`insight-enrich`） | 34063423994；09-06 22:14:19–22:15:08 | success | 队列 1；ok 1、noface 0、err 0。一条可选官方来源请求超时，但未使本轮失败。 |
| T3 经验层 refresh（`insight-enrich-t3`） | 34065579018；09-06 22:59:33–23:09:49 | success | 可用搜索预算 53、队列 53；写入 7、empty 1、err 0。触及校招预留线后停止，剩余候选并未在本轮清空。主题门拦下 7 条、转投 1 条。 |
| 档位提取（`insight-grade`） | 34069573933；09-07 00:21:48–00:23:20 | success | apply 模式；扫描/请求 226，判出并写入 25，未判出 201；LLM 调用 12、失败批次 0、未耗尽额度。 |
| 主体抽取 + signal 派生（`insight-subjects`） | 34068018306；09-06 23:50:52–09-07 00:08:47 | success | 抽取：扫描 1,086 公司，保留 574，insert 4、update 1,663、retire 0、failed 0。派生：扫描 1,150 公司 / 1,732 主体，1,601 有指标，写入 10,487、retire 13、snapshots 1,732、failed 0。 |
| A 股年报官方事实（`insight-annual-report`） | 34064022867；09-06 22:26:23–22:31:11 | success | 40 候选，checked 40、parsed 1、written 2、section_not_found 3、already_latest 36、failed 0。真实有新增，但多数已是最新。 |
| 过期下架（`insight-staleness-sweep`） | 34061241245；09-06 21:29:52–21:30:16 | success | retired 0；本轮没有满足 `valid_until` 已过期且仍 active 的条目。 |

当前 workflow 列表中没有名为 `topic_sweep` 的独立调度。最接近的 `insight-staleness-sweep` 执行的是 `insight_sweep.py`，职能仅为按 `valid_until` 下架过期 active 条目，不能把它视为主题目录、主题覆盖或主题质量巡检已经运行。

最新 T3 与 grade 均有实际搜索/LLM 工作量，日志没有显示缺失凭据或账户级 LLM 故障；这只证明本次所用路径可用，不能推出全部 provider 均已配置，亦不能代替后续的台账回读。T3 的预算预留机制已造成明确的当轮限流式部分完成，不是“成功即已清空待办”。

## 岗位库生命周期

| 链路 | 最新 completed run（UTC） | 状态 | 日志中的业务结果 |
|---|---|---|---|
| 列表抓取（`daily-job-crawl`） | 34052519950；09-06 18:41:27–19:05:15 | success | 844 成功、8 失败、20 空源、52 跳过；created 11、updated 269,613。它是抓取/写入工作量，不代表唯一新增岗位。 |
| 逐岗探活（`liveness-sweep`） | 34067355848；09-06 23:36:18–09-07 01:29:25 | success | 36 个 Actions job 均 success；其中 29 个 adapter 分片输出：checked 132,037、alive 130,982、miss 421、expired 262、failed 372、skipped 0。 |
| 已确认 expired 清理（`purge-expired`） | 34018637363；09-06 07:15:04–07:15:44 | success | 精确删除 1,903。07:15:41Z 的 workflow 内快照：active 455,602、removed 50,723、expired 1。该快照不是当前实时总量。 |

liveness 的 `checked` 为实际探测返回项（filled + alive + miss + expired + failed），不含 skipped；本轮 alive 为 99.20%（130,982 / 132,037）。按此前确认的 F3 语义，`alive` 仅表示该次逐岗处理没有给出撤岗或错误结果，不能推成完整存量的“真实存活率”、唯一岗位数或净增量。miss/failed 不会被盖为 alive，仍留待后续轮次处理。

## 证据边界

- 本报告的 run 状态来自 `gh run list`，吞吐来自对应 `gh run view --log` 的最终聚合行；这是 workflow 内业务输出，不以 GitHub 绿灯替代业务产出。
- 各脚本会尝试写 `ops_runs`，但该写入设计为非阻断。本次没有重新查询 Supabase `ops_runs`，所以不能把“workflow 成功”或日志输出表述为“本次台账已被独立读回确认”。
- 昨日的 7 日 liveness 台账、db-report 和画像数据未重取；它们不用于判断本次 24 小时调度是否成功。
