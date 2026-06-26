# 交接：v3 实现下一个 session 从这里开始

> 写于 2026-06-25。基线分支 `draft/radar-pivot-0623`。权威 spec：本目录 `01`~`06`。总进度：`IMPLEMENTATION-PROGRESS-v3.md`。

## ✅ 已完成（2026-06-25 续做，commit ee93792 + 7efc272，全绿 + live 验证）
- **C 类 9 大厂逐岗撤岗探活（原"下一步主线"）已做完**：7 源 clean httpx detector（amazon/apple/meituan/
  microsoft/sf_express/tencent/vivo，关闭信号逐源 live 实测、13/13 集成实测通过）接进 `enrich.ENRICH_REGISTRY`
  + `lib/liveness-client.js` LIVENESS + `liveness-sweep.yml` matrix；bilibili 入 `audit_dead_links._BROWSER_ADAPTERS`
  浏览器审计兜底；phenom（SPA 壳 + AMD/百事低相关）诚实延后。信号详表见记忆 `job-radar-cclass-liveness-signals`。
- **3.3 JSON-LD**：抽取器 + 优先级合并器 `normalizer.resolve_official_times` 就绪+测好；**源能力 live 盘点**见
  `source-jsonld-capability.md`（服务端 JSON-LD 只在 Workday 外站 HTML + HSBC，国内 SPA 全 JS 渲染抓不到）。
  逐源 HTML 抓取接线暂缓（workday 富化抓 cxs JSON 非 HTML + 消费方 NEWLY_DISCOVERED 未上 → 热路径零收益不加抓取）。
- 回归：node 517 / crawler 459 / tsc 0 全绿。**未 push**（等用户指令；本 session worktree 分支 claude/radar-cclass-0625）。
- ⚠️ 上线后须 live 盯首轮 `liveness-sweep`（新增 7 adapter 分片）是否正常挤干 C 类大厂死岗（amazon/sf html 抓量大、
  Akamai/限流命中落 miss 不误判死 = 安全，但覆盖看 db-report 的 checked_24h 是否升）。

---
（以下为原始交接；C 类 / 3.3 已如上完成，其余延后项仍有效）

## 现在是什么状态（全绿、已 push）
- **Phase 1 护城河 / Phase 2 强度 / Phase 3 信号+时间核心 / Phase 4 分流+硬化 + 3.5 job_events** 全部完成并 push 到 `origin/draft/radar-pivot-0623`。
- 回归门：`node --test tests/*.test.js`=509、`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`=435、`npx tsc --noEmit`=0、4 个 workflow YAML 已校验。
- **已做的 live 验证**（环境网络是通的，git/gh/psql 都能用）：
  - `gh workflow run jobs-db-migrate --ref draft/radar-pivot-0623` → success；psql 实查香港库 `jobs.confirmed_closed_at` 列 + `job_events` 表（8 列+check）✅ 已生效。
  - `gh workflow run db-report --ref draft` → 新 SQL（2b 覆盖率段 + 第3段 checked_24h）真库执行通过。

## ⚠️ db-report 实测覆盖数据（这是下一步的依据）
active 126,702；**checked_24h 仅 39,291（31%）**、never_checked 86,775（68%）。分源：
- **httpx 在 liveness-sweep matrix 的源 ~100% 覆盖**：wt/hotjob/workday/greenhouse/eightfold。
- **SPA 源覆盖低**：beisen 13% / moka 11% / feishu 6%（靠 dead-link-audit 轮转 + 我新加的 dead-link-audit-new 新岗优先churn 上来）。
- **9 个 httpx 大厂 checked_24h=0**（下一步主线，见下）。

> 含义：今日主清单（STILL_OPEN 需 ≤24h 核验）当前偏向 httpx 源；科技消费大厂（多为 SPA/自建）大多落「等待再次确认」，直到保鲜覆盖churn上来。**这是 spec 要的诚实状态，不是 bug。**

## 下一步主线：把剩余大厂源纳入保鲜覆盖（接着本 session 做了一半的活）
本 session 已把 **B 类 4 个 SPA 大厂**（alibaba/netease/ctrip/huawei，~6200 岗）加进 `audit_dead_links._BROWSER_ADAPTERS`（commit 75ec9d7）。**剩 C 类 9 个 httpx 大厂无 detail 撤岗探活器 → 24h 覆盖恒 0**：

`amazon, apple, bilibili, meituan, microsoft, phenom, sf_express, tencent, vivo`

每个的做法（**必须 live 逐源摸信号，禁猜**，CLAUDE.md §1 红线）：
1. live 取该源一个**在招** jd_url + 一个**已关闭** jd_url（已关闭的可从 db 里 status=expired 的找，或源站翻已下架岗）。
2. 比对两者的 detail 端点（HTTP 状态码 / JSON state 字段）找**可靠关闭信号**——参照 `crawler/enrich.py` 现成的 `_detail_wt`（req_state=9501）/`_detail_hotjob`（state=1017）/`_detail_workday`（404）。jd_url 格式见 CLAUDE.md「当前 source 状态」表（meituan `zhaopin.meituan.com/web/position/detail?jobUnionId=` / vivo `hr.vivo.com/job-detail?_irjid=` / bilibili `jobs.bilibili.com/social/positions/{id}` / sf_express `hr.sf-express.com/JobSearchById/{id}` / apple `jobs.apple.com/.../details/` 等）。
3. 写 `_detail_xxx(jd_url) -> JobClosedError|正常` 注册进 `ENRICH_REGISTRY`，并把该 adapter 加进 `.github/workflows/liveness-sweep.yml` 的 matrix.adapter。
4. **同时**给 `lib/liveness-client.js` 加对应探活器（点击/展示核验也能判它，01 spec §4.3）+ 在 `LIVENESS` 注册 → `livenessSupported(adapter)` 为真。
5. 测试：`crawler/test_*.py` 加该探活器的纯解析单测（在招 vs 关闭返回可区分，mock 不打真网）；`tests/liveness-client.test.js` 加 golden。
6. 摸不到可靠 httpx 关闭信号的源（详情页是渲染型 SPA）→ 退而求其次加进 `audit_dead_links._BROWSER_ADAPTERS`（浏览器渲染兜底，同 B 类）。

> 提示：meituan/vivo/bilibili/tencent 详情页多有不挂签名的 JSON 接口（参考 `domestic-adapter-veins` 记忆「自建门户多有公开接口，先穷尽 httpx」）→ 优先 httpx 探活器，比浏览器快。

## 之后按计划做 3.3（JSON-LD 接线）
- `crawler/normalizer.extract_jobposting_ld(html)` 已写好+测好（`crawler/test_jobposting_ld.py`），**只差接线**：
  - 在 enrich 逐岗抓 detail HTML 的地方（`crawler/enrich.py` 的 detail fetcher）调它，按 **官方结构化(JSON-LD) > adapter 直填 > 正文正则** 取 `posted_at`/`deadline`（02 spec §3.2）。这段可 offline 接（无 JSON-LD 时返回 None 自然回退，纯增益）。
  - **源能力盘点**（哪些源详情页带 JSON-LD JobPosting）需 live 抽样 → 登记一张源能力表。
- 接通官方 `posted_at` 后，才可考虑解禁 `NEWLY_DISCOVERED` 信号（还需 3.6 防假动量 + first_seen 污染消退，见 02 §4.2）。

## 其余延后项（无消费方，别急）
- **3.6 防假动量守则** + **CONFIRMED_OPEN 写入**（每日 sweep 量大，等 momentum/NEWLY_DISCOVERED 真要上 C 端再开；planner `jobs_db.plan_confirm_event` 已就绪）。
- **write.ts upsert 路径 FIRST_SEEN/REAPPEARED**（crawler 已是主写入方，thin wiring；planner 口径见 `crawler/jobs_db.plan_upsert_events`）。
- **1.5 SPA 接口级探活**（飞书/Moka/北森 JSON 接口，live 摸）。

## Live 验证 runbook（环境网络通，自己做、别推给用户）
- 跑 workflow on 分支：`gh workflow run <wf> --ref draft/radar-pivot-0623` → `gh run watch <id> --exit-status`。
- 读香港库（只读 OK，DDL 写会被 classifier 拦→走 jobs-db-migrate）：
  `set -a; source /Users/bytedance/Desktop/求职雷达/.env.local; set +a; psql "$JOBS_DATABASE_URL" -c "..."`，**Bash 需 dangerouslyDisableSandbox=true**（否则 TLS 代理把响应抹 null），**绝不打印密钥值**。
- schema 改香港库：改 `jobs-db/schema.sql` → `gh workflow run jobs-db-migrate --ref <分支>`（幂等）。
- 覆盖率体检：`gh workflow run db-report --ref <分支>` → `gh run view <id> --log`。

## 不变量（破坏即回归失败）
expired sticky / summary preserve-if-empty / `enrich_checked_at` 不被列表重抓覆盖 / canonical 三处一致 / job_events 写失败不影响 upsert / 点击不被阻塞（核验非阻塞、默认放行）。

## 合并上线时
- 迁移 164（radar_intensity）**push main 自动应用**（migrate.yml）；香港库 schema 已手动 apply（上面）。
- push 后盯首轮 CI：`liveness-sweep`（新 cron 4/12/20）、`dead-link-audit-new`、`db-report`。
</content>
