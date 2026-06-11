# JD 正文（summary）富化 — 设计 spec

- 日期：2026-06-11
- 状态：已脑暴定稿，待实现计划
- 目标：消除「岗位库大面积缺 JD 正文」这一产品短板。当前 active ≈ 10.1 万岗，最近行样本 ~60% 空 summary（快档故意只写列表 + 重档富化没跟上）。jd_url 可靠，summary 是缺口。

## 1. 问题与根因

- 快档 `daily-crawl.yml`（httpx 列表）`CRAWL_DETAIL_CAP=0` 故意**只写列表骨架、不抓正文**（为 <30min）。
- 重档 `enrich-crawl.yml`（浏览器 tier，1/7 源轮转，5.5h）re-crawl 列表 + 逐岗 detail，但**只能富化「当前仍挂在 live 列表」的岗位**；存量里「已不在列表但仍 active」的空 summary 行**永远碰不到**（实测 oracle 重爬 77→74 只清 3 行）。
- 结果：新写入的岗位长期薄，存量 backlog 不收敛。

根因 = **富化吞吐与覆盖跟不上**，不在抓取或入库（入库刚批量化提速 78x）。

## 2. 目标与非目标

**目标（Hybrid，业界标准：实时富化所见 + 后台 drain 长尾）**
1. 用户**当下看到**的卡片必有 summary（on-demand enrich-on-read）。
2. 后台并发 worker 按优先级 drain 10 万 backlog，summary 空占比持续下降（active 表目标 <10%，用户可见集 ~0%）。
3. 不新增常驻 worker / Redis / Celery（守 Phase-1 边界）；Postgres 当队列，GitHub Actions 当并行 worker。

**非目标**
- 不接 LLM 抽取（Phase-1 边界）。
- 不追求「10 万岗 100% 补齐」——没人看的冷岗低优先，长尾可残留（死信老化）。
- 不动 jd_url 质量门、不改前端大改。

## 3. 关键洞察（设计基石）

1. **大多数 adapter 的「详情」是纯 HTTP/JSON 接口，不需要浏览器**：workday(cxs detail)、oracle、eightfold、smartrecruiters、hotjob(`listPositionDetail`)、wt、greenhouse/lever/ashby/phenom。→ 这些可 httpx **高并发**富化（10-20），不被 Playwright 串行卡。
2. **存量必须按 `jd_url` 反推 detail 端点富化**，不能靠 re-crawl 列表（只触 live 列表）。已有两个验证过的 backfill 脚本证明该模式：`scripts/backfill_foreign_summaries.py`（httpx，workday/oracle/eightfold/smartrecruiters）+ `scripts/backfill_moka_summaries.py`（浏览器渲染）。本方案 = 把它们**统一 + 补齐缺的 adapter + 工程化为常态服务**。
3. **少数 adapter 详情需渲染**：beisen / moka / feishu（SPA，无干净公开 detail JSON 或需站点 session）。这些是源数量大头（beisen 211 + moka 196 + feishu 49 = 456 源），走 browser 低并发 shard，单独节奏。

## 4. 架构总览

四个组件，职责单一、接口清晰：

```
列表发现（写骨架，无 summary）          summary 富化（本方案新增/统一）
┌─────────────────────────────┐      ┌────────────────────────────────┐
│ daily-crawl.yml  httpx 列表   │      │ crawler/enrich.py 统一富化注册表 │
│ enrich-crawl.yml 浏览器 SPA   │ ───► │  enrich_by_jd_url(adapter,row)   │
│   列表（beisen/moka/feishu）  │      │   → summary | None               │
└─────────────────────────────┘      └───────────────┬────────────────┘
                                       后台 drain ◄────┤────► on-demand
                              ┌────────────────────┐  │  ┌──────────────────┐
                              │ enrich-backlog.yml │  │  │ /api/enrich (读时)│
                              │ Actions matrix 分片 │  │  │ 可见卡缺 summary  │
                              │ Postgres 队列+死信  │  │  │ → httpx 并发补→弹入│
                              └────────────────────┘  │  └──────────────────┘
                                          回写：批量 upsert（已落地）
```

## 5. 组件详设

### 5.1 `crawler/enrich.py` — 统一「按 jd_url 富化单岗」注册表

- 接口：`enrich_one(adapter_name, source, job_row) -> str | None`（返回 summary 文本或 None）。
- 内部 `ENRICH_REGISTRY: dict[adapter_name -> callable]`，两类：
  - **HTTPX 类**（无浏览器，可并发）：`workday / oracle / eightfold / smartrecruiters`（迁移现有 `backfill_foreign_summaries.py` 的 `_detail_*` 逻辑）、`hotjob`（postId→`/wecruit/positionInfo/listPositionDetail/`）、`wt`、`greenhouse / lever / ashby / phenom`（公开 JD JSON/HTML）。
  - **BROWSER 类**（需渲染、低并发）：`beisen / moka / feishu`（moka 复用 `backfill_moka_summaries.py`；feishu/beisen 用站点 session 重放 detail XHR 或渲染 detail 页）。
- 每个 callable 从 `job_row.jd_url`（+ `source.source_url`）反推 detail 请求，复用 `normalizer.clean_summary` 口径；正文可推导时顺带补 `job_type/experience/education/deadline`（对齐 run.py）。
- 既有两脚本重构为薄壳调用 `enrich.py`（不重复逻辑）。

### 5.2 队列 = Postgres（迁移 `133_job_enrich_tracking.sql`）

- jobs 加两列：`enrich_fail_count int default 0`、`enrich_checked_at timestamptz`。
- 待办集（队列）：`status='active' AND (summary IS NULL OR summary='') AND enrich_fail_count < 3`。
- **优先级排序**（对齐 CLAUDE.md：私企 500 强 > 国企 > 外企、本土 > 外企）：
  1. 源档位权重（本土私企 > 国企 > 外企）。注：`sources` 无 `origin` 列，用 `sources.segment`（seed 里私企=`'private'`）+ `lib/company-origin` 的 `classifyCompanyOrigin(company)` 口径映射；具体权重表在实现计划里定。
  2. `first_seen_at desc`（最新优先）。
  3. `enrich_checked_at nulls first`（没试过的先试）。
- **死信**：富化失败（detail 404/已撤岗/连续异常）→ `enrich_fail_count += 1`、`enrich_checked_at = now`；≥3 次不再入队，随生命周期老化。成功 → 写 summary。

### 5.3 后台 drain = 新 `.github/workflows/enrich-backlog.yml`

- 触发：cron 高频（如每 2-3h；公开仓库分钟无限）+ 手动。
- **matrix 分片**：
  - httpx-detail shard（×N，如 4-6）：每片 `LIMIT chunk`（如 5-10k）按优先级取队列、httpx 并发富化（全局 10-20、**按 host 限 2-3** + 指数退避 + jitter，守合规红线）、批量 upsert 回写。
  - browser-detail shard（×1-2）：低并发渲染 beisen/moka/feishu，单源限量。
- 复用 `db.upsert_jobs_batch` 回写（只更 summary + 派生字段）。
- step `timeout-minutes` 有界（如 50），远低于 6h。

### 5.4 on-demand enrich-on-read = 新 `app/api/enrich/route.ts`

- `POST { jd_urls: string[] }`（封顶 ~30）。
- 服务端（service role）：按 jd_url 查 jobs 行 → 仅取 **httpx-detail adapter** 的缺 summary 行 → 调 enrich（并发封顶 20）→ `upsert` summary → 返回 `{ jd_url: summary }`。
- **跨语言注意**：本路由是 TS（Vercel），enrich 逻辑主体在 Python `crawler/enrich.py`。on-demand 只覆盖**简单映射的 httpx 源**（workday/hotjob/oracle/eightfold/smartrecruiters/wt/greenhouse/lever 等，detail = jd_url 拼接 + 一次 JSON GET），故在 `lib/enrich-client.ts` **重实现这几条简单映射**（不含浏览器源），并与 Python 侧用**同一组 golden 用例**保证 jd_url→detail 端点解析一致。复杂/浏览器源不进 on-demand。
- **browser-detail 源不在 on-demand 范围**（一次请求里渲染太慢）→ 返回标记，前端展示「去官网看正文」，靠 5.3 drain 补。
- 幂等、短时（serverless 限内）；失败静默降级（卡片保持薄，不报错）。

### 5.5 前端（最小改）

- Today/Jobs 列表渲染后：收集**可见**卡里缺 summary 且属 httpx-detail 源的 jd_url → 调 `/api/enrich` → 正文**异步弹入**。
- 列表排序：**有正文的排前**（已有打分排序加一档 summary-present 权重）。
- 薄卡占位：「正文抓取中 · 点开看官网」。（用户主动「刷新/联网爬」已只放有 summary 的卡，本条针对后台库的浏览体验。）

## 6. 数据流

1. 列表抓取写骨架（summary 空）→ 入队（天然 = `summary is null`）。
2. drain worker 按优先级取队列 → enrich_one → 成功写 summary / 失败记死信。
3. 用户开列表 → 可见薄卡走 /api/enrich 即时补（httpx 源）。
4. summary 空占比随 drain + on-demand 下降。

## 7. 错误处理与合规

- **礼貌**：按 host 并发 2-3、批间延迟、指数退避 + jitter；沿用 `robots.py`。
- **死信**：连败 3 次 / 404 → 停试，老化。
- **永不炸整批**：单岗富化失败只记死信，不掀分片（沿用 run.py 约定）。
- **合规红线**：只打官方公开 detail 端点、不绕验证码、不登录；维持 jd_url 质量门不变。

## 8. 测试

- 纯函数（无网络，unittest）：每个 adapter 的 `jd_url → detail 端点` 反推正确（含 hotjob postId、workday externalPath、moka uuid）；`ENRICH_REGISTRY` 分发；队列优先级排序；死信阈值逻辑。
- `/api/enrich`：mock supabase + mock fetch，验只富化 httpx 源、封顶、幂等、失败降级。
- 回归四件套（node test / crawler unittest / build / git diff --check）。
- live 验证靠真机/cron（沙箱挡网络）。

## 9. 分期落地

- **P1（最快见效）**：`enrich.py` HTTPX 类（workday/hotjob/wt/外企 ≈ 260 源）+ 迁移 133 + `enrich-backlog.yml` httpx shard。先把 httpx-detail backlog drain 干净。
- **P2**：browser-detail 类（beisen/moka/feishu ≈ 456 源，backlog 大头）+ browser shard。
- **P3**：`/api/enrich` + 前端 on-demand 弹入 + summary-present 排序权重。
- **P4**：优先级/死信/并发调优；观测 summary 空占比指标。

## 10. 成功判据

- active 表 summary 空占比：60%（当前新写入样本）→ **<10%**（drain 收敛后）。
- 用户可见集 summary 覆盖 ~**100%**（on-demand 兜底）。
- 快档 daily 不回退（仍 <30min）；drain 单 step <50min、不撞 6h；无合规告警。

## 11. 风险

- browser-detail（beisen/moka/feishu）吞吐仍是瓶颈，456 源 backlog 大；P2 可能需多 shard + 多天 drain。可接受（长尾）。
- 个别源 detail 反推不稳 / 反爬 → 死信兜底，不阻塞。
- on-demand 给 Today/Jobs 加一次轻请求；封顶 + 异步，不阻塞渲染。
- **跨语言重复**：on-demand 的 httpx-detail 映射在 Python(crawler) 和 TS(lib) 各一份，有漂移风险 → 用同一组 golden 用例钉死、只覆盖简单映射来把重复面降到最小；若维护成本超预期，P3 可改为「on-demand 也走轻量后台触发」而非 TS 重实现。
