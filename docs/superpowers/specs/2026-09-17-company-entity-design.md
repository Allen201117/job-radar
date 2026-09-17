# 公司实体模型设计（2026-09-17）

> 起因：2026-09-17 对抗性审查 §7 把「洞察张冠李戴」的根因定为 **「靠公司名字符串在读取时猜归属」**，
> 根治方向写的是 `company_id` 实体表（状态 ⏸ 待创始人点头）。本文把那一行展开成可执行设计。
> 本文只到表定义草案，不含实现代码。所有数字都标了取数出处，可复现。

## 0. 一句话

现在「这个岗属于哪家公司」是**每次读取时用字符串子串现猜**的，四套规则各猜各的（洞察 `findCompanyProfile`、
必投 `resolve_owner`、国聘 `group_id`、清单 `aliases`）。本设计把归属**一次性定死在写入时**，
落成 `companies` 实体表 + 各表的 `company_id` 外键，读取侧只做 join，不再有猜的余地。

---

## 1. 先量：现状到底有多散

取数时间 2026-09-17，脚本见文末「复现」。

### 1.1 名字写法的规模

| 指标 | 数字 | 查询 |
|---|---:|---|
| `sources` 总行 / distinct company | 1,602 / **1,162** | `select count(*), count(distinct company) from sources` |
| 其中 enabled | 1,389 / **1,101** | 同上 + `where enabled` |
| `jobs` distinct company（全表） | **2,399** | `select count(distinct company) from jobs` |
| `jobs` distinct company（active） | **1,576** | 同上 + `where status='active'` |
| active 岗总行 | 492,643 | — |
| `company_profiles` 行 / distinct company | 1,383 / **1,383** | `select count(*), count(distinct company) from company_profiles` |
| 其中带 `aliases` 的画像 | **38 家 / 76 条别名** | `count(*) filter (where array_length(aliases,1)>0)` |

**注意 `sources.company`(1,162) 与 `jobs.company`(1,576 active) 不是一套命名空间**——
差额主要来自国聘那类「一个源带多家公司」的行（见 1.3）。

### 1.2 国聘产物：带「（集团名）」后缀的写法

| 指标 | 数字 |
|---|---:|
| active jobs 里 `company ~ '（[^（）]+）$'` 的 **distinct 写法 / 行数** | **471 种 / 3,484 个岗** |
| `sources` 里同形写法 | 10 行 |

括号内容 top6（distinct 写法 / 岗数）：中国联通 21/635、国投集团 95/530、中国能建 39/421、
中国铝业集团 74/382、中远海运 93/368、航天科工 46/233。

⚠️ 这 471 种写法**不是脏数据**——它是国聘 adapter 用 `group_id` 核过名之后**故意写进 company 字段的归属声明**。
问题在于它是「写进字符串里的外键」：下游（洞察匹配、必投覆盖、校招分面）全部要靠正则把它再解析出来。
实体模型要做的正是把这个括号变成一列 `parent_id`。

### 1.3 一个源带几家公司（决定 `jobs.company_id` 怎么来）

| 一个 source 在 active jobs 里带出的 company 种数 | 源数 | 岗数 |
|---|---:|---:|
| 1 种 | **1,324** | **480,654 (97.6%)** |
| 2–5 种 | 12 | 8,565 |
| 6–50 种 | 12 | 2,090 |
| 50+ 种 | 4 | 1,334 |

👉 **97.9% 的源是单公司源**，`jobs.company_id` 直接由 source 带下来即可；只有 **28 个源 / 11,989 个岗（2.4%）**
需要「按行解析公司」。这决定了迁移的工作量分布——不要为 2.4% 的情况把 97.6% 的路径复杂化。

### 1.4 现有两套匹配器各自的命中率

**A. `findCompanyProfile`（洞察侧，lib/insight-match.ts）**

| 对象 | 命中 | 率 |
|---|---:|---:|
| × `sources.company` 全部 1,162 种 | 1,159 | 99.7% |
| × `sources.company` enabled 1,101 种 | 1,101 | **100.0%** |
| × `jobs.company` active 1,576 种 | 1,304 | **82.7%** |
| 同上，按在招岗位数加权 | 491,747 / 492,643 | **99.8%** |
| 反向：1,383 个画像里被某个在招公司名匹配上的 | 1,155 | 83.5% |

未命中的 272 种写法几乎全是 1.2 那批国聘子公司长名（top10 全是「…（中国铝业集团有限公司）」「…（航天科工）」之类），
每种只挂 8–9 个岗，所以**加权后看着 99.8% 很漂亮，按写法看只有 82.7%**。
📌 `sources` 侧 100% 是因为 `company_profiles` 本来就是从 sources 派生的——**这个数字不能当作「匹配器很准」的证据**。

**B. `resolve_owner`（必投侧，crawler/must_apply.py）**

| 指标 | 数字 |
|---|---:|
| 必投清单规范名（国内 329 + 海外 326，去重） | **652** |
| `owner_index()` 条目（规范名 + 别名） | 662（别名实际生效 **10** 条） |
| 清单里声明的 `aliases` 总条数 | **23 条**（国内 3 家 3 条 / 海外 20 家 20 条） |
| × `sources.company` 1,162 种 → 能归到某一家 | 452（38.9%），覆盖 375/652 家 |
| × `jobs.company` active 1,576 种 → 能归到某一家 | 606（38.5%），覆盖 **361/652** 家 |

⚠️ 别名声明 23 条、实际进 `owner_index` 只有 10 条——差额被「规范名恒压过别名」吃掉了（`owner_index` 的 `setdefault`）。
**这本身就是「口径活在两套代码里」的症状**：清单里写了 23 条，运行时只生效 10 条，没有任何地方会报这个差。

### 1.5 关键：两套匹配器互相打架

拿同一个 `jobs.company` 写法，一边问 `resolve_owner`（必投归谁）、一边问 `findCompanyProfile`（哪个画像），
再用 `companyMatches` 检查两个答案是不是同一家：

| 指标 | 数字 |
|---|---:|
| 两套都给出结论的公司名 | **586 种** |
| 两套结论**互不相认** | **46 种 / 39,912 个在招岗（占 586 种的 7.8%）** |

46 条逐条看过，分三类：

1. **必投侧真·张冠李戴（裸子串）—— 8 种 / 2,297 个岗**，全部是 `resolve_owner` 拿**规范名**当子串 token：

   | 库里写法 | 被错归给 | 岗数 |
   |---|---|---:|
   | 达信 Marsh McLennan | **Mars**（玛氏） | 1,715 |
   | MiniMax 稀宇科技 | **IMAX** | 182 |
   | 渤健 Biogen | **GE**（"bio**ge**n"） | 168 |
   | 老虎国际 Tiger Brokers | **GE**（"ti**ge**r"） | 75 |
   | Gemini | **GE** | 62 |
   | 极智嘉 Geek+ | **GE** | 61 |
   | 广州文搏智能科技（FlashForge） | **GE**（"Flash**Forge**"？→ "for**ge**"） | 31 |
   | MetaApp | **Meta** | 3 |

   📌 **清单的 `pattern` 写得很严**（`%General Electric%` / `%Meta Platforms%` / `%Mars, Inc%`），
   错的是 `resolve_owner` / `owner_index` 用的是 **`name`**（"GE"/"Meta"/"Mars"）。
   同一份 JSON 的两个字段被两条链当成两种语义 —— 这正是「口径散落」的代价，不是某个正则写歪了。

2. **真·集团 vs 独立法人的争议 —— 需要人拍板的，不是 bug**：
   `北京现代汽车有限公司（北汽集团）` 必投判 **Hyundai**、括号自报 **北汽**（合资公司，两边都对）；
   `中海油田服务（中国海油）`、`腾讯微保 WeSure`、`吉利汽车 / 吉利德 Gilead`、`TCL中环 / TCL华星`、`菜鸟驿站`。
3. **同一家、只是拉丁短名被资格门挡掉 —— 无害**：`AMD 超威`、`Citi 花旗`、`GSK`、`Dow`、`汇丰 HSBC`…

另有一个**用括号当真值**的对拍：471 种国聘写法里，「按主体名猜出的归属」≠「括号自报集团」只有 **2 种 / 82 个岗**
（北京现代、好未来（学而思））——说明国聘那条 `group_id` 核名链**本身是可信的**，
可信的恰恰是那条「查了对方的结构化 id」的链，不是猜字符串的链。

---

## 2. 设计：`companies` 实体表

### 2.1 表定义草案

```sql
-- 公司实体（唯一事实源）。放 Supabase（与 sources / company_profiles 同库，便于外键）。
create table public.companies (
  id            uuid primary key default gen_random_uuid(),
  canonical_name text not null,            -- 归一键：小写、去装饰后缀（复用 normalizeCompany 口径）
  display_name  text not null,             -- 给用户看的品牌名：「腾讯音乐」
  legal_name    text,                      -- 工商全称（有就填）：「腾讯音乐娱乐科技（深圳）有限公司」
  parent_id     uuid references public.companies(id),  -- 集团关系；NULL = 自己就是顶层
  relation      text not null default 'standalone'
                check (relation in ('standalone','subsidiary','joint_venture','brand')),
  industry      text,                       -- 与 lib/company-industry 的枚举同源
  country_code  text,
  aliases       text[] not null default '{}',  -- 库里出现过的其它写法（含英文名）
  origin        text not null               -- 这行是怎么来的：seed / iguopin_group / manual / auto_discover
                check (origin in ('seed','iguopin_group','manual','auto_discover')),
  verified_at   timestamptz,                -- 人工复核过的时间；NULL = 仅自动映射
  created_at    timestamptz not null default now()
);
create unique index companies_canonical_key on public.companies (canonical_name);
create index companies_parent_idx on public.companies (parent_id);
```

**四个字段解释为什么必须有**：
- `relation`：`北京现代（北汽集团）` 是合资公司，`parent_id` 只能挂一个，`relation='joint_venture'` 让下游知道
  「这家同时是 Hyundai 的」不是错，而是**这个模型有意不表达的东西**（详见 §4 风险）。
- `origin` + `verified_at`：自动映射与人工核过的必须能分开，否则「一致率达标」会把自动错的算成对的。
- `aliases`：**只收「库里真出现过的写法」**，不收推测——这是「宁可漏判不可错杀」的落地。
- `canonical_name` 唯一索引：两条实体撞同一个归一名 = 合并冲突，必须在写入时炸，不能靠读取时挑一个。

### 2.2 各表挂 `company_id`（全部先做影子列，`null` 允许）

| 表 | 新列 | 怎么填 |
|---|---|---|
| `sources` | `company_id uuid references companies(id)` | 一次性映射（§3），单公司源 97.9% |
| `jobs`（香港库） | `company_id uuid` （**不加跨库外键**，香港库里没有 companies 表） | 写入时由 `crawler/jobs_db` 从 source 带下来；国聘等多公司源按行解析后带下来 |
| `company_profiles` | `company_id uuid references companies(id)` | 一次性映射 |
| `must_apply_gap_attempts` | `company_id uuid` | 清单条目映射后带下来 |
| 必投清单 `lib/must-apply-list*.json` | 每条加 `"company_id": "<uuid>"` | 保留 `pattern`/`aliases` 不删（回滚用） |

⚠️ **`jobs.company_id` 不加外键是刻意的**：jobs 在自建香港 PG、companies 在 Supabase（悉尼），
跨库外键做不到。代价 = 香港库里可能出现指向已删实体的 id → 由每日 db-report 对拍孤儿 id 兜底，
**不许靠「反正不会删」这种假设**。

### 2.3 读取侧怎么变

| 现在 | 之后 |
|---|---|
| `findCompanyProfile(profiles, job.company)` 逐次子串猜 | `job.company_id = profile.company_id` 直接等值 |
| `resolve_owner(source.company, owner_index())` | `source.company_id in (清单条目的 company_id 集合)` |
| 国聘 `（集团名）` 后缀 + 正则解析 | `companies.parent_id` |
| 清单 `aliases` ILIKE 模式 | `companies.aliases`（一处登记，两端共读同一实体） |

`jobs.company` 这个字符串列 **不删**：它是「对方门户当时自报的名字」，是第一手证据，
删了就再也无法复核映射对不对。实体 id 是**结论**，字符串是**观测**，两者并存。

---

## 3. 数据回填：1,162 个 sources 名字 → 实体

### 3.1 三档自动 + 一档人工

以 `sources.company`（1,162 种）为种子建实体，分四档：

| 档 | 判据 | 预估量 | 处置 |
|---|---|---:|---|
| **A 唯一归一名** | `normalizeCompany` 后全库唯一、且不被任何其它名包含 | ~900 种 | 自动建实体，`origin='seed'`，`verified_at=null` |
| **B 集团自报** | `company ~ '（集团名）$'` 且括号内容能映射到 A 档某实体 | **471 种写法（jobs 侧）/ 10 行（sources 侧）** | 自动建子实体 + `parent_id`，`origin='iguopin_group'`；国聘 `group_id` 直接落成 parent（§4.2） |
| **C 互相包含** | 归一后 X ⊂ Y（京东/京东方、腾讯/腾讯音乐、TCL/TCL华星） | 由 §1.5 的 46 条 + 现有子串门 dropped 64 对推算，**≈150 对** | **必须人工**：两条独立实体？还是 parent/child？ |
| **D 跨语言 / 无重叠** | 中英文互不包含（壳牌/Shell、大陆集团/Continental、达信/Marsh McLennan） | 现有 `aliases` 已登记 23 条 + 1.5 里 46 条中的拉丁类 ~20 条，**≈50 对** | 人工确认后写进 `companies.aliases` |

**人工量估算：C + D ≈ 200 对，每对判断「同一家 / 母子 / 无关」，按 20 秒一条 ≈ 70 分钟。**
这是一次性成本，且**只需要做 C/D 两档**——A 档 900 种不看（唯一名没有歧义空间）。
📌 这个估算里的 A 档 ~900 是推算不是实测（我没跑「归一后唯一且不被包含」这条查询）——**实施第一步就是把它跑实**，
若 A 档显著低于 900，人工量线性上升，要重新评估。

### 3.2 人工复核清单怎么生成

一张 CSV，每行一对候选，**按影响面（岗位数）倒序**，附四列证据让人能一眼判：
`名字A | 名字B | A的岗数 | B的岗数 | 两家的 jd_url 域名 | 国聘group_id是否相同`。
域名那一列是最强判据——`boe.com` vs `jd.com` 一眼分开京东方和京东，不需要人懂业务。

### 3.3 增量：新源怎么进

新增源时，`normalizeCompany` 命中已有实体 → 复用；不命中 → **建新实体并进人工队列**（`verified_at=null`）。
🚫 **绝不做「自动挂到最相似的实体上」**——那就是把子串猜测换了个地方继续猜。

---

## 4. 风险与红线：历史坑在新模型下怎么被结构性杜绝

| 历史坑 | 旧模型为什么必然踩 | 新模型怎么杜绝 |
|---|---|---|
| **京东 / 京东方** | `%京东%` 是子串，`京东方` 必然命中；`resolve_owner` 靠「最长者胜」这条**约定**兜住，一旦有人写了 `%京东%` 而没写 `%京东方%` 就漏 | 两条独立 `companies` 行，`parent_id` 都是 NULL。归属在**写入时**定死，读取时没有「猜」这个步骤，所以没有可漏的约定 |
| **中通 / 北京华晋中通电力** | 搜索源返回法人全称，`company_name_matches` 靠「token 必须在开头」这条启发式挡 | 搜索返回的候选**不允许直接入库**：必须先落到一个 `company_id`（命中已有实体 or 进人工队列）。不认识的法人 = 不入库，不是「猜一个」 |
| **中国建筑 / 中国建研院** | 括号自报的集团被子串规则盖过（2026-09-17 §8 ②′ 刚修） | 括号 = `parent_id` 一等公民。**数据自报的结构化归属优先级恒高于名字推断**，写成外键就没有「盖过」这回事 |
| **大陆集团 / Continental** | 中英文零重叠，单向子串救不了 → 判「零源缺口」→ 重复插源 → 同岗两行 | 同一实体的 `aliases` 里同时有中英文；必投清单条目直接引 `company_id`，**「有岗但指标显示 0」这一类从定义上消失** |
| **达信 Marsh McLennan → Mars（本次实测 1,715 个岗）** | `resolve_owner` 拿规范名 "Mars" 当子串 | 清单条目 = `company_id`，不再有 token |
| **国聘集团展开 84% 挂错（2026-07 实录 2,439 个岗）** | 「可信来源」旁路了核名门 | `group_id` 是**唯一**能写 `parent_id` 的自动来源（§4.2）；名字推断**不允许**写 `parent_id` |

### 4.1 新模型自己的新风险（必须写下来，否则就是只报好消息）

1. **合并错了比猜错了更难回滚**：把两家合成一个实体后，`job_actions` / 洞察都挂过去了，拆回来要逐行判。
   → 防：合并操作只允许人工、必须记 `origin='manual'` + 操作留痕；**自动链只许建新实体，不许合并**。
2. **`parent_id` 只能挂一个母公司，合资公司天然表达不了**（北京现代 = 北汽 × Hyundai）。
   → 本设计**刻意不做多母公司**（那是图，不是树，下游查询复杂度翻倍）。合资走 `relation='joint_venture'` +
   `parent_id` 挂**实际发薪的那家**，另一家写进 `aliases` 备注。代价写明：按 Hyundai 筛不到北京现代。
3. **实体表本身会过期**（改名、被并购）。→ `verified_at` + 每季度对拍「实体名 vs 库里最新写法」。
4. **影子期双写不一致**：写入侧要同时写 `company` 和 `company_id`，漏一处 = 静默。
   → 防：`company_id is null` 的 active 岗数进 db-report，>0 且在涨就告警。

### 4.2 国聘 `group_id` 怎么落到 `parent_id`

现在 `iguopin.py` 的 `_company_group_id` 已经返回**三态**（有集团 / 查到了无集团 / 请求失败）。映射规则照搬这个三态：

| `_company_group_id` 返回 | `companies` 怎么写 |
|---|---|
| 非空 group_id | 该 group_id 对应的集团实体（没有就建，`origin='iguopin_group'`）→ 写 `parent_id`，`relation='subsidiary'` |
| `""`（定论：无集团） | `parent_id = null`，且**记下「这是定论」**（`verified_at` 由这条定论盖上） |
| `None`（请求失败） | **什么都不写**，`parent_id` 保持 null 且不盖 `verified_at`，下轮重查 |

🔴 红线：`companies.external_ref` 建议加一列存 `iguopin_group_id`，让「这个 parent 是谁说的」可追溯。
**绝不允许把「请求失败」和「确认无集团」写成同一种状态**——2026-09-04 国聘那次 84% 错配的两次修复失败，
错的正是把这两态混成一种。

---

## 5. 分阶段计划（每阶段独立上线、独立回滚）

| 阶段 | 做什么 | 上线判据 | 回滚 |
|---|---|---|---|
| **P0 只读报表**（无迁移） | 跑一个只读脚本，产出 §1.5 那张「两套结论互不相认」表 + §3.1 四档分布，**先把 A 档实测出来** | 报表能复现、数字可指出查询 | 删脚本 |
| **P1 建表 + 影子列** | 迁移 256：建 `companies`，给 `sources` / `company_profiles` 加 `company_id`（全 null）；香港库迁移给 `jobs` 加 `company_id` | 迁移 apply 成功、无任何读取方使用新列 | `drop column` / `drop table`（没人读，零影响） |
| **P2 自动回填 A/B 档 + 人工 C/D** | 建实体、填 `sources.company_id`；人工清单走一遍 | `sources.company_id` 非空率 ≥95%；C/D 档 200 对全部有人看过 | 把 `company_id` 置 null，旧链路完全没动 |
| **P3 写入侧双写** | crawler / `lib/jobs-store/write.ts` 写 jobs 时带 `company_id`；**旧字符串匹配照常跑** | 新入库 active 岗 `company_id` 非空率 ≥97%（对齐 §1.3 的 97.6%） | 停止双写，列留着 |
| **P4 不一致报表驱动核对** | 每日跑「实体 join 结果 vs 旧字符串匹配结果」的差异表，进 `ops_runs` | 连续 7 天差异表里**没有新增**「实体错、字符串对」的条目 | — |
| **P5 切读（分链，不一次切）** | 顺序：洞察 → 必投覆盖 → 校招分面。每条链单独切、单独观察一周 | 见 §6 验收 | 每条链一个 env 开关，切回字符串匹配 |
| **P6 退役** | 旧匹配器打 `@deprecated`、清单 `pattern` 降级为「仅回滚用」 | P5 全部稳定 ≥2 周 | — |

**P2 与 P3 之间不得跳步**：没有回填就双写，会让 97% 的岗带着 null id 入库，后面再补是全表回填。

---

## 6. 验收指标（双向计数，不许只报净值）

按 CLAUDE.md「①的量必须双向」：每条指标都要分项，**不许只给总数或净值**。

| 指标 | 现状基线（2026-09-17 实测） | 目标 | 双向计数怎么报 |
|---|---|---|---|
| **洞察归属错配率** | 两套结论互不相认 **46 种 / 39,912 岗**，其中真错配 **8 种 / 2,297 岗** | 真错配 = **0** | 报「旧对新错 X 条 / 旧错新对 Y 条」，**X 必须为 0**（纯收紧，与 2026-09-17 子串门那次同判据） |
| **洞察可匹配率（按写法）** | `findCompanyProfile` × active company 名 **82.7%**（1,304/1,576） | ≥98% | 分「新命中 / 新丢失」两列；新丢失逐条人工看 |
| **必投覆盖家数** | `resolve_owner` 覆盖 **361/652** 家 | 数字会**变动**，变动本身不是成功 | 必须报「新增覆盖 A 家 / 失去覆盖 B 家」，B 逐家给理由（是本来就错配的，还是真丢了） |
| **jobs.company_id 非空率** | 0 | active ≥97.6%（= §1.3 单公司源占比） | 分「source 带下来 / 按行解析 / 仍为 null」三档 |
| **国聘 parent_id 覆盖** | 471 种括号写法靠正则 | 471 种全部落成 `parent_id` | 报「parent 与括号一致 / 不一致 / 括号有但 group_id 查不到」三档 |
| **人工复核完成度** | — | C/D 档 200 对 100% | `verified_at` 非空的实体数 |

🚫 **不许拿「没报错 / 单测绿 / 覆盖数字变大」当验收**。必投覆盖从 361 涨到 500 可能全是新的错配。

---

## 7. 明确不做的

- **不做多母公司 / 股权图**（见 §4.1-2）。
- **不删 `jobs.company` / `sources.company` 字符串列**——它是观测，实体 id 是结论。
- **不引入外部公司库（工商数据 / 企查查）**：授权与成本未评估，且会引入第二个「可信来源旁路核名门」的诱惑。
- **不在本设计里动匹配算法本身**：`lib/insight-match.ts` 的三层子串门在 P5 之前照常跑，P6 之后只作回滚用。

---

## 复现

```
# 1.1 / 1.2 / 1.3：psql 计数，查询原文见各表格右列
# 1.4 A：node 加载 lib/insight-match.ts（tests/_load-ts.js）× company_profiles 全量 × jobs/sources distinct company
# 1.4 B / 1.5：python3 引 crawler/must_apply.py 的 owner_index()/resolve_owner，
#              与 findCompanyProfile 的结论用 companyMatches 互检
```
取数脚本落在本次会话的 scratchpad，未入库（一次性取证，不是需要维护的工具）。
P0 阶段要把 §1.5 那张表做成可重复跑的只读报表再入库。
