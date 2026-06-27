# 爬虫吞吐 & 编排改造设计（有效性 + 新鲜度）

> 状态：设计已确认（2026-06-28）。**阶段 A 已实现 + 测试 + 真机验证 + 本地 commit（未 push）**；阶段 B/C 已排定。
> 实施记录见文末 §9。
> 作者：Claude（应用户「岗位库新增慢 + 今日机会不够新」诉求脑暴）。
> 基线分支：`claude/dreamy-carson-1f0739`（worktree）。

## 0. 一句话结论

岗位库的真正瓶颈**不是抓取量**（~1500–2100 新岗/天 ≈ 接近市场真实速度），而是 **64% 的在招岗（8.2 万）被关在"慢浏览器车道"**——抓新 1 次/天、探活 7 天才轮一遍永远追不上。本设计把能 httpx 化的 SPA 源（feishu 已验证、beisen 高把握）搬进 4 次/天的 httpx 快车道，浏览器车道缩到只剩真硬骨头（moka），从而**同时**修好「有效性」（探活覆盖）和「新鲜度」（大厂新岗提频）。

## 1. 实证诊断（2026-06-28 真机 + 香港库实测）

### 1.1 抓取量不是问题
- 看板「852 今日新进」是**半天数**（截图 UTC 12:00，4 次抓取才跑 2 次）。
- 干净日（6/21–6/26）真新增 **1368–2144/天**；6/15 的 79230 + 之后几天上万全是「库重建回填」污染。
- 836 源中 24h 内 **791 个被重新抓到刷新**、仅 **195 个真出新岗** → 大部分公司官网本就没几个新坑，硬冲量只会抓回更多重复。

### 1.2 真瓶颈 = SPA 源被关慢车道（香港库 per-adapter 实测）

| 平台 | active 岗 | **从没探活** | 24h 探活 | 抓取方式 | httpx 可行性（实证） |
|---|---|---|---|---|---|
| beisen 北森 | 40,714 | **34,413** | 5,326 | 浏览器 | ✅ 高把握：PortalId 已实测在页面 HTML 里（leapmotor/sunwoda 冷 httpx 直取）；端点需 1 次抓包 |
| moka | 29,227 | **25,506** | 3,099 | 浏览器 | ❌ 真不行：列表接口密文反爬（necromancer），httpx 只拿到密文 |
| feishu 飞书 | 8,410 | **7,833** | 382 | 浏览器 | ✅ 已验证：`dcar.jobs.feishu.cn` 冷 httpx 返 count=574 真实岗位 |
| feishu 变体(nio/xpeng/xiaomi) | ~2,100 | ~2,050 | ~18 | 浏览器 | ✅ 同 feishu |
| wt/hotjob/workday/meituan/apple/amazon/tencent/vivo/bilibili/sf_express/eightfold/greenhouse… | — | **0** | 全部 | httpx | ✅ 已在探活车道，24h 内 100% 核实 |
| alibaba/netease/ctrip/xiaohongshu/huawei/jd | — | **~7,500** | 极少 | httpx | ✅ 是 httpx，**只是漏配进探活车道** |

三条关键事实：
1. **httpx 探活车道运转完美**（wt/hotjob/workday… 24h 100% 核实）。整个「64% 没探活」几乎全压在 beisen 34k + moka 25.5k + feishu 10k ≈ **68k（占全部未核实 82%）**。
2. **~7,500 个 httpx 岗漏配进探活车道**（alibaba/网易/携程/小红书/华为/京东）——零风险立刻能修。
3. **feishu/beisen 探活可几乎免费**：既然能 4 次/天 httpx 拉**全量**列表，「上次在、这次全量列表没了」= 下架（list-absence），不需要 SPA 壳详情页那套浏览器看文字。

### 1.3 附带老毛病
- **病灶 C — 新鲜信号坏了**：「今日机会」判新靠 `jobs.first_seen_at`，但它被 6/15 库重建全冲成同一天；干净的 `job_events.FIRST_SEEN`（append-only）6/25 才开始记。
- **病灶 D — 大源页数封顶（次要）**：netease 800/2452、alibaba 500，翻页之后的新岗被截。

## 2. 当前编排现状（改造前基线）

| Workflow | cron(UTC) | 并行 | 处理对象 | 关键限额 |
|---|---|---|---|---|
| daily-crawl | 1,7,13,17（4×/天） | 单 runner / 10 线程 host-queue | **仅 httpx 源**，list-only（DETAIL_CAP=0） | step 50min；浏览器源被排除 |
| enrich-crawl | 18（1×/天） | matrix shard 0–5（6×） | **浏览器源**（beisen/moka/feishu/google/bytedance/tencent）列表+逐岗正文 | 180min |
| enrich-backlog | */3（8×/天） | matrix 5 adapter | hotjob/workday/oracle/eightfold/smartrecruiters 补正文 | limit 20000/分片 |
| enrich-backlog-browser | 20（1×/天） | matrix 6 分片 | moka 正文渲染补全 | ~9000/天封顶 |
| liveness-sweep | 4,12,20（3×/天） | matrix 15 adapter，max-parallel 4 | httpx 源逐岗探活 → expired | limit 50000/adapter |
| dead-link-audit | 22（1×/天） | matrix 6 分片 | **SPA 浏览器探活**（moka/beisen/feishu）软 404 | ~9000/天，**全量轮一遍 ~7 天** |
| dead-link-audit-new | 1,7,13,19（4×/天） | 单 runner | 近 48h 新 SPA 岗优先探活 | 300/run |
| purge-expired | 2:30（1×/天） | 单 runner | DELETE status=expired + VACUUM | — |

## 3. 目标设计：三条车道

### 🚀 车道 1 — httpx 快车道（便宜、可扩、4 次/天）
- 跑所有 httpx-capable 源；**新增 feishu + beisen 新版租户**进入此车道。
- **探活两招免费拿**：
  - ① **list-absence 探活（新机制，complete-pull 守卫）**：某源本次 httpx 抓取**抓全了**（翻到 total、非 error/非截断），则该源「上次 active、这次全量列表里没出现」的岗 → `expired`。
  - ② 现有逐岗 httpx 检测器（wt `req_state=9501` / hotjob `state=1017` …）继续作为有详情端点源的兜底。
- **补 6 个漏网 httpx 源进探活**（alibaba/netease/ctrip/xiaohongshu/huawei/jd ~7.5k）：优先用 list-absence（它们已在 daily-crawl httpx 抓取里）。
- 效果：**~58k 岗（beisen 40k + feishu 11k + 漏网 7.5k）拿到当天新鲜 + 当天探活**，几乎零额外成本。

### 🐢 车道 2 — 浏览器车道（缩到只剩真硬骨头 ~25–30k）
- 只留 moka（密文反爬）+ beisen 老 SSR 租户 + byd/快手/google/bytedance 等自建 SPA。
- 列表抓取（enrich-crawl）源变少 → 跑得快 → **1 次/天 提到 2 次/天**。
- 探活（dead-link-audit）从面对 82k 缩到 ~25–30k → 现有 ~9k/天 **追得上（~3 天一轮 vs 永远追不上）**，优先「从没探过 + 最新」。

### 🛡️ 车道 3 — 展示时兜底（已存在，复用）
- `/api/jobs/liveness-check` + `lib/liveness-client.js` 验用户当下看到的岗；feishu/beisen 有 httpx 探活后，SPA 岗展示时探活也变便宜（后续可加 fetch 检测器）。

### 病灶 C/D 修复
- **新鲜信号**：「今日机会」/雷达 feed 排序与「新发现」判定改读 `job_events.FIRST_SEEN`（干净 append-only），不再用污染的 `first_seen_at`。降级：job_events 无记录的老岗 fall back `first_seen_at` 但不参与「新发现」加权。
- **大源页数封顶**：netease / alibaba 等高翻动源抬封顶到能覆盖真实在招量（次要，列入 Phase C 调参）。

## 4. 分阶段实施

### 阶段 A — 稳赢快赢（低风险，本轮交付）
**A1. feishu 列表 httpx 化（已实证）**
- `crawler/adapters/feishu.py`：`fetch()` 改 **httpx-first**——直接 `POST https://{host}/api/v1/search/job/posts` 翻页到 `data.count`；失败/空才回退现有浏览器抓包链。
- httpx 路径下游响应 shape 与现有 `{"_intercepted":[{"data":{"job_post_list":[...],"count":N}}]}` 保持一致，`parse()` 不动。
- 标记**本次抓取是否抓全**（翻到 count）→ 供 list-absence 用。
- 接线：把 `feishu` 加入 `crawler/run.py` 的 `_HTTPX_SAFE_ADAPTERS`，使其进入 daily-crawl `--tier httpx`（4×/天）。**同时保留** enrich-crawl 浏览器路径作为过渡兜底（httpx 稳定数日后再摘）。
- daily-crawl 环境无 Playwright → httpx 路径必须自给，失败当次跳过（不崩整轮）。

**A2. list-absence 探活机制（新，可复用）**
- 新纯函数 `crawler/liveness_absence.py`（+ 测试）：输入 `(source_id, 本次抓取 canonical 集合, complete: bool, 该源现存 active 岗集合)` → 输出应 expire 的 job_id 列表。
- **complete 守卫（防误杀，最高优先级不变量）**：仅当本次抓取 `complete=True`（adapter 翻到 total 且非异常/非截断）才执行；任一不确定 → 不 expire。被截断的大源（netease/alibaba 旧封顶）永不走 list-absence。
- 写库：复用 `markJobExpiredById` 同口径，写 `status=expired` + `confirmed_closed_at` + `job_events.CLOSED`。
- 在 `crawler/run.py` 抓取每源后调用（只对声明 `supports_absence_liveness=True` 且 complete 的源）。feishu + 6 个漏网 httpx 源先用它。

**A3. 新鲜信号接 job_events（本轮核查结论：保持现状，不强行开启）**
- 核查发现代码**已正确处理**：`NEWLY_DISCOVERED` / `COMPANY_MOMENTUM` 信号在 `lib/opportunities/signals.ts:3` /
  `types.ts:50`（「first_seen 污染下不可用」）/ `grouping.ts:9`（「momentum 恒空，job_events 前不上」）**已被显式 gate**。
- 这是项目按 Phase 3 正确的时序决策：依赖 `job_events`（FIRST_SEEN 2026-06-25 起 append-only）攒够干净数据
  + 6/15 重建污染随 7 天窗自然消退。**现在强行翻开 = 拿没攒够的数据上 C 端「猛招/新发现」，反而误导。**
- 故本轮**不改**：到时（job_events 攒够 + 污染清）翻 gate 即可，无需新代码。`opportunities.ts` 的
  `first_seen_at >= sinceIso` 近 7 天窗，6/28 已离 6/15 污染 13 天、窗口移出污染区，自愈。

**A4. 6 个漏网 httpx 源进探活**
- alibaba/netease/ctrip/xiaohongshu/huawei/jd：优先 list-absence（A2）；若其 daily 抓取被封顶截断不可用 absence，则建逐岗 httpx 检测器（Phase C 再说）。

**A 阶段验收**：`db-report` 探活覆盖率 SQL 改造前后对比（never_checked% 下降、checked_24h% 上升）；feishu httpx 真机抓取确认 created>0；回归四件套全绿。

### 阶段 B — beisen httpx 化（最大奖，先 spike）
**B1. Spike（先做，gate 后续）**
- 取 ~10–15 个代表 beisen 租户（覆盖 social/campus、新版/老版）。
- 步骤：① httpx GET 列表页 HTML 抽 `PortalId`（已证可行）② 用现有浏览器适配器抓一次包，记录确切 `GetJobAdPageList` 端点 host/path ③ 用该端点 + HTML 抽的 PortalId 冷 httpx 重放，确认返回真实岗位。
- **过线阈值**：≥70% 代表租户冷 httpx 可达 → 建 httpx 适配器；否则 beisen 留浏览器车道，止于此。
- **同时验证**：beisen 列表是否只返「在招」岗（list-absence 安全前提）；若夹带已关闭岗 → list-absence 对 beisen 禁用，改逐岗 detail 探活。

**B2.（spike 过线才做）beisen httpx 适配器**
- `crawler/adapters/china_ats.py` `BeisenAdapter`：httpx-first（HTML 抽 PortalId → httpx 翻页 GetJobAdPageList），失败回退现有浏览器抓包 + SSR 链。
- 加入 `_HTTPX_SAFE_ADAPTERS` 进 daily-crawl 4×/天 + list-absence 探活。老 SSR / httpx 不可达租户继续浏览器车道（按租户回退，不一刀切）。

### 阶段 C — 浏览器车道收尾 + 诚实计数
- enrich-crawl / dead-link-audit 重新圈定到**只剩真浏览器源**（moka + beisen-old + byd/快手/google/bytedance）；enrich-crawl 1×→2×/天。
- dead-link-audit 优先级：`enrich_checked_at IS NULL`（从没探过）+ 最新优先；honest rotation。
- **§4 诚实计数对齐**：从没验过且老（first_seen 超 N 天 + enrich_checked_at 为空）的浏览器岗，不计入首页「有效在招」（或显式标注），避免数字虚高。
- 大源页数封顶调参（netease/alibaba）。

## 5. 不变量 / 防坑（改任一处务必保住）

1. **list-absence 必须有 complete 守卫**——截断/异常抓取永不 expire（见 [[job-radar-job-expiry-closed-detection]] 「通用 staleness sweep 不可行」的教训：故意只抓部分会误杀）。
2. **upsert 既有不变量不破**：`status` 走 `CASE` 黏住 expired（list 重抓不复活死岗）；`_UPDATE_COLS` 不含 enrich 簿记；`_PRESERVE_IF_EMPTY`（summary/job_type/…空值 COALESCE 保留）三处同口径（jobs_db.py / write.ts）。
3. **httpx-first 必有浏览器回退**（按源/租户级），daily-crawl 无 Playwright 时 httpx 失败当次跳过、不崩整轮、不写空。
4. **canonical 三处同步**（lib/canonical-url.js / crawler/normalizer.py / jobs-db/schema.sql）——本设计不改 canonical，但 absence 比对必须用 canonical_jd_url。
5. **写入端 HK 报错不回退 Supabase**（避免孤儿数据），沿用现有 gated 约定。
6. **moka 不强行 httpx 化**（密文反爬，会得到密文/空，反而误判）。

## 6. 验证策略
- 纯函数优先测：list-absence（complete 守卫 / 空集 / 截断不杀 / 正常 expire 差集）、feishu httpx 翻页解析 & 抓全判定。
- crawler unittest 不打真实网络（mock httpx）。
- 真机验证（自己做，网络通）：feishu httpx 抓取 created>0；beisen spike 可达率；db-report 覆盖率前后对比。
- 回归四件套：`node --test tests/*.test.js` + `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` + `npm run build` + `git diff --check`。

## 7. 风险 & 回滚
- **list-absence 误杀**：complete 守卫 + 先只对「翻得到 total」的源开 + 灰度先看 expired 量是否异常。回滚=关 absence 开关，岗位回 active 由下次抓取自然恢复（status CASE 不挡 active 写入新岗）。
- **feishu/beisen httpx 被风控**：保留浏览器回退；httpx 失败不写空。回滚=从 `_HTTPX_SAFE_ADAPTERS` 摘掉该 adapter 即回纯浏览器旧路。
- **beisen 租户异构**：spike 阈值门 + 按租户回退，不达标的留浏览器。
- **GitHub Actions 额度**：httpx 远比浏览器省，本设计净省额度。
- **香港库连接上限 100**：httpx 探活走轻连接，沿用现有 PER_HOST/max-parallel 约束。

## 8. 交付边界（本轮）
- 本轮交付 **完整 spec（本文件）+ 阶段 A 实现 + 测试 + 真机验证 + 本地 commit**（草稿分支，**不 push**，待用户「上线」指令）。
- 阶段 B/C 在本 spec 完整排定；B 的 spike 为其第一步任务。

## 9. 实施记录（2026-06-28）

### 已完成（commit 在草稿分支 claude/dreamy-carson-1f0739，未 push）
- **feishu 家族 httpx-first**（`crawler/adapters/feishu.py`）：httpx 直拉 posts API + 浏览器回退 + `fetch_complete` 标记；
  加入 `crawler/run.py` `_HTTPX_SAFE_ADAPTERS` → 进 daily-crawl 并发档 4×/天。
- **list-absence 探活**（`crawler/jobs_db.py` `plan_absence_sweep` 纯函数 + `sweep_absent_jobs`）：占比安全闸 +
  env `LIVENESS_ABSENCE_APPLY` 默认 dry-run；`run.py` 抓全后调用。
- **测试**：`crawler/test_feishu_httpx.py`(8) + `crawler/test_absence_sweep.py`(10) 全绿；`test_run_concurrency.py`
  同步 feishu→httpx。回归 crawler 477 / node 520 全绿（本轮仅改 crawler Python，不涉 TS，build 不受影响）。
- **真机验证**（2026-06-28，自建香港库）：
  - httpx 抓取：智谱 237/237 全岗带正文 fetch_complete=True；xtool/zhipu/minimax 三租户 created/updated 正常。
  - **list-absence dry-run 实测**：xTool active=289、本次列表 279 → absent=10（3.5%，真实已关闭岗），远低于 50% 安全闸
    → 翻 `LIVENESS_ABSENCE_APPLY=true` 即会正确下架这 10 个、不误伤 279 活岗。智谱/MiniMax absent=0。**机制安全、可开启。**

### 下一步（按本 spec）
1. **开启 feishu 探活落库**：线上观察几日 daily-crawl 的 `[absence]` dry-run 日志占比稳定后，给 `daily-crawl.yml`
   env 加 `LIVENESS_ABSENCE_APPLY: "true"`（push 即生效）。
2. **从 enrich-crawl/dead-link-audit 摘除 feishu**（httpx 稳定数日后），让浏览器车道缩小（阶段 C 一部分）。
3. **阶段 B**：beisen spike（PortalId 已证在 HTML；需一次浏览器抓包定位 GetJobAdPageList 真实端点 → httpx 重放）。
4. **阶段 C**：浏览器车道收尾（moka 等）+ §4 诚实计数 + 大源页数封顶调参。
