# 后端管线优化（爬虫 + Workflow + CI）— 进度台账

> 目标：把后端抓取管线（Python 爬虫、30 个 GitHub Actions workflow、探活/富化/扩源链路）整体优化到更高效、更稳定。产品行为（抓什么、精度红线）不变。
> 范围：抓取管线为主 + 顺手修 2026-08-26 审阅报告的管线类遗留；LLM 账户已充值恢复（live 验证 HTTP 200）。
> 工作方式：先体检（4 条并行审查线 + 生产库实测）→ 汇总按 ROI 排序清单 → 分批实施，每批验证全绿后 commit + push。
> 若本任务中断：读本文件「优化清单」一节，从第一个未完成项继续；验证四件套见项目 CLAUDE.md；两条 upsert 不变量（_PRESERVE_IF_EMPTY / expired CASE 黏住）不许破坏。

## 体检实测基线（2026-08-28，生产库同日快照）

- active 岗 381,529；expired 待 purge 440；removed 22,023；日新增 ~6,262。
- 探活两极分化：**152,633 岗 24h 内被探过（部分一天 2-3 次）**，但 **198,154 岗（52%）超 7 天未探**、其中 **77,065 从未探过**、42,603 超 30 天。
- never-checked 集中平台：moka 11,455 / 字节 8,400 / 京东 3,205 / 比亚迪 2,752 / ashby 2,745 / 网易 2,227 / 蚂蚁 2,074 / 百度 1,726 / 吉利 1,667 / 宁德 1,650 / 小米 1,273 / 海尔 1,254 / 小红书 1,214 / 国聘 1,101 / zhiye 1,096。
- 7 天未探大头：moka 21,073 / 字节 11,956 / workday 系外企（target/JLL/JCI/AMAT/波音/通用等各 1,300-3,800）。
- SiliconFlow 账户已恢复（最小真实调用 HTTP 200）；insight-t3 / campus-cycle-enrich / campus-official-pages 三条 cron 已恢复在位。

## 体检结论汇总

### A. CI 运行数据实测（agent 待回）

（待填）

### B. Workflow 配置审查（已回）

高：H-1 liveness-sweep workers 文档 6 实际 10（连接峰值被低估）；H-2 enrich-crawl 无 concurrency 无 guard；H-3 enrich-backlog 矩阵含 google 空跑（8 次/天纯浪费）；H-4 dead-link-audit 6 分片无 max-parallel；H-5 dump-jobs-schema 连错库（查 Supabase 空表）；H-6 purge/vacuum 无 timeout（默认 360min）；H-7 ops-watchdog 默认 dry-run（需确认 repo Variable OPS_WATCHDOG_APPLY）。
中：M-1 全部 workflow 无 pip cache（仅 enrich-backlog 一项每天 96 次冷安装，~96-192 分钟/天）；M-2 enrich-crawl httpx tier 也装 Playwright；M-3 UTC 22:00-22:40 四重档叠加；M-4 daily-crawl sweep_limit 死参数；M-5 dead-link-audit limit 描述 1500 实际 1200；M-6 migrate 类无 timeout；M-7 campus-crawl gate 每 20min 白装 setup-python。
低：L-1 无 fetch-depth:1；L-2 auto-discover-overseas 无注释；L-4 campus-official-pages 与 browser-drain 同时 20:00；L-5 jobs-db-data-migrate 一次性脚本留存。

### C. 爬虫代码审查（已回）

P0：#1 enrich_backlog.py enrich_row 网络异常误判 alive 并盖 enrich_checked_at（暗死岗代码根因，需 error 标记分流）。
P1：#2 fetch_liveness_queue 无 20h 冷却（sweep 每日 3 次全量重探小 adapter，40.8 万次/天 → 预计 -55%）；#3 12 个 adapter 在 enrich-backlog 与 liveness-sweep 双探（冷却修法可一并解决）；#4 robots.txt 每源一抓无 host 缓存（每轮浪费 700-800 请求）；#5 should_skip HEAD 无 host 缓存（同量级浪费）；#6 db.py get_discovery_run 重复定义死代码。
P2：#7 avature 不在任何 CI matrix（欧莱雅等既不富化也不探活）；#8 wt 有正文能力但不在 enrich-backlog matrix；#9 tencent/vivo 同上。
P3：#10 liveness-only TIMEOUT=25s 偏松；#11 sweep_absent_jobs 双查询；#12/#13 Supabase 兜底路径缺不变量保护与写重试（prod 不走，低优）。

### D. 审阅遗留核对（已回，逐条对过 diff 而非只信 commit message）

已修：P0-4 验收门 SPA 误杀（69daa71，改走 ENRICH_REGISTRY detail 只认 JobClosedError）；P0-5 央企枚举（5f4f6ee）；P0-8 LLM 保险丝全链（→081ebac 恢复定时）；P0-9 假共识门（ac91fd9）；P1-2 审计 timeout 90→150/limit→1200（但 90min 被杀真凶未查）；P1-3 首项 successfactors 已进 sweep matrix；P1-10 巨潮交叉验证；P2 db-report/production-smoke 已补 schedule。
部分修：P0-6 feishu 坏链**代码门已加**（feishu.py \_detail_portal_closed/should_skip 只认 404/410）但 1,192 条存量坏链是否清掉无证据；P0-7 暗死岗**只清了数据（4028→60）根因代码没动**——enrich_backlog.py L163-193 任何 fetch 异常仍与「真无正文」同路盖 enrich_checked_at，无死信升级，剩余 60 条（wecruit campus/intern 板块）就是活证据。
未动：P1-3 其余 11 adapter 盲区 12,775 岗（jd 3,173/ashby 2,718/antgroup 2,046 占 62%，均有公开 JSON 接口可照 ENRICH_REGISTRY 模式补）；P1-8 gap_funnel entry 身份复核+anti_bot 退避；P1-9 洞察队列仍按 founded_year 排（insight_backlog.py:373）；P1-11 beisen absence 对拍（决策项，维持 dry-run）；P2 iguopin 快车道空转（resolve_detail_cap(300) 在快档 CRAWL_DETAIL_CAP=0 时返 0 → \_detail_verified 全无 → 全丢）；P2 洞察快车道台账永 queued（insight-enrich.yml 无状态回写）；P2 sweep 3 次/天过配；遗留#5 搜索 provider 无账户级判据（search_provider_http.py:50-51 / qianfan_search.py:90-91，status>=300 一律静默返 []，账户欠费=没搜到，gap_funnel/校招链无保护）；遗留#4 看板/watchdog 两套口径；遗留#6 审计 90min 被杀真凶未查。

## 优化清单（按 ROI 排序，实施时逐项打勾；草案，待 CI 数据线校准）

### 批次 1：探活/富化 正确性 + 预算重分配（最高 ROI）
- [ ] 1.1 enrich_row 网络异常与真 miss 分流：fetch 异常走 `err` 不盖 enrich_checked_at；持久失败死信升级（复用 enrich_fail_count），sweep 队列过滤死信（治「盖活章」根因，P0）
- [ ] 1.2 fetch_liveness_queue 加 ~20h 冷却（HK SQL + Supabase 两路径），消同岗日探 3 次 + 12 adapter 双探（探活量预计 -55%，预算自动流向 stale 岗）
- [ ] 1.3 wecruit 空壳判死扩到 postType=campus/intern，并清剩余 ~60 条存量
- [ ] 1.4 enrich-backlog matrix：移除 google（空跑）；补 avature/wt/tencent/vivo（有正文能力不被 drain）；liveness-sweep matrix 补 avature
- [ ] 1.5 盲区探活器补齐（12,775 岗零覆盖）：先 jd/ashby/antgroup（62%），再 haier/mihoyo/iguopin/meituan_campus/phenom/tencent_music/alibaba_campus/pinduoduo；每个探活器判死信号必须真伪 id live 对拍，宁可漏判不可错杀（适合派 Codex 写、CC live 验收）
- [ ] 1.6 feishu 1,192 条存量坏链清理（代码门已在，用 _detail_portal_closed 逐租户 detail 确认后批量标 expired；核验样本量匹配影响面）

### 批次 2：Workflow 配置硬化（纯 yml，低风险）
- [ ] 2.1 liveness-sweep workers fallback '10'→'6'（对齐文档，压连接峰值）
- [ ] 2.2 enrich-crawl 加 concurrency 组 + guard job（仿 enrich-backlog）
- [ ] 2.3 dead-link-audit 主 audit job 加 max-parallel: 3
- [ ] 2.4 补 timeout-minutes：purge-expired 30 / maintenance-vacuum 60 / migrate 20 / jobs-db-migrate 60 / db-report 30 / dump-jobs-schema 10
- [ ] 2.5 pip 依赖缓存：高频 workflow 全部用 setup-python 的 cache: pip（enrich-backlog 每天 96 次冷安装是重灾区）
- [ ] 2.6 enrich-crawl 的 Playwright 改条件安装（httpx tier 不装）
- [ ] 2.7 campus-crawl gate job 去掉 setup-python（用 runner 自带 python3）
- [ ] 2.8 cron 错峰：22:00-22:40 四重档叠加拆开；campus-official-pages 20:00→20:20
- [ ] 2.9 参数一致性：dead-link-audit limit 描述 1500 改 1200（以实际为准）；daily-crawl 删 sweep_limit 死参数
- [ ] 2.10 dump-jobs-schema 改连 HK 库（JOBS_DATABASE_URL）
- [ ] 2.11 ops-watchdog 从 dry-run 转真告警（repo Variable OPS_WATCHDOG_APPLY=true，先核对 watchdog 输出质量再开）

### 批次 3：爬虫代码效率与静默失败治理
- [ ] 3.1 robots.txt host 级进程缓存（每轮省 700-800 请求）
- [ ] 3.2 should_skip HEAD host 级缓存 + timeout 10→5s
- [ ] 3.3 db.py get_discovery_run 重复定义删死代码
- [ ] 3.4 iguopin 快车道空转修（快档 CRAWL_DETAIL_CAP=0 与 _detail_verified 硬门冲突）
- [ ] 3.5 搜索 provider 账户级判据下沉到 search_provider_http.py/qianfan_search.py（欠费≠没搜到，保护 gap_funnel/校招链全部调用方）
- [ ] 3.6 洞察队列排序 founded_year → 无洞察×在招岗位数 desc（insight_backlog.py:373）
- [ ] 3.7 洞察快车道台账回写（insight-enrich.yml 补 status 回写，治永 queued）
- [ ] 3.8 gap_funnel：缓存 entry 身份复核 + anti_bot 30d 退避（P1-8）

### 待 CI 数据线校准后决定
- [ ] 4.x 失败率/超时/schedule 丢失的实测修复项（待 agent A 数据）

## 实施记录

- [x] 体检启动：4 条并行审查线 + 生产库实测（2026-08-28）
- [x] LLM 账户恢复 live 验证（HTTP 200）；三条 LLM cron 已确认恢复在位
- [ ] 清单定稿（等 CI 数据线）
