# 校招供给基座设计（2027 届秋招正式批）

**日期**：2026-08-04
**背景**：2027 届秋招正式批陆续开闸。校招公司的特点是**一次性放出全部岗位**——一家开闸即新增几百到几千岗。
校招专区是产品面向最大用户群（应届生）的核心场景，其地基是「开闸那一刻能不能完整、及时地把岗位捞进库」。

---

## 0. 现状摸底（2026-08-04 live 实测，非推断）

### 0.1 库里现状

- 校招类 active 岗 **16416**，近 7 天新增 **3740** —— 抓取链路在跑，不是停摆。
- 但分布极不均：字节 2155 / 比亚迪 2053 / 人保 1873 / 好未来 1004 / 小红书 589，
  头部互联网大多是个位数到几十。

### 0.2 头部大厂校招板块覆盖（逐源核对 + live 探接口）

| 公司 | 现接源 | 库内校招岗 | 判定 |
|---|---|---|---|
| 阿里（13 个 BU） | `…/off-campus/position-list`（字面即社招频道） | 1 | ❌ 校招频道未接 |
| 快手 | `zhaopin.kuaishou.cn/#/official/**social**/` | 1 | ❌ 校招板块未接 |
| 美团 | `zhaopin.meituan.com/web/position`（社招） | 58 | ❌ 校招在 `/web/campus` |
| 网易 | `hr.163.com` queryPage（社招） | 34 | ❌ 校招在 campus.163.com |
| 拼多多 / vivo / 顺丰 / 大疆 / 腾讯音乐 | 仅社招 | 0 | ❌ |
| 小米 / 京东 / 百度 | — | 1~14 | ⚠️ 见下 |
| 腾讯 | `attrId` 1/2/3 三板块全翻 | 20 | ✅ 已覆盖 |
| 字节 | `bytedance_campus` 独立源 | 2155 | ✅ 已覆盖 |

### 0.3 关键结论一：**大厂 2027 届正式批基本还没开闸**

live 探证：

- 腾讯 `careers.tencent.com` API：社招 `Count=2215`、**校招 `Count=17`**、实习 83。
  → 我们的 20 不是漏抓，是腾讯自己还没放。
- 阿里淘天校招频道：`totalCount=34`，首条标题写着「T-Star Lab **26 届**秋招」= 上一届尾巴。

**所以本工程不是补历史欠账，是抢在开闸前把基座建好。** 时间窗即当下。

### 0.4 关键结论二：**「校招板块」多数是同一 ATS 换频道，不必逐家写 adapter**

live 探证（淘天 `talent.taotian.com`，同一 `/position/search` 接口）：

| channel | totalCount |
|---|---|
| `GROUP_OFFICIAL_SITE` | 605（社招，我们现在抓的） |
| `""` / 任意无效值 | 34（服务端 fallback 集） |

→ 阿里校招频道**确实存在且同接口可达**，但正确的 channel 常量需从校招页前端 bundle 里挖
（`CAMPUS_OFFICIAL_SITE` 等猜测值均被服务端当作无效值 fallback，**不能靠猜**）。
这确立了本设计的探测原则：**每家都要 live 探证，猜出来的一律不入库。**

### 0.5 已有能力盘点（不重复造）

- 百度 adapter 自身循环 `RECRUIT_TYPES = (SOCIAL, CAMPUS, INTERN)` → 单源已覆盖三类，
  故 `campus-list` 源被迁移禁用是**正确去重**，不是 bug。
- 北森 `Category: []` 不按类别过滤 → `/campus` 与 `/social` 抓回同一份（迁移 186 已去重）。
- 缺口漏斗 `crawler/gap_funnel.py` 的「先插 disabled 源 → 真抓 → 回读健康岗 ≥1 才 enable」
  验收门已在必投清单场景验证有效，本设计直接复用该工艺。

### 0.6 时效现状

- httpx 快档 `daily-crawl.yml`：每日 4 次（UTC 1/7/13/17）。
- 浏览器档 `enrich-crawl.yml`：每日 UTC 18，6 片并行全量覆盖一遍。
- **抓取队列中没有「校招优先」概念**，校招源与普通社招源同等排队。
  → 一家公司开闸后，最坏要等 6~24 小时才进库。

---

## 1. 目标与非目标

**目标**：秋招正式批开闸时，目标公司放出的校招岗

1. **进得来**（校招板块已接通）
2. **进得快**（1 小时内）
3. **进得全**（放 3000 个就进 3000 个，不被分页/超时截断且能自检）
4. **显示对**（届别正确、开闸状态可见）

**非目标（本轮不做）**：

- 通知 / 推送（邮件、微信）——地基优先。
- 第三方招聘平台（国聘除外，红线不变）。
- 校招岗的 JD 正文富化提速（走已有 enrich 链路，不在本设计内）。

---

## 2. 总体结构

五块，① 是 ②③④ 的共同地基：

```
① sources.board（校招源成为一等概念）
   ├─→ ② 补管子（把缺的校招源探出来、验证后入库）
   ├─→ ③ campus-crawl.yml（秋招高频专用车道）
   └─→ ④ 开闸检测 → 加急重抓 → 抓全兜底
⑤ jobs.grad_class（届别，展示层正确性，与上面四块解耦）
```

---

## 3. ① sources.board —— 校招源成为一等公民

### 3.1 问题

系统当前无法回答「哪些源是校招源」。`lib/campus-zone.ts` 的 `hasCampusSource` 靠 URL 里有没有
`campus` 字样判断——这个判据已经出过事故：靠 `job_type=校招` 识别、但列表 URL 不含 campus 令牌的
通用源（飞书 / moka / beisen 通用租户 / 自建 SPA），会被误判成「⚙️ 待接入」，而卡面同时列着真岗，
自打脸（见 [[job-radar-campus-zone]] 复审踩坑）。

### 3.2 设计

`sources` 加列：

```sql
alter table sources add column if not exists board text not null default 'social';
-- 取值：'social' | 'campus' | 'intern' | 'mixed'
```

**`mixed` 的定义**：该源的 adapter 一次抓取即覆盖社招+校招+实习全部类别。

**回填规则（按 adapter 真实能力，不按 URL 猜）**：

| 判据 | board |
|---|---|
| adapter ∈ {`tencent`, `baidu`, `beisen`} —— 代码中确证一次抓全类别 | `mixed` |
| adapter = `bytedance_campus` | `campus` |
| URL 含 campus 令牌 且 adapter 非上述 mixed 集 | `campus` |
| URL 含 intern 令牌 | `intern` |
| 其余 | `social` |

⚠️ **不变量**：mixed 判据来自 adapter 源码事实（`tencent.BOARD_ATTRS`、`baidu.RECRUIT_TYPES`、
`china_ats` 的 beisen `Category: []`）。新增/修改 adapter 使其覆盖范围变化时，**必须同步此回填规则**，
否则校招车道会漏抓或空跑。

### 3.3 下游接线（三处）

1. **`lib/campus-zone.ts`**：`hasCampusSource` 改为 `board in ('campus','mixed')`；
   **保住既有不变量**——`campusJobCount > 0` 仍然优先于 board 判定（有真岗就不许显示「待接入」）。
2. **`crawler/run.py`**：支持 `--board campus,mixed` 过滤源，供 ③ 的高频车道使用。
3. **运营看板**：校招源覆盖数进 `/admin/health`。

---

## 4. ② 补管子 —— 40 家头部的校招板块

### 4.1 分档（按投入产出）

- **A 档 · 换频道即得**：同一 ATS/同一接口，换 channel 参数或路径即可。
  阿里 13 BU、快手、美团、网易、小米、B 站、携程、顺丰、腾讯音乐。
- **B 档 · 已覆盖，只需验证**：腾讯、百度、字节、京东（hotjob school）、拼多多、OPPO、
  滴滴（moka campus）、大疆（moka campus）。**只做验证与标 board，不改代码。**
- **C 档 · 硬骨头**：无公开接口的 SPA。尽力探，探不到就**诚实留白**（专区显示「待接入」）。

### 4.2 探测工艺（`crawler/campus_board_probe.py`）

复用缺口漏斗的验收门形状：

```
取目标公司（必投清单 ∩ 无 campus/mixed 源）
  → 按其已有社招源的 adapter 推候选校招入口（换 channel / 换路径 / 已知模板）
  → live 探：接口可达 ∧ 返回岗位数 ≥1 ∧ 标题核验归属该公司
  → 插 disabled 源 → 真抓一轮 → 回读香港库该源健康岗 ≥1
  → 才 enable；否则删源 + 删本次脏岗，按失败原因退避
```

**失败退避**（照抄 `must_apply_gap_attempts`）：入口猜错 30 天、探到但当前 0 岗 14 天、
反爬/登录墙转人工不再自动跑。

### 4.3 台账表

```sql
create table campus_board_attempts (
  company text primary key,
  stage text not null,          -- probed / inserted / verified / failed
  fail_reason text,
  candidate_url text,
  recheck_after date,
  updated_at timestamptz default now()
);
```

admin 可读，service_role 可写。**目的是不重复空烧**——同一家探不出来不要天天探。

### 4.4 精度红线（不可让步）

- **禁止猜 slug/channel 直接入库**。0.4 已证明服务端对无效 channel 会 fallback 返回一份
  看起来「有数据」的结果——**能返回数据 ≠ 猜对了**。所以验收门必须是「回读库里有健康岗」
  而不是「接口返回 200 且非空」。
- 归属核验复用 `crawler/company_name_match.py`，防同名子串张冠李戴。

---

## 5. ③ campus-crawl.yml —— 秋招高频专用车道

```yaml
on:
  schedule:
    - cron: "20 * * * *"   # 每小时一轮，与 daily-crawl(整点) / enrich-crawl(UTC18) 错峰
  workflow_dispatch:
```

- 抓取范围：`board in ('campus','mixed')` **且** 公司在必投清单内。
  规模约几十个源 → 单轮几分钟，成本可忽略（公开仓库 Actions 分钟无限）。
- **季节门**：仅在 8–11 月（秋招）与 2–4 月（春招）启用高频；淡季由 workflow 内部
  判月份直接早退，避免全年无谓请求目标站点。判月份而不是删 cron，便于随时手动触发。
- 与 `daily-crawl` 的关系：daily-crawl 覆盖面不变（仍抓全部源），本车道是**叠加的加密轮次**，
  不替代、不减少既有覆盖。

---

## 6. ④ 开闸检测 + 加急重抓 + 抓全兜底 ⭐

这块是「确保放出来的岗我们全都拿到」的核心保险，也是本设计中唯一新增的控制回路。

### 6.1 快照

每轮校招车道抓完，按源记录一行快照：

```sql
create table campus_board_snapshots (
  id bigserial primary key,
  source_id uuid not null,
  company text not null,
  campus_job_count int not null,      -- 该源当下 active 校招岗数
  reported_total int,                 -- adapter 自报的官网总数（可空）
  captured_at timestamptz not null default now()
);
```

### 6.2 开闸判据

```
surge = campus_job_count >= max(prev_count * 3, prev_count + 50)
```

两个条件取大，兼顾两种形态：从 17 涨到 800（倍数）、从 0 涨到 60（增量）。
`prev_count` 取该源最近一条快照。首次快照不判开闸（无基线）。

### 6.3 触发动作

1. **立刻全量重抓该源**：不等下一轮定时；翻页到底；放开 adapter 的保守 `MAX_PAGES`
   上限（改用 `reported_total` 推导页数）。
2. 写入开闸事件（`campus_board_snapshots` 加 `surge` 布尔列即可，不另建表）。

### 6.4 抓全校验（诚实自检）

抓完比对：

```
coverage = 入库该源 active 校招岗数 / adapter.reported_total
coverage < 0.9  →  标记未抓全 → 自动重试一次 → 仍不足则看板报红
```

⚠️ **前提约束**：`reported_total` 仅在 adapter 真实自报时可用（腾讯 `Count`、美团 `totalCount`、
网易 `total`、阿里 `totalCount` 均有）。**adapter 没有自报总数时不得填假值**，此时跳过校验并在
看板标「无法校验」——宁可承认测不了，不许编一个数字让指标好看。

### 6.5 与 list-absence 探活的关系（防误删红线）

⚠️ 本设计**不引入任何新的撤岗路径**。开闸重抓走的是普通 upsert，
`jobs_db.sweep_absent_jobs` 的既有双安全闸（仅 `fetch_complete` 的源 + 单源缺席占比 >50% 跳过）
原样保留。**严禁**从「快照数字下降」反推撤岗——见 [[job-radar-liveness-rotation-starvation]]
华为 460 个在招岗差点被误删的教训：列表条数少于库存有两种成因，处置相反。

### 6.6 用户侧展示

专区公司卡在开闸事件 7 天内显示「🔥 刚开正式批」。
数据来源即 `surge=true` 的最近快照，不新增判断逻辑。

---

## 7. ⑤ 届别 grad_class

### 7.1 字段

```sql
alter table jobs add column if not exists grad_class smallint;   -- 如 2027
```

### 7.2 抽取规则（纯函数，`lib/grad-class.js` + `crawler/grad_class.py` 同口径）

**只认硬信号**，命中即取，全不命中返回 `null`：

- `2027届` / `2027 届` / `27届` → 2027
- `2027校招` / `2027年校园招聘` / `2027秋招` / `2027春招` → 2027
- 英文 `Class of 2027` / `2027 Graduate` → 2027
- 同理适用于 2026 / 2028
- 命中多个不同届别 → 取**最大**（招聘文案常写「2026/2027 届均可」，取更晚的那届更贴合当季）

### 7.3 ⚠️ 明确否决：不用入库时间推届别

初版选项中曾包含「用入库时间兜底」，**本设计明确去掉**。理由：8 月抓到的校招岗大概率是 2027 届，
但也可能是 2026 届的收尾岗——靠时间推等于猜，会把 26 届残岗错标成 27 届，比留白更伤用户。
且 `first_seen_at` 曾被 2026-06-15 库重建污染（见 [[job-radar-campus-zone]] A0 摸底），
不是可靠的时间基准。

**留白的展示后果**：`grad_class = null` 的岗**照常展示、不隐藏**，只是不显示届别标签。

### 7.4 专区展示

- 默认列表 = `grad_class = 当季届别` ∪ `grad_class is null`。
- `grad_class` 明确小于当季（如 2026）的岗 → 移出默认列表（可通过筛选看到）。
- 当季届别推导：纯函数按当前月份定（5–12 月 → 次年+1 届；1–4 月 → 当年+1 届），
  与已有 `lib/recruitment-cycle.ts` 的选季逻辑同口径。

---

## 8. 测试策略

| 单元 | 测法 |
|---|---|
| board 回填规则 | 纯函数 + 表驱动单测（各 adapter → 期望 board） |
| `windowStatus` 改吃 board | 补测「有校招岗 + board=social」仍判 hiring（保住既有不变量） |
| 开闸判据 surge | 纯函数单测：17→800 ✅ / 0→60 ✅ / 0→10 ❌ / 首次无基线 ❌ |
| 抓全校验 coverage | 纯函数单测：含 `reported_total = null` 时返回「无法校验」而非 0 |
| grad_class 抽取 | 纯函数单测：各硬信号 + 多届取大 + 无信号返 null |
| 探测工艺 | crawler unittest，**不打真实网络**（mock httpx） |

live 验证（沙箱可做，本环境网络通）：探测器对 A 档公司的真实产出、首轮车道产出数。

---

## 9. 上线顺序与风险

**顺序**：① → ③ + ④ → ⑤ → ②（边探边补）。
理由：①③④ 是机制，一上线就对**已接通的源**生效；② 是持续产出，晚一天不阻塞机制。

**风险与对策**：

| 风险 | 对策 |
|---|---|
| 高频车道打爆目标站点被限流 | 只跑几十个源、每小时一轮；季节门限制在招聘季；沿用既有并发上限 |
| 开闸重抓遇大批量 upsert 超时 | 复用既有分页 helper 与 upsert 路径，不新增写入通道；失败按源记录，下一轮续 |
| 探测猜错入脏源 | 验收门=回读库里健康岗 ≥1，猜错自动删源删岗（4.4） |
| 快照数字下降被误当撤岗 | 6.5 明确禁止，不新增撤岗路径 |
| `board` 回填错导致车道漏抓 | 回填按 adapter 源码事实；新增 adapter 须同步规则（3.2 不变量） |
