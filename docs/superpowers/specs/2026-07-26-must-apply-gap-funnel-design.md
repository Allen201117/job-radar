# 必投清单缺口漏斗（Must-Apply Gap Funnel）设计

日期：2026-07-26
状态：已与创始人拍板，待实现
北极星：`必投清单健康覆盖`（每行业 30 家里有多少家在库里有 ≥1 条 `active + summary≥60` 的岗）

---

## 1. 问题与实测基线

### 1.1 今天（2026-07-26）live 实测

数据源：香港 jobs 库 `group by company` 全量 + Supabase `sources` 全量（psql 直连，不受 PostgREST 1000 行截断）。
健康口径与 `lib/jobs-store/read.ts:getMustApplyCoverage` 字节级一致：`status='active' and char_length(btrim(summary)) >= 60`。

| 行业 | 健康覆盖 | 行业 | 健康覆盖 |
|---|---|---|---|
| 互联网/科技 | 29/30 | 地产/建筑 | 15/30 |
| 汽车/出行 | 22/30 | 能源/化工 | 12/30 |
| 消费/零售 | 20/30 | 金融 | 11/30 |
| 制造/工业 | 20/30 | 教育 | 11/30 |
| 医疗/医药 | 20/30 | 物流/供应链 | 9/30 |
| | | 传媒/文娱 | 9/30 |

合计 **178/330 槽位**，**151 家唯一公司零健康岗**。六个行业不到一半：金融 11、教育 11、能源/化工 12、地产/建筑 15、物流/供应链 9、传媒/文娱 9。

### 1.2 病根（已 live 证实，不是猜测）

1. **缺口 ≈ 100% 是「库里根本没有源」**，不是 adapter 坏了。金融 19 家缺口里 18 家在 `sources` 表连一行都没有；151 家缺口里只有 1 家（礼来）是「有源但被 disable」。
2. **每日自动扩源结构性够不着**：`crawler/auto_discover.py` 的 `PLATFORMS = {"feishu","hotjob"}` + browser 道 beisen/moka，一共只在 **4 个平台**上按预写 slug 探活。银行、央企、外企在华、自建门户公司不在这 4 个平台上 → `targets_must_apply.json` 里 120 家缺口天天被猜、天天 0；另有 **31 家缺口连候选清单都没进**（中国石油、中国石化、中海油、国家电网、南方电网、国家能源、华能、三峡、中国中铁、中国中冶、中国能建、中国邮政、中远海运、宝洁、联合利华、雀巢、欧莱雅、沃尔玛、施耐德、宝马、奔驰、大陆集团、礼来、巴斯夫、壳牌、DHL、联邦快递、普洛斯、京东物流、优酷、微众银行）。
3. **三块造好却没用上的资产**：
   - `company_spa`（`crawler/adapters/china_ats.py`）——通用自建 SPA 官网 adapter，浏览器拦截站点自己的岗位接口、只放行带真实 per-job URL 的岗，**加源零代码**。当前 enabled sources 里 **0 个**在用。
   - `crawler/search_router.py`（千帆/博查/Tavily/Serper）——只服务「职业洞察 T3」，**完全没接扩源**。
   - **国聘（iguopin）adapter 已写好并 live 验过**（commit `1c89996` + `56a67ed`，7/12 家央企达标：中国建筑 193 岗、中国电建 81 岗、中国铁建 10 岗、国家电网、中石油、工行、平安），**但躺在没合并的分支 `draft/codex-iguopin-0717`**。后果：Supabase 里那 4 个 iguopin 源自 2026-07-17 起再没被抓过（`jobs.last_seen_at` 最大值 = 2026-07-17），中国电建/中国铁建当前的健康岗是 7-17 的存货，即将被探活扫成 expired → **地产/建筑 15/30 会自己往下掉**。

### 1.3 计量瑕疵（已复核，规模有限但必须修）

- **`%万达%` 双槽假绿**：`地产/建筑·万达集团` 与 `传媒/文娱·万达电影` 用同一个 pattern `%万达%`，而库里唯一匹配的公司是 `万达控股集团`（源 `https://wanda.hotjob.cn/wt/wanda/web/index`，岗位是「工程经理」等，疑似山东万达控股，与大连万达/万达电影无关），624 条健康岗**同时把两个槽位撑绿**。
- **弱覆盖**：`金融·中国平安` 的健康岗全部来自「中国平安财产保险股份有限公司莆田中心支公司」，仅 4 条。
- 其余 pattern 包含型碰撞（`%京东%`⊂京东方/京东物流/京东科技、`%网易%`⊂网易云音乐、`%腾讯%`⊂腾讯音乐、`%阿里%`⊂阿里影业）经实测**当前没有造成「完全靠碰撞撑绿」的槽位**（全量扫描结果 0 个），12 个可疑槽位里 10 个是合理别名（`Bosch 博世`、`PepsiCo 百事`、`江苏恒瑞医药`、`好未来（学而思）`、`中国中化 ChemChina` 等）。**结论：baseline 178/330 基本可信，但万达那 2 个槽位是真假绿，必须修正（修完覆盖会诚实地 -2）。**
- **`auto_discover.existing_source_keys()` 把 disabled 源也算「已覆盖」**（`crawler/auto_discover.py:111`）→ 一家公司只要曾经插过一个坏源，就永远不会被重新发现。当前只影响礼来 1 家，但会持续毒化本设计的漏斗（漏斗自己会插失败源），必须一起修。

### 1.4 创始人已拍板的三条前提

1. **国聘算可接受的源**：央企走 `iguopin.com` 的逐岗详情链接。前端应标注「来源：国聘（国资委官方平台）」。（其余第三方招聘平台——智联/BOSS/前程无忧/猎聘——红线不变，仍然禁止。）
2. **必投清单可以改，但按硬规则**：只因「用户不再值得投 / 根本不公开招聘」换人，**绝不因「我们抓不到」换人**；本轮只产出证据清单，换谁由创始人终审。
3. **本轮目标 = 先救 6 个塌陷行业**，不追全行业 24/30。

---

## 2. 目标与验收

### 2.1 覆盖目标（两周）

| 行业 | 现在 | 目标 |
|---|---|---|
| 金融 | 11/30 | ≥17 |
| 教育 | 11/30 | ≥17 |
| 能源/化工 | 12/30 | ≥18 |
| 地产/建筑 | 15/30 | ≥21 |
| 物流/供应链 | 9/30 | ≥15 |
| 传媒/文娱 | 9/30 | ≥15 |

即六个行业各 **+6 家健康公司**（合计 +36）。

### 2.2 验收口径（硬性，禁止用替代指标冒充）

一家公司算「补上了」，必须同时满足：

1. 该公司在**香港 jobs 库**里有 ≥1 条 `status='active' and char_length(btrim(summary)) >= 60` 的岗；
2. 该岗的 `jd_url` 抽查 HTTP 200 且页面含岗位标题（防张冠李戴）；
3. 岗位归属正确——`jobs.company` 与清单 pattern 匹配，且详情页确实是这家公司（不是同名不同司）。

**明确禁止**用「新增了几个 source」「探活通过几家」当成果。CI 每轮结束必须回读香港库产出「本轮真实新增健康公司数」。

### 2.3 反向验收（不许出现的）

- 第三方招聘平台（智联/BOSS/51job/猎聘）入库数 = 0。
- 入库的岗没有一条是「招聘首页/搜索页/公告 PDF」当 `jd_url`。
- 不因为凑数把清单换成好抓的公司（清单本轮不自动改）。

---

## 3. 架构

### 3.1 总览

```
                    ┌─ P0 国聘回收（1 天，独立，先落地）
                    │
必投清单 (11×30)  ──┼─ P1 缺口漏斗 httpx 道（2-5 天）──┐
+ 香港 jobs 库      │                                  ├─→ sources → daily-crawl → jobs → 健康覆盖
+ Supabase sources ─┼─ P2 漏斗 browser 道 + 计量修正 ──┘
                    │
                    └─ P3 清单治理证据（只出证据，不改清单）
```

漏斗单向状态机，每家公司**一轮只走一遍**，失败带原因与复查日期落台账，避免「每天空烧 CI」。

### 3.2 状态机

```
unknown ──①入口发现──→ entry_found ──②平台指纹──→ platform_known ──③④探活+真抓+回读──→ healthy
   │                        │                          │                                    ↑
   │                        │                          │                                    │
   ├→ no_official_entry     ├→ wrong_platform          ├→ no_active_jobs                   │
   │  (30 天后复查)          │  (30 天后复查)            │  (14 天后复查)                    │
   │                        │                          ├→ no_stable_jd  ─→ manual_review    │
   │                        │                          ├→ anti_bot      ─→ manual_review    │
   │                        │                          ├→ login_wall    ─→ manual_review    │
   │                        │                          └→ thin_only ──(enrich 补正文)───────┘
   │                                                      (14 天后复查)
   └→ governance_candidate（连续两轮无公开入口 → 进 P3 证据清单，停止自动重试）
```

`manual_review` = `next_retry_at IS NULL`，**永远不再自动跑**，只在 P3 报告里列出。

### 3.3 新增台账表（Supabase，迁移 `185_must_apply_gap_attempts.sql`）

> 迁移前缀：当前最大是 184，本表用 **185**。加前先 `ls supabase/migrations` 复核未被占用。

```sql
create table must_apply_gap_attempts (
  id uuid primary key default gen_random_uuid(),
  scope text not null default 'domestic' check (scope in ('domestic','overseas')),
  company text not null,                 -- 必投清单里的 name（唯一键的一半）
  pattern text not null,
  industries text[] not null default '{}',
  state text not null default 'unknown' check (state in (
    'unknown','entry_found','platform_known','source_added','healthy','thin_only',
    'no_official_entry','wrong_platform','no_active_jobs','no_stable_jd',
    'anti_bot','login_wall','manual_review','governance_candidate')),
  official_entry_url text,
  detected_platform text,
  source_id uuid,
  fail_reason text,
  evidence jsonb not null default '{}'::jsonb,   -- {search_provider, candidate_urls, fingerprint_hits, probed_jobs, healthy_jobs, sample_jd_url, http_status}
  attempts integer not null default 0,
  rounds_no_entry integer not null default 0,    -- 连续「无公开入口」轮数，≥2 → governance_candidate
  last_attempt_at timestamptz,
  next_retry_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (scope, company)
);
create index idx_gap_attempts_queue on must_apply_gap_attempts (state, next_retry_at nulls last);
```

RLS：`service_role` 全权；admin（`profiles.role='admin'`）只读。参照 `supabase/migrations/002_rls.sql` 与 `159_admin_ops_dashboard.sql` 的写法。

### 3.4 新增/改动模块

| 文件 | 职责 | 复用 |
|---|---|---|
| `crawler/gap_census.py` | 从必投清单 + 香港 jobs + sources 算出每个槽位状态，upsert 进台账表；产出当轮工作队列 | `must_apply.py`、`jobs_db.py`、`db.fetch_all_rows` |
| `crawler/entry_finder.py` | 级联搜索找官方招聘入口；第三方平台黑名单过滤 | `search_router.py`（**改造成级联，见 §4.2**）、`lib/discovery/filtering.js` 的判定逻辑（Python 重写，规则对齐） |
| `crawler/platform_fingerprint.py` | 取入口页 → 识别 ATS 平台族 → 给出候选 `(adapter_name, source_url)` | `httpx`、现有 adapter 的 URL 形态 |
| `crawler/gap_funnel.py` | 编排：取队列 → 入口 → 指纹 → 探活 → 真抓 → 回读验收 → 写台账；CLI + 配额 + dry-run | `discover_domestic.sweep`、`probe.probe_one`、`run._process_one_source`、`ops_runs.py` |
| `crawler/adapters/iguopin.py` | 国聘 adapter（**从 `draft/codex-iguopin-0717` 分支合并，不要重写**） | 已存在 |
| `.github/workflows/gap-funnel.yml` | 每日 cron（httpx 道）+ 手动 dispatch；P2 加 browser job | 参照 `auto-discover.yml` |
| `lib/must-apply-list.json` | 修 `%万达%` 碰撞；加可选 `parentPattern` / `brandTokens` 字段 | — |
| `lib/jobs-store/read.ts` | `getMustApplyCoverage` 支持子品牌归属（§5.2） | 现有聚合缓存 |
| `app/admin/health/page.tsx` | 缺口漏斗台账卡 + 「真实扩源 / 口径变动」拆账 | 现有 `MustApplySection` |

---

## 4. 详细设计

### 4.1 P0：国聘回收（第 1 天，独立可上线）

1. **合并分支**：`git merge draft/codex-iguopin-0717`（2 commits：`1c89996`、`56a67ed`）。预期冲突点：`crawler/run.py`（ADAPTERS 表 + `_HTTPX_ADAPTERS` 列表）、`crawler/probe.py`、`lib/source-adapters.ts`。合并后：
   - `crawler/run.py` 的 ADAPTERS 必须含 `"iguopin": IguopinAdapter()`；
   - `lib/source-adapters.ts` 白名单含 `iguopin`；
   - `enrich-backlog.yml` / `daily-crawl.yml` 的 adapter 分片名单如按 adapter 枚举，需同步（接线四处，见 memory `job-radar-must-apply-breakthrough`）。
2. **验证现有 4 个源复活**：`中国平安 / 中国建筑 / 中国电建 / 中国铁建`，本地跑一次抓取，确认写进香港库且 `last_seen_at` 是今天。
3. **批量补央企源**（每家必须 live 验证后才入库）：
   候选（来自 §1.2 的 31 家「连清单都没进」+ 已在清单但零健康的央企）：
   中国石油、中国石化、中海油、国家电网、南方电网、国家能源集团、华能集团、三峡集团、中国中铁、中国中冶、中国能建、中国邮政、中远海运、招商蛇口、华润置地、中海地产、上海建工、东航物流。
   - `source_url` 约定：`https://www.iguopin.com/job?company={公司全称}&match={精准匹配词}`（`match` 是 adapter 的精准过滤参数，见 commit `56a67ed`，用于根治国聘模糊搜索夹带无关岗）。
   - **入库门**：跑一次真抓 → 香港库回读该 source 的健康岗 ≥1 → 抽查 1 条 `jd_url` 200 + 标题核验 + 公司归属正确 → 才写 `sources`。0 命中的（commit 记录里招行/中行/中石化/中铁/中信证券曾 0 命中）不入库，写台账 `no_active_jobs` + 14 天后复查。
   - `sources.company` 用**清单里的 name**，别用国聘上的全称变体，避免 pattern 对不上（这是历史高频病）。
4. **修 `%万达%` 假绿**（诚实修正，覆盖会 -2）：
   - 先核实 `wanda.hotjob.cn` 租户的真实主体（打开一条 `jd_url` 看落款/公司名）。若是山东万达控股 → 把该 source 与其 jobs 的 `company` 统一改成 `万达控股集团`（山东，化工），并从必投清单口径里排除；
   - `lib/must-apply-list.json`：`地产/建筑·万达集团` → `%万达集团%`，`传媒/文娱·万达电影` → `%万达电影%`；
   - 两个槽位随后诚实地变成缺口，进漏斗队列；
   - commit message 必须写明「口径修正，北极星 -2，原因=同名不同司假绿」。
5. **修 `existing_source_keys` 把 disabled 当已覆盖**（`crawler/auto_discover.py:111`）：去重集只算 `enabled=true` 的公司名；`source_url` 去重仍算全量（防重复插同一 URL）。加单测。

**P0 验收**：iguopin 4 老源恢复抓取 + 新增央企源全部经真抓回读达标 + 覆盖数字（修正万达后）写进 commit message。

### 4.2 P1：漏斗主干（httpx 道）

#### ① 入口发现 `entry_finder.py`

- **级联，不是扇出**。现有 `search_router.search()` 会把所有配了 key 的 provider 都调一遍（一家公司烧 4 次额度）。漏斗自己实现级联：
  1. 千帆搜 1 次（`qianfan`，日顶 50，与洞察共用 `search_usage` 台账）；
  2. 没拿到可信官方入口 → 在 `serper` / `tavily` 里挑当日剩余额度最多的**一个**再搜 1 次；
  3. 仍失败 → `no_official_entry`，`next_retry_at = now + 30d`，`rounds_no_entry += 1`。
- 每家公司**每轮最多 2 次搜索**。整轮总搜索次数硬上限走 env（默认 40/天），超了直接停，写 ops_runs。
- query 模板：`"{公司} 招聘 官网"`、`"{公司} 社会招聘 职位"`（第二条只在第一条无果时用，且算作第 2 次）。
- **候选 URL 过滤**（规则与 `lib/discovery/filtering.js` 对齐，Python 重写并加单测）：
  - 黑名单直接丢：`zhaopin.com`、`liepin.com`、`51job.com`、`zhipin.com`、`lagou.com`、`job592`、百科/新闻/知乎/CSDN 等内容站；
  - 白名单加分：URL host 含公司域名主干、路径含 `job|career|recruit|zhaopin|hr|campus`；
  - 已知 ATS host（`mokahr.com`、`zhiye.com`、`italent.cn`、`hotjob.cn`、`dayee.com`、`myworkdayjobs.com`、`successfactors`、`eightfold.ai`、`oraclecloud.com`、`avature.net`、`taleo.net`、`greenhouse.io`、`lever.co`、`ashbyhq.com`、`smartrecruiters.com`、`feishu.cn`、`iguopin.com`）直接判为高可信；
  - 取 top-1 高可信候选写 `official_entry_url`，其余存 `evidence.candidate_urls`。

#### ② 平台指纹 `platform_fingerprint.py`

- httpx GET 入口页（`follow_redirects=True`，UA 用常见浏览器 UA，超时 15s，失败重试 1 次）。
- 依次匹配：**最终 URL host** → **HTML 里出现的第三方 host** → **已知接口路径特征**。
- 输出 `(adapter_name, source_url)` 或 `unknown_spa`。
- 特殊码处理：`403/412/503 + WAF 特征` → `anti_bot`（转 manual_review）；出现登录表单且列表页需登录 → `login_wall`；页面只有公告/PDF 链接、无逐岗详情 → `no_stable_jd`。
- **禁止**：绕验证码、伪造登录态、破解签名。

#### ③④ 探活 + 真抓 + 回读验收（`gap_funnel.py` 的核心，最容易被做假的一步）

顺序**必须**是：

1. 用识别出的 `(adapter_name, source_url)` 跑一次**只读探活**（复用 `discover_domestic.sweep` / `probe.probe_one`），拿到 `count>0` 且标题核验通过才继续；
2. 插入 `sources` 行，**先 `enabled=false`**，`notes` 标 `gap_funnel:pending`；
3. 用 `run._process_one_source`（或等价单源抓取入口）对这个 source **真跑一次抓取**，正常写香港库；
4. **回读香港库**：`select count(*) filter (where char_length(btrim(summary))>=60) from jobs where source_id = ? and status='active'`；
5. 分流：
   - **≥1 健康岗** → `sources.enabled=true`，state=`healthy`；抽查 1 条 `jd_url`（200 + 页面含标题）写进 `evidence.sample_jd_url`；
   - **有真实岗但全是薄卡**（岗 >0、健康 =0、jd_url 抽查通过） → `sources.enabled=true`（岗是真的，交给 `enrich-backlog` 补正文），state=`thin_only`，14 天后复查是否转 healthy；
   - **0 岗 / jd_url 打不开 / 标题核验失败（张冠李戴）** → **删除刚插的 source 行**，并 `delete from jobs where source_id = ?`（本次抓进来的脏数据不留），state 记对应失败原因。
- 公司命名：`sources.company` 一律用清单 `name`。入库后立即校验 `company ILIKE pattern`，不匹配就地改名（jobs + sources 双改），否则等于白干。

#### 队列与配额

- 每轮从台账取：`state IN ('unknown')` 或 `next_retry_at <= now()`，按「本轮目标行业优先 → 用户 target_companies 命中优先 → 缺口行业覆盖率低者优先」排序。
- 默认配额（env 可调）：`GAP_FUNNEL_COMPANY_CAP=20`（每日处理公司数）、`GAP_FUNNEL_SEARCH_CAP=40`、`GAP_FUNNEL_INSERT_CAP=15`。
- `GAP_FUNNEL_APPLY` 默认 **dry-run**（只算不写 sources / 不写 jobs），线上先看一轮台账干净了再打开。
- 每轮写 `ops_runs`（运营看板②每日战报能看到）。

### 4.3 P2：browser 道 + 计量修正

#### company_spa 浏览器道

- 指纹结果为 `unknown_spa` 的公司进 browser 队列，独立 job（参照 `auto_discover_browser.yml`），**每日 5 家**上限（浏览器源单个 2-5 min，daily CI 预算有限）。
- 用 `CompanySpaAdapter` 对入口页跑一次拦截；能拿到带真实 per-job URL 的岗才继续走 §4.2 的 ③④ 验收门。
- 拿不到（页面壳空、接口要临时 token、点击才加载）→ `no_stable_jd` → manual_review，**不再每日重试**。

#### 子品牌归属计量（防止「父公司蹭达标」）

- `lib/must-apply-list.json` 条目支持两个**可选**字段：
  ```json
  { "name": "京东科技", "pattern": "%京东科技%", "parentPattern": "%京东%", "brandTokens": ["京东科技"] }
  ```
- `getMustApplyCoverage` 计量规则：
  `healthy = 直接匹配的健康岗 + 父公司门户里 title/summary 命中 brandTokens 的健康岗（后者需 ≥3 条才计入）`。
- 实测可达标：京东科技 72、京东物流 97、网易云音乐 107、网易有道 13；**不达标**：盒马 0、优酷 5（低于 3 条的按 0 计，优酷 5 条需人工确认是否真属该品牌，先不计）。
- **性能**：品牌回退不得退化成「每个 brand 扫一次全表」。实现成**一条 SQL**，对 `status='active'` 扫一次，用 `count(*) filter (where ...)` 一次性算出所有 brand 的计数；结果并入现有 60s 聚合缓存；只服务 admin 看板（用户侧看板不受影响）。
- 看板上这类达标要标注「经父公司门户覆盖」，不许伪装成独立源。

#### 看板拆账

- `/admin/health` 必投供给 tab 增加：
  - 清单版本号（`lib/must-apply-list.json` 顶部加 `"_version": "2026Q3-v1"`，读取时忽略下划线开头的键）；
  - 「本轮真实扩源 +N」与「口径变动 ±M」分开显示（复用迁移 `158_admin_health_snapshot` 的快照，若不够用再加列，**别新开一张快照表**）；
  - 缺口漏斗台账卡：各 state 计数 + 最近失败原因 top5 + manual_review 清单。

### 4.4 P3：清单治理证据（只出证据，不改清单）

- 对满足下列任一条件的公司，产出证据条目：
  - `rounds_no_entry >= 2`（连续两轮找不到任何公开投递入口）；
  - `state='login_wall'` 或 `no_stable_jd` 且人工复核确认无公开逐岗页；
  - 校招型公司需**跨过一个完整招聘季**才允许进候选（不能用淡季 90 天淘汰）。
- 产出 `docs/must-apply-governance-2026-07.md`：公司 / 行业 / 证据（搜索到的入口 URL、HTTP 状态、页面性质）/ 建议替换为谁（同行业、公开在招、用户相关）/ 待创始人终审。
- **本轮不自动修改 `lib/must-apply-list.json` 的公司名单**（万达 pattern 修正属于「修假绿」，不算治理换人）。

---

## 5. 红线与不变量（实现时必须守住）

1. **禁止猜 slug 直接入库**。任何 source 入库前必须走完 §4.2 ③④ 的真抓 + 回读。
2. **jd_url 必须是逐岗真实详情页**。招聘首页/搜索页/公告 PDF/登录页一律不入。
3. **第三方招聘平台禁止入库**，国聘（`iguopin.com`）是创始人已拍板的唯一例外，前端需标注来源。
4. **不绕验证码、不伪造登录态、不破签名**；命中反爬一律转 manual_review。
5. **PostgREST 1000 行截断**：所有 `sources` / 用户表全量查询走 `db.fetch_all_rows`（带 `.order("id")`）。
6. **upsert 不变量不许破**：`crawler/jobs_db.py` 的 `_PRESERVE_IF_EMPTY`（summary/job_type 等空值用 COALESCE 保留旧值）、status 走 `CASE` 黏住 `expired`、`_UPDATE_COLS` 不含 `enrich_checked_at`。
7. **迁移**：前缀 185，加前 `ls supabase/migrations` 复核；push 后由 `migrate.yml` 自动 apply，**不要手跑 SQL**。
8. **新 adapter 接线四处**：`crawler/run.py`（ADAPTERS + httpx 名单）、`crawler/probe.py`、`lib/source-adapters.ts`、相关 workflow 的 adapter 分片。
9. **不读、不打印任何密钥**（`.env*`、service_role key、连接串）。

---

## 6. 测试

### 纯函数单测（必须，不打网络）

- `crawler/test_gap_funnel.py`：状态机迁移、retry 策略（30d/14d/manual）、配额裁剪、队列排序。
- `crawler/test_entry_finder.py`：第三方黑名单过滤、已知 ATS host 高可信判定、级联「首个可信即停」（mock provider）。
- `crawler/test_platform_fingerprint.py`：各平台 HTML/URL 指纹样本 → 期望 adapter（样本存 fixture，不打网络）。
- `crawler/test_must_apply.py`：补 `%万达集团%` / `%万达电影%` 拆分后的 pattern 断言。
- `tests/must-apply-list.test.js`：清单结构校验（新增可选字段不破坏现有断言、`_version` 键被忽略）。
- `tests/jobs-store-must-apply.test.js`（或并入现有）：子品牌 rollup 计量——父公司命中 ≥3 条才算达标、<3 条按 0 计。

### 回归四件套（每个阶段结束都要跑）

```bash
node --test tests/*.test.js && \
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
  npm run build && git diff --check
```

### live 验证（沙箱网络可用，自己做，别让创始人代跑）

- P0：4 个 iguopin 老源 + 新增央企源，逐个确认香港库回读到健康岗。
- P1：先 `GAP_FUNNEL_APPLY` 关着跑一轮，人工看台账 20 家的判定是否合理，再打开写入。
- 每阶段结束跑一次覆盖率复核脚本，把「六个塌陷行业的真实数字」贴进 commit message。

---

## 7. 交付与分支

- 在当前 worktree（`top-tab-overlap-a8a305`，分支 `claude/must-invest-companies-coverage-7fd046`）上做。
- 每个阶段（P0/P1/P2/P3）独立 commit，message 写清「改了什么 / 为什么 / 覆盖率前后真实数字」。
- 创始人已授权本任务完成后直接 push（`git fetch origin && git merge origin/main` → 跑回归 → `git push origin HEAD:main`）。
- 冲突或验证失败 → 停下报告，不强推、不 force push。

---

## 7.1 P0 实际落地记录（2026-07-27 完成）

- 合并 `draft/codex-iguopin-0717`（iguopin adapter），4 个老央企源恢复可抓。
- **adapter 的 `match` 过滤从朴素子串换成严格核名**（新增 `crawler/company_name_match.py`）。起因是 live 实测的三个张冠李戴：搜「中通」命中「北京华晋中通电力工程设计」、搜「绿城」命中「中交城投绿城」、搜「华图」命中「山东中卓华图教育」。规则 = token 必须在公司名开头，或只被地名前缀隔开。
- **151 家缺口公司全量过国聘**（两轮：第一轮用清单名当搜索词，第二轮对 0 命中的换法人实体真名，如 中国能建→「中国能源建设」、中国中冶→「中冶」）→ 严格核名 + 全量 detail 终验 → **24 家通过**。
- 24 家逐个走验收门（插源 disabled → 真抓 → 回读香港库健康岗 → ≥1 才 enable），**24/24 全部读到健康岗**：中远海运 247、中国能建 59、中国中冶 39、泰康 28、中国中铁 16、协鑫 14、中南传媒 14、中海油 8、中公教育 8 等。
- pattern 修正：`中国能建 %能建% → %中国能源建设%`、`中南传媒 %中南传媒% → %中南出版传媒%`（原 pattern 与法人实体真名对不上，属写错）。`国家电网` 实体全部叫「国网 XX」，但 `%国网%` 会误命中「中国网络…」，**暂不放宽**，源保留、诚实记为未覆盖 —— 等 P2 的 alias 能力再解决。
- `万达控股集团` 经 live 核实是大连万达商管（万达广场招商营运/商管财务），已把 sources + jobs 的公司名归一为 `万达集团`；`万达电影` 诚实变回缺口。

**覆盖率实测 178/330 → 200/330**（真实扩源 +23，口径修正 −1）。六个塌陷行业：金融 11→13、教育 11→15、能源/化工 12→17、地产/建筑 15→20、物流 9→11、传媒/文娱 9→9（+1 真实、−1 假绿）。

## 7.2 P2 子品牌计量规则修订（2026-07-27 live 实测后覆盖 §4.3 原描述）

原设计写「title 或 summary 命中 brandTokens 且 ≥3 条」。香港库实测后**改为只认 title**：

| 品牌 | title 命中 | 仅 summary 命中 | 结论 |
|---|---|---|---|
| 网易云音乐 | 41 | 66 | title 命中是真岗 |
| 网商银行 | 94 | 3 | 真 |
| 极氪 | 100 | 62 | 真 |
| 京东物流 | 13 | 48 | 真 |
| 优酷 | 0 | 5 | **全假**：阿里「AI 推理平台」岗 JD 里罗列业务线时提了一句优酷 |
| 京东科技 | 0 | 72 | 正文「我们是京东科技…」其实是真岗，但无法与上面那种样板文自动区分 |

也试过「只看 summary 前 120 字」想区分自我介绍与业务线罗列，实测区分不了（优酷那 5 条同样落在前 120 字内）。因此：**只认 title 命中、且 ≥3 条**；仅 summary 命中的落「待人工确认」，不自动算达标（京东科技因此仍记为缺口，诚实）。

---

## 8. 已知会失败的地方（提前认，不要硬刚）

- **银行自建门户是最硬的一块**：四大行、中信/华泰/国泰海通多为自建 + WAF（实测 `zhaopin.sgcc.com.cn` 返 412、`www.se.com` 403 Akamai）。金融行业 +6 大概率要靠：微众修复、同花顺、宁波银行、泰康、京东科技（父门户归属）、网商银行（蚂蚁门户归属）等**非四大行**的公司凑，不要为覆盖数字硬刚银行反爬。
- **央企常发公告+PDF 附件**，没有逐岗详情 URL —— 这类只能靠国聘，国聘也没有就认输记 manual_review。
- **SPA 返回 200 不等于有岗**：壳页面、接口要临时 token、点击才加载的，判 `no_stable_jd`。
- **列表能抓不等于有正文**：SuccessFactors 系常见「有列表无正文」→ 落 `thin_only`，靠 enrich 补，别当成功。
- **外企全球门户可能根本没有中国岗**：Workday 接通但中国岗 0，属于 `no_active_jobs`，不是 adapter 失败，别反复重试。
- **GitHub Actions 跑在境外**，部分国内门户可能对境外 IP 更严。P1 第一轮要在台账里区分「本地能连 / CI 连不上」，如果出现系统性差异，记录下来再决定要不要换出口。
