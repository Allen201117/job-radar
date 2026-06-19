# 任务交接 Prompt：求职雷达 — JD 正文覆盖率（治薄卡，主攻 moka）

> 整段交给执行 agent。自包含：执行者对本会话无记忆。完成后由主 agent live 复核。

---

## 你的角色与使命

你是「求职雷达 / Job Radar」（`/Users/bytedance/Desktop/求职雷达`）的爬虫工程师。
首页「岗位库」计数用 `count_valid_active_jobs()` = **active 且有 JD 正文 ≥60 字**（项目原则#4：薄卡不算「有效在招」、不进计数）。
**使命**：把库里大量「能打开但无 JD 正文」的薄卡补上正文，把全库 JD 覆盖率从 79% 拉高，**主攻 moka**。

## 真实覆盖数据（主 agent 2026-06-20 live 实测，香港库）

| adapter | active | 有JD≥60 | 覆盖% | 薄卡(thin) | 备注 |
|---|---|---|---|---|---|
| **moka** | 27,337 | 255 | **1%** | **27,082** | **全库薄卡的 76%，绝对主攻** |
| wt | 69,598 | 64,396 | 93% | 5,202 | 尾巴 |
| feishu | 8,267 | 6,937 | 84% | 1,330 | 尾巴 |
| beisen | 35,160 | 34,567 | 98% | 593 | 基本好 |
| amazon / phenom / google / siemens / microsoft | — | 0 | **0%** | ~660 | 外企，**无 enrich handler**（见下 C） |
| huawei | 436 | 191 | 44% | 245 | |
| **全库** | **168,911** | **133,450** | **79%** | **35,461** | |

> 新加大厂 httpx 源（meituan/bilibili/pinduoduo/vivo/sf_express）已 99% 内联补正文，**别动**。byd 见下 B。

---

## ⚠️ 铁律

1. **不许编造正文**。summary 必须是**真实抓到的 JD 正文**（职责/要求等），≥60 字才算数。禁止用标题/占位/拼凑充数（原则#4：指标诚实）。
2. **不破坏已覆盖的源**。只补薄卡，不动已有正文。
3. **诚实记录上限**：moka 27k 是浏览器逐岗渲染补正文，**慢**——若 CI 预算下只能覆盖一部分，如实报「本轮覆盖 N、剩余 M、瓶颈=单岗渲染耗时」，给可持续的分批方案，别假装全清。
4. 最小化改动，复用现有富化底座（见下），别另起炉灶。

## 现有富化底座（务必复用，先读懂）

- `crawler/enrich.py`：按 adapter 的 detail handler 注册表（`jd_url` 反推 detail 端点 → 抓 JD 正文）。现有 handler：workday/oracle/eightfold/smartrecruiters/greenhouse/lever/hotjob/wt。**新增 adapter 的富化在这里加 `_detail_xxx` + 注册**。
- `crawler/enrich_backlog.py`：薄卡队列 drain（按 `enrich_checked_at`/source 索引取工作队列，死信、每线程 sb、按 host 限流）。httpx 类薄卡走这里。
- `crawler/backfill_moka_summaries.py`：**moka 专用逐岗浏览器渲染补正文**（2026-06-18 修过取数超时）。**moka 的主路径就是它**——先搞清它为什么没把 27k 补上（没进 CI 定时？跑太慢追不上？坏了？）。
- workflows：`enrich-backlog.yml`(httpx) / `enrich-backlog-browser.yml`(浏览器) / `dead-link-audit.yml`。
- 迁移 150/151：source 前导部分索引（让队列查询脱离 8s 超时，别让你的查询又撞超时）。
- `count_valid_active_jobs()`（迁移 151）= 计数口径；`db-report.yml` 只读出 status/有效率/分 adapter。

## 任务（按价值排序）

### A. moka 27k 薄卡补正文（主攻，占 76% 的窟窿）
- moka detail JSON 加密 → 必须浏览器逐岗渲染取正文（`backfill_moka_summaries.py` 的路数）。
- **先诊断**：跑/读 `backfill_moka_summaries.py`，确认它现在能否对一个真实 moka 薄卡抓到正文；查它有没有定时 workflow、为什么 27k 没被补上。
- **再规模化**：让它**可持续分批**把 27k 薄卡补上（参照 enrich-crawl 的 host-aware 分片 / 按 `enrich_checked_at` 最旧轮转）。浏览器逐岗慢，**算清吞吐**（单岗渲染秒数 × 27k ÷ 并行）给出「每天能补多少、几天补完」的现实方案；优先补**最近/目标相关**的 moka 岗。
- **目标**：moka 覆盖率从 1% 显著拉高（给出本轮实补数 + 可持续清完的方案）。

### B. byd 薄卡（新源，刚上线，约 2k 将为薄卡）
- byd 列表 2037 但 `DETAIL_CAP=20`（`crawler/adapters/byd.py`）→ 仅 20 个有正文。
- **好消息**：byd 详情 `queryDetail` 是**公开 httpx 接口**（`https://job.byd.com/portal/api/portal-api/position/queryDetail`，POST id）。
- **修法**：byd 抓取时用 **httpx queryDetail 批量补全部 2037 的正文**（不是浏览器、很快），把 `DETAIL_CAP` 提到覆盖全量（或去掉）；或加 `enrich.py` 的 `_detail_byd`（注意 byd 的 `jd_url` 是 AES 加密 token，反推不出 id → enrich-by-jd_url 不可行，所以**首选抓取时内联用 queryDetail 补全**，positionId 在抓取上下文里现成）。
- **目标**：byd 覆盖率→高（live 验证 summary≥60）。

### C. 外企 0% 覆盖（amazon 386 / phenom 121 / google 59 / siemens 57 / microsoft 40）
- 这些 bespoke 外企 adapter **不在 enrich.py 注册表**里 → 薄卡补不上。
- **修法**：确认它们抓取时是否内联抓 detail；没有则在 `enrich.py` 加 `_detail_amazon`/`_detail_phenom`/... handler（`jd_url` → detail 端点 → JD 正文），注册进表，让 `enrich-backlog` 能 drain。google 若是无头 DOM 抓取，参照 moka 走浏览器富化。
- **目标**：这几个从 0% 拉到有覆盖（量小，主要是补齐 handler 缺口）。

### （D. 低优尾巴）wt 5.2k / feishu 1.3k / beisen 593：已高覆盖，时间够再扫；多半是撤岗/detail 偶发失败的残留，别花大力气。

## Live 访问 / 验证（沙箱）

- 联网/DB 必须 Bash `dangerouslyDisableSandbox: true`；`set -a && source /Users/bytedance/Desktop/求职雷达/.env.local && set +a`；**绝不打印密钥**。
- 香港 jobs 库：`psql "$JOBS_DATABASE_URL" -c "..."`（会话 TZ=Asia/Shanghai）。
- **覆盖率自测查询**（改进前后都跑）：按 source_id 聚合 `count(*) filter(where status='active')` 与 `... and char_length(coalesce(summary,''))>=60`，join Supabase sources 的 adapter_name（node + @supabase/supabase-js，REST 分页 1000/页；jobs 表无 adapter_name）。
- 浏览器富化需 chromium：`cd crawler && python3 -m playwright install chromium`（本机无 `timeout` 命令，别用它包裹）。
- 单源富化自测：对一个真实薄卡 id 跑 detail handler / backfill，确认抓到 ≥60 字真实正文。

## 验收标准（主 agent 将 live 复核）

- [ ] **moka**：覆盖率从 1% 明显提升；给出本轮实补数、可持续清完 27k 的分批方案 + 吞吐测算；抽样几条 moka 岗 live 看 summary 是真实 JD≥60。
- [ ] **byd**：覆盖率→高（queryDetail 内联补全），live 抽样验证。
- [ ] **外企 0% 五家**：补齐 enrich handler，覆盖率>0，live 抽样验证。
- [ ] 全量 crawler 单测绿；新增 handler 有单测（喂样例 detail 响应给 parse，不打网络）。
- [ ] 返回总表：adapter | 改进前覆盖% → 后 | 做法 | 抽样真实正文片段 | 剩余/瓶颈（诚实）。
- [ ] 全库有效计数（count_valid_active_jobs）改进前后对比。

## 提交

- 每块清晰 commit。**push 前与主 agent/用户确认**（push 触发生产迁移与抓取），除非另有授权。
