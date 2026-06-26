# 02 抓取重构方向 Spec（发现/保鲜分流 + 便宜优先 + 记真时间）

> 日期：2026-06-24
> 地基文档：`产品方向v2-岗位保鲜雷达.md`（v3）、`01-保鲜与运维硬化-spec.md`
> 性质：技术方向规格。不是推翻爬虫，是把它的重心从"多抓"转到"保鲜又快又准又便宜 + 把时间记真"。
> 实现基线：基于现有 `crawler/`（`run.py`/`jobs_db.py`/`discovery.py`/`normalizer.py`/adapters）扩展。

---

## 0. 三条主张

1. **发现（找有哪些岗）和保鲜（反复核对岗还在不在）是两件事，要分两条流跑。**
2. **保鲜先用最便宜的信号判，判不出来再上昂贵的无头渲染。**
3. **岗位的时间要记真**：尽量拿官网的"发布时间/截止时间"（含解析网页里的结构化招聘数据），记不到就老实标"我们新发现"，不冒充"刚发布"。

不做的：不再以"源数量"为目标、不大规模铺新 adapter（精不在多）。

---

## 1. 现状基线（实现前必读）

| 模块 | 文件 | 现状 |
|---|---|---|
| 抓取主流程 | `crawler/run.py`（`ADAPTERS` 55 个、`_partition_by_tier`、`_group_by_host`、`_process_one_source`、`run_crawl`） | httpx 快档线程并发（按 host 分队，同 host 串行）；浏览器档串行；每源 `type(adapter)()` 新实例防 host 串味 |
| 写库 | `crawler/jobs_db.py`（HK，`upsert_job`/`upsert_jobs_batch`，canonical 去重，`_PRESERVE_IF_EMPTY`，expired sticky）；`crawler/db.py`（Supabase 回退） | gated on `JOBS_DATABASE_URL` |
| 发现/刷新 | `crawler/discovery.py`（`SpaKeywordRecipe` 发现、`CompanyRefreshRecipe` 公司库刷新，逐源增量回写 `discovery_runs`） | 已部分独立 |
| 时间解析 | `crawler/normalizer.py`（`pick_publish_date`/`coerce_iso_date`/`extract_posted_at`/`extract_deadline`、`PUBLISH_TIME_FIELDS`） | posted_at：adapter 直填优先、否则正文正则；deadline：极少 adapter 直填、主要正文正则 |
| 定时 | `.github/workflows/daily-crawl.yml`（httpx 快档 + 内置 sweep 12k + 按需浏览器） | 发现和保鲜已在不同 step，但**保鲜仍搭在 daily 抓取里跑** |

关键现实：
- **当前无任何 JSON-LD / schema.org / sitemap 解析**（grep 无结果）——这是 §3 的主要抓手。
- 多数外企 ATS（microsoft/google/eightfold/oracle）`posted_at=None`，时间最缺。
- ~835 enabled 源、~98% 在产出。

---

## 2. 发现与保鲜分两条流

### 2.1 现状问题

`daily-crawl.yml` 把"抓列表（发现）"和"逐岗核对（保鲜）"放在同一次 daily 跑里，互相挤预算（httpx 50min + sweep 65min）。两者节奏需求不同：
- **发现**：跟公司发布节奏，按源重要性可日/可降频；
- **保鲜**：跟"展示岗的核验时限"（24h/72h，见 01 spec §2），是独立的、必须稳的节拍。

### 2.2 目标拆分

| 流 | 跑什么 | 节拍 | 复用 |
|---|---|---|---|
| **发现流** | 抓各源列表，发现新岗、更新岗位字段 | 头部源 daily，长尾降频/按需（接"更新关注公司"） | `run.py` httpx 快档 + 浏览器档 |
| **保鲜流** | 按 `enrich_checked_at` 最旧轮转 + 新岗优先核验岗位死活，撤岗→expired | 独立高频（保住 24h/72h SLA），与发现解耦 | `enrich_backlog.py --sweep` + `audit_dead_links.py` |

实现：
- 把保鲜从 `daily-crawl.yml` 内联 step 中**独立出来**，由 `liveness-sweep.yml`（httpx 源）+ `dead-link-audit.yml`（SPA 源，含 01 spec §3.1 的新岗高频小批分支）单独承担、按 SLA 调频。
- `daily-crawl.yml` 只管发现（抓列表），不再背 12k sweep（sweep 交给独立流）。
- 二者通过 `jobs` 表解耦，不新增队列系统/Redis。

---

## 3. 便宜优先的核验 + 结构化数据

### 3.1 核验"先便宜后昂贵"

判一个岗死活，按成本从低到高，**能在前一级判定就不进下一级**：

1. **HTTP 层信号（最便宜）**：detail/apply URL 的状态码、重定向（404/410/跳回列表 = 强死信号）。
2. **JSON/XHR 接口**：很多 SPA（飞书/Moka/北森/自建大厂）列表与详情其实有 XHR JSON 接口，含状态字段（已存在的 wt `req_state` / hotjob `state` 即此类）——逐源排查这些接口，能判死活就不渲染整页。
3. **无头渲染（最贵）**：只留给前两级都判不出来的 SPA 软 404。

落地：在 `lib/liveness-client.js`（应用侧）和 `crawler/enrich.py`（爬虫侧）的探活注册表里，为更多 SPA 源补"接口级"探活函数，把它们从"只能渲染"降到"接口可判"。`audit_dead_links.py` 的渲染只作兜底。

### 3.2 解析结构化招聘数据（拿官方时间的主抓手）

很多官网在详情页 HTML 里埋了标准结构化数据，直接含发布日期和截止日期：

- `<script type="application/ld+json">` 里的 **schema.org `JobPosting`**：`datePosted`（官方发布时间）、`validThrough`（截止时间）、`hiringOrganization`、`jobLocation`、`employmentType`。
- 部分站点：`<meta>` / OpenGraph（`og:updated_time` 等）、或 `<script>window.__DATA__={...}</script>` 内嵌 JSON。

要求：
1. 在 `normalizer.py` 新增 `extract_jobposting_ld(html)`：解析 `application/ld+json` 中的 `JobPosting`，抽 `datePosted` → `official_posted_at`、`validThrough` → `deadline`。
2. 抓取链路里，**官方结构化数据 > adapter 直填 > 正文正则** 的优先级取 `posted_at` / `deadline`。
3. 逐源排查（一次性盘点）哪些源的详情页带 JSON-LD JobPosting，登记到一张"源能力表"（哪些源能拿官方发布/截止时间），供 §4 与产品 spec 的信号判定使用。

---

## 4. 把时间记真（与 01 spec、技术 spec 对齐）

### 4.1 字段语义（老实区分"官方时间"和"我们的时间"）

`jobs` 表时间字段重新厘清语义（不一定都新增列，先把语义和写入口径定死）：

| 字段 | 含义 | 来源 | 可信度 |
|---|---|---|---|
| `posted_at` | **官方发布时间** | 结构化数据/接口/adapter；拿不到则为 NULL | 高（仅当非 NULL） |
| `first_seen_at` | **我们首次抓到** | 入库时写 | 低（≠ 官方发布；受新接源/重灌影响） |
| `last_seen_at` | 最近一次在列表里见到 | 列表重抓刷新 | 中 |
| `enrich_checked_at` | 最近一次**逐岗核验**（确认还在/已死） | 富化/巡检/实时核验写 | 高（保鲜核心） |
| `deadline` | 官方截止时间（文本，需可解析） | 结构化数据/接口/正则 | 取决于来源 |
| `confirmed_closed_at`（新增） | 我们**确认下架**的时刻 | 判死时写 | 高 |

### 4.2 关键判断：什么时候敢说"新发布"

- **只有 `posted_at` 非空（来自官方/结构化数据）**，且在近窗口内，才可作"官网近期发布"判断。
- **只有 `first_seen_at`、没有 `posted_at`** → 最多说"我们新发现"，**且当前因 6/15 重建污染暂不可用**（全库 `first_seen_at` 都集中在 6/15 之后）。等满足下列条件再启用"我们新发现"：
  1. 距上次全库重建已过足够时间（`first_seen_at` 分布回归正常）；
  2. 能区分"真首次发现"与"新接源/重灌批量灌入"（见 §4.3）。

### 4.3 防"假新/假动量"（数据已实锤的坑）

`first_seen_at = 我们抓到时间`，所以**新接入一个源/一次重灌**会把一堆老岗标成"刚发现" → 假新机会、假招聘动量。守则：

1. 招聘动量只统计**全窗口（如近 28 天）持续有覆盖**的源/公司，新接入源在其"接入稳定期"内不参与动量计算；
2. 单次大批量灌入（同一 `source_id` 在极短时间 `first_seen_at` 激增）打标，排除出"新发现/动量"信号；
3. 这些守则写成纯函数 + 测试，供产品 spec 的 `COMPANY_MOMENTUM` / "我们新发现" 复用。

---

## 5. 岗位生命周期事件（append-only，便宜地记真历史）

> 库已换香港、几十 G，空间不是约束（详见方向 v3 §6.2）。但仍**不堆冗余**：只记里程碑，不记每次心跳。

### 5.1 事件表（jobs-db，不在 Supabase）

在 `jobs-db/schema.sql` 增 `job_events`（append-only）：

```sql
create table if not exists job_events (
  id            uuid primary key default gen_random_uuid(),
  event_key     text not null unique,          -- 幂等键
  job_id        uuid not null references jobs(id) on delete cascade,
  source_id     uuid,
  event_type    text not null check (event_type in (
                  'FIRST_SEEN',                 -- 我们首次抓到
                  'OFFICIAL_POSTED',            -- 拿到官方发布时间时记一次
                  'CONFIRMED_OPEN',             -- 逐岗核验确认仍在招（按天去重）
                  'CLOSED',                     -- 确认下架
                  'REAPPEARED'                  -- removed->active（不含 expired 复活）
                )),
  occurred_at   timestamptz not null default now(),
  observed_at   timestamptz not null default now(),
  payload       jsonb not null default '{}'::jsonb
);
create index if not exists idx_job_events_job_time on job_events (job_id, occurred_at desc);
create index if not exists idx_job_events_type_time on job_events (event_type, occurred_at desc);
```

`event_key` 规则（保证便宜、不堆量）：
```text
FIRST_SEEN:{job_id}                          # 一辈子一条
OFFICIAL_POSTED:{job_id}                      # 一辈子一条
CONFIRMED_OPEN:{job_id}:{yyyy-mm-dd}          # 按天去重，不是每次核验都写
CLOSED:{job_id}:{yyyy-mm-dd}                  # 一次下架一条
REAPPEARED:{job_id}:{yyyy-mm-dd}
```

### 5.2 "还在不在"不堆历史

- `CONFIRMED_OPEN` **按天去重**（一天最多一条），不是每次 sweep 命中都插。
- 日常"它还活着"的状态，靠 `jobs.enrich_checked_at` **单字段覆盖更新**承载，不进事件表。
- 估算：每岗一辈子 ~2–4 条事件（首见、可能拿到官方发布、若干天确认、下架），14 万岗 ~几十 MB（见方向 v3 §6.2）。

### 5.3 写入

- 爬虫端 `crawler/jobs_db.py`：upsert 时比对旧值，best-effort 插 `job_events`（**事件写失败只 warning，不影响 jobs upsert**）。
- 应用侧 `lib/jobs-store/write.ts`（discovery/search 写入路径）同口径，抽一个 helper，不复制两套判断逻辑。
- `expired` 不被列表复活的不变量保持：`expired→active` 不产生 `REAPPEARED`。

---

## 6. 验收口径

1. **结构化数据**：先做一次"源能力盘点"（哪些源详情页带 JSON-LD JobPosting），数量以盘点结果为准、不预设；对**盘点出的、确有 JSON-LD 的源全部**，`extract_jobposting_ld` 能抽出 `datePosted`/`validThrough` 并写入 `posted_at`/`deadline`（每个给 1 条 live 样例）。
2. **便宜优先核验**：至少把 1–2 个原本只能渲染判死的 SPA 源，改成"接口级"可判（给 live 样例：在招 vs 已关闭返回可区分字段）。
3. **发现/保鲜分流**：`daily-crawl.yml` 不再背 sweep；保鲜由独立 workflow 按 SLA 调频跑（给 workflow diff）。
4. **时间记真**：构造一个能拿到官方 `posted_at` 的岗 vs 只有 `first_seen_at` 的岗，证明前者可判"官网近期发布"、后者不可。
5. **事件表**：新岗产生 `FIRST_SEEN`；同一天重复核验只产生一条 `CONFIRMED_OPEN`；下架产生 `CLOSED`；`expired` 列表重抓不产生 `REAPPEARED`；事件写失败不影响 upsert。

必跑：
```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npm run build
git diff --check
bash scripts/check-migrations.sh   # 若动 Supabase 迁移
```

新增/更新测试（至少）：
```text
crawler/test_jobposting_ld.py        # JSON-LD 抽取
crawler/test_jobs_db_events.py       # 事件触发 + 按天去重 + expired 不复活 + 写失败不影响 upsert
crawler/test_momentum_guard.py       # 假新/假动量守则（新接源/重灌不算新）
```

---

## 7. 明确不做

- 不大规模铺新 adapter / 扩源（精不在多）；
- 不引入向量库 / Redis / Kafka / 队列系统；
- 不把 JD 全量历史快照存表（只存里程碑事件）；
- 不在本轮重写无头渲染框架（先做接口级探活 + 结构化数据 + 新岗优先）；
- 不破坏 canonical 去重三处一致（`lib/canonical-url.js` / `crawler/normalizer.py` / `jobs-db/schema.sql` 的 SQL 函数）。
