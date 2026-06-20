# 职业洞察 — 供给升级设计（爬取面 / 可靠性 / 即时性）

> 状态：设计已确认（2026-06-20），按 Phase 1 → 2 → 3 实施。
> 目标：让职业洞察从「又少又水又旧」变成「目标用户真正要的、可靠、新鲜」的内容，**全程不碰红线**。

## 1. 背景与根因

洞察当前低价值的实测根因（见探查）：

1. **覆盖极低**：~95% 公司点开是「暂无洞察」。用户看到的大多是 T1（`lib/insight-derive.ts` 从自有岗位库现算的招聘时机/在招数量/薪资区间），白开水且需公司有 3–5 个在招岗位才触发。
2. **有料内容被免费额度卡死**：文化/真实薪资体感/晋升路径/上市股票这些维度靠 T3 流水线（`crawler/insight_engine.py` 接地→抽取→判官→共识），但检索源百度千帆免费仅 ~50 次/天（`QIANFAN_DAILY_CAP=40`），等于一天只能富化 1–2 家，几百家排队几个月。
3. **不即时、不保鲜**：无「用户点开就现查」机制（只能等每天 20:30/21:30 UTC 定时任务）；过期信息无自动下架巡检（设计写过但从未接上）。
4. 人工种子仅 14 家、~29 条，一次性。

## 2. 合规线（写死，不动）

- **官方源 = 事实**：上市/财报/工商等官方披露，`grade=fact`，带官方链接。
- **搜索源 = 去标识群体结论**：经搜索引擎 API（前门，非自爬）取公开讨论 → 只留群体性结论 + ≤60 字引用 + 回链原帖 + 判官核验；`experience` 须 ≥2 个不同 publisher 共识。
- **禁止**：直接爬脉脉/知乎/小红书等社区（判例在先：微博诉脉脉、大众点评诉百度、巧达科技刑案），禁存整段 UGC 原文，禁落库股价数字（只存 `payload.quote_url`），禁产品口吻断言（`lib/insight-verification.ts` 的 assertion lint 已守）。
- 搜索引擎 API 是拿到同样 UGC 公开内容的**合规前门**：不破反爬、不破登录墙、付费查授权索引、只取去标识聚合 + 回链。

**核验/去标识/判官闸门（`lib/insight-verification.ts` + `crawler/insight_engine.py`）本次不放松。** 升级的是「供给量与新鲜度」，不是「降低门槛」。

## 3. 架构总览（三步走，每步独立上线/独立测试）

```
Phase 1  可切换多源搜索层    解吞吐瓶颈：有料内容 每天1-2家 → 每天几百家
Phase 2  官方权威铁事实源    填可靠：上市/股票/公司背景维度，零合规风险
Phase 3  即时触发 + 过期保鲜  点开就优先现查 + 老信息自动下架
```

## 4. Phase 1 — 可切换的多源搜索层（最高优先，先用免费额度验证路由灵活性）

### 4.1 组件

新建 `crawler/search_providers/`（纯 `httpx`，不引新依赖）：

- `base.py` — `SearchProvider` 协议 + 统一结果形状
  `SearchResult = {title, url, snippet, text, publisher}`（**与现 `qianfan_search.search()` 输出字节级一致** → `run_pipeline` 的 sources 直接喂，下游零改动）。
  每个 provider 实现 `name`、`is_configured()`（有 key 且未熔断）、`search(query, top_k) -> list[SearchResult]`，缺 key/出错**静默返回 `[]`**。
- `qianfan.py` — 把现有 `crawler/qianfan_search.py` 重构成一个 provider（保留其 `qianfan_usage` 守卫与 50/天硬顶）。
- `bocha.py` — 博查 AI 搜索（中文 UGC 最深；`POST https://api.bochaai.com/v1/web-search`，Bearer key）。
- `tavily.py` — Tavily（返回已清洗正文，最贴合喂 AI；`POST https://api.tavily.com/search`，body 带 `api_key`）。
- `serper.py` — Serper（谷歌 SERP 兜底；`POST https://google.serper.dev/search`，`X-API-KEY`）。
- `router.py` — `SearchRouter`：
  - 注册所有 provider，按优先级取**已配置**的那些（没配 key 的自动跳过 → 这正是「免费额度先测灵活性」的关键）。
  - **每源每日预算硬顶**（走 `search_usage` 表 + `SearchBudget` 助手，镜像 qianfan 的 `budget_used/remaining/consume`）。
  - **多源并取 + 按 url 去重**（≥2 个独立来源天然喂饱「≥2 publisher」共识门）。
  - **熔断/兜底**：某源额度耗尽或报错 → 跳到下一源，绝不整体失败。
  - 每源独立 env 开关（如 `BOCHA_DISABLED`），沿用 `BAIDU_QIANFAN_SEARCH_DISABLED` 套路。

### 4.2 预算与配置

- 迁移 `156_search_usage_budget.sql`：`search_usage(provider text, day date, used int default 0, updated_at timestamptz, primary key(provider, day))`。`qianfan_usage`（137）保留，qianfan provider 继续用它；新源走 `search_usage`。
- env：`BOCHA_API_KEY`/`TAVILY_API_KEY`/`SERPER_API_KEY` + 每源 `*_DAILY_CAP` + `*_DISABLED`。全局「每日富化公司上限」继续在 `insight_backlog` 控。
- **成本护栏**：所有付费搜索一律过 `search_usage` 日顶 + 全局公司日顶 + 一键熔断；超额自动停。用户给「每月最多花多少」→ 换算成各源日顶焊死。

### 4.3 接入点

`crawler/insight_backlog.py` 中 T3 检索处：把直接 `qianfan_search.search()` 换成 `SearchRouter().search()`，输出形状不变 → `run_pipeline` 不动。

### 4.4 测试（守「单测不打真实网络」）

`crawler/test_search_providers.py`：
- 各 provider 的响应解析（mock httpx 返回 → SearchResult；覆盖正常/空结果/HTTP 错误/缺字段）。
- 路由器：预算耗尽跳源、报错兜底、多源去重、零 provider 配置时优雅返回 `[]`。
- live 冒烟仅在有 key 时手动跑（不进 CI 默认门）。

### 4.5 先用免费额度验证灵活性（用户明确要求）

Tavily(1000/月免费)、Serper(2500 免费额度)、博查(试用额度)、千帆(50/天) → 在不花钱/几乎不花钱下即可验证路由层能**按配置切换 / 多源并取 / 缺源兜底**。验证通过、用户给正式 key + 预算上限后再放量。

## 5. Phase 2 — 官方权威铁事实源（攻可靠性，用户已点头）

新建 `crawler/official_facts/`（或并入 `insight_backlog` 的 T2 drain），每个抓取器产出结构化事实 → `insight_items(origin='official', grade='fact')`，带官方链接，几乎必过核验门：

- `edgar.py` — SEC EDGAR（美股上市，官方免费 API）：股票代码/交易所/最新申报。
- `cninfo.py` — 巨潮资讯（A 股/科创/创业板，CSRC 指定披露）：上市状态/股票代码/公告。
- `hkex.py` — 港交所披露易（港股）：上市信息。
- 企业信用公示（成立年份/注册资本/法律状态）= **延后/先探活**：有验证码反爬，能稳定拿到才接，拿不到不硬碰、不猜。

要点：主要填 `listing` 维度 + 公司背景列（`founded_year`/`funding_stage`/`headcount_band` 已存在）；**行情数字不落库**，只存 `payload.quote_url`；设 TTL + `valid_until`。按公司所属市场路由到对应官方源。
测试：各源存样例响应 fixture 解析，不打真实网络。

## 6. Phase 3 — 即时触发 + 过期保鲜（攻即时性）

- **现查触发**（`app/api/insights/route.ts`）：命中的公司无新鲜库存洞察 / `insight_checked_at` 过期时 →
  ① **队列提前**（置 `insight_checked_at=NULL` 或优先标志，下次 drain 优先取）= 默认、便宜、即时重排；
  ② **限量快车道**：对用户主动点开的公司发 `workflow_dispatch` 单公司富化（复用 `/api/refresh` 的异步轨道 + `GITHUB_DISPATCH_TOKEN`），带节流幂等（N 小时内已富化的不重发、全局每小时 ≤N 家）控成本。
  推荐：①默认 + ②小流量快车道。
- **过期下架巡检**：新增 `.github/workflows/insight-staleness-sweep.yml`（每日）→ `valid_until` 过期的 retire、硬 TTL 太久没核实的降级/重排。纯函数 `should_retire/should_requeue` 单测覆盖。
- **TTL 调优**：`listing` 等易变维度复核更勤。

## 7. 贯穿全程

- **成本**：见 4.2 护栏。用户最后一并给 key + 月度上限。
- **合规**：见 §2，闸门不放松。
- **文档同步**（留痕规约）：每个落地 commit 同步更新 `CLAUDE.md`（模块 B 段、env、目录结构）、本 spec、相关记忆。
- **回归四件套**：`node --test tests/*.test.js` + `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` + `npm run build` + `git diff --check`。

## 8. 用户提供（外部，我碰不了）

- 搜索源 API key（博查/Tavily/Serper）→ GitHub Secrets + Vercel 环境变量（用户：最后一并给）。
- 每月花费上限数字 → 换算日顶。
- 当前：先用各家免费额度，验证路由层灵活性。

## 9. 不做（Out of scope）

- 直接爬社区；存整段 UGC / 落库股价数字；放松核验闸门。
- 正式放量（待用户给 key + 上限前，仅免费额度验证）。
- 新增重型依赖（一律 `httpx`）。

## 10. 实施顺序

Phase 1（解瓶颈 + 免费额度验路由）→ Phase 2（官方源补可靠）→ Phase 3（现查 + 保鲜）。每 Phase 独立可上线、独立测试、独立 commit。
