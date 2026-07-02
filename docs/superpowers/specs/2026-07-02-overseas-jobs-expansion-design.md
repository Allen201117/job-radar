# 海外岗位打通 & 填充设计（Overseas Jobs Expansion）

> 状态：**设计脑暴中，待用户确认后交 Codex 实施**（2026-07-02）。
> 作者：Claude（应用户「岗位库只有国内岗，把海外大公司岗位也放进来」诉求脑暴）。
> 基线分支：`claude/wonderful-liskov-066845`（worktree）。
> 实施方：Codex；验收方：Claude（本文档作者）。

---

## 0. 一句话结论 + 服务对象

把海外机会加进**现有中文产品**，不做全站英文。管道是现成的——14 个外企 ATS 适配器（Workday / Amazon / Google / Microsoft / Greenhouse / Lever / Phenom / Oracle / Eightfold / SmartRecruiters / Ashby / Apple 等）**早就打通了，只是被写死成「只抓在华岗」**。本设计把「只抓中国」这道闸按地区放开（美国 + 新加坡 + 全球远程），加结构化地区字段 + 全局「求职范围」开关，让海外岗与国内岗**物理共库、逻辑隔离**，并把中文简历/岗位卡标签/岗位库治理这套机制**复用**到英文 JD 上。

**服务两类人（不做全站 i18n）：**
1. 国内用户出海求职（中文简历，找美/新/远程岗）
2. 海外华人 / 留学生就地求职（人在海外，找当地岗）

两类人共用一套中文界面 + 「求职范围」开关 + 地区筛选，无需切换语言。

---

## 1. 关键决策（用户 2026-07-02 拍板）

| # | 决策 | 取值 | 影响 |
|---|---|---|---|
| 1 | 目标用户 | **两者都要**（国内出海 + 海外就地） | 不做全站英文；市场覆盖两类人群去向 |
| 2 | 优先地区 | **美国 + 新加坡 + 香港 + 全球远程** | 严格锁这几个，防岗位量爆炸 |
| 3 | 国内/海外隔离 | **全局「求职范围」开关**（国内 / 海外 / 全都要），默认国内 | 老用户零感知；雷达/岗位库**列表**尊重它；**首页计数保持合并总数**（见 §8.3） |
| 4 | 简历匹配 | **可选上传英文简历** + 确定性中英桥兜底 | 精准匹配靠英文简历；不传也有基础匹配 |
| 5 | 香港归属 | **归国内**（大中华区） | `job_scope`：国内=大陆+港澳；净新增海外=美/新/远程 |
| 6 | 签证 sponsorship | **这期做**（JD 关键词识别，零 LLM） | 打「给/不给 sponsorship」标签 |
| 7 | LLM 成本 | **硬约束：可控范围内尽量省** | 爬虫打标签全走确定性规则；不新增任何 per-job LLM |

---

## 2. 术语与口径（先钉死，避免歧义）

### 2.1 `job_scope`（岗位求职范围归属）
- **`domestic`（国内）** = 中国大陆 + 香港 + 澳门（大中华区，= 现有 `is_china_location` 口径去掉台湾）。**现有全部在库岗默认 domestic，不变。**
- **`overseas`（海外）** = 本期净新增的**美国 + 新加坡 + 全球远程**，以及未来扩展的其他境外地区。
- **台湾**：现有爬虫显式拒收，本期**维持不抓**（既不算 domestic 也不主动覆盖），不在范围内。

### 2.2 「求职范围」开关（用户偏好，`user_preferences.job_scope`）
- 取值 `domestic` | `overseas` | `all`，**默认 `domestic`**。
- 驱动全站：今日机会召回 + 岗位库列表 + 首页计数 + 刷新公司库 scope，都按它收窄。
- 与 Jobs 页「地区筛选」正交：开关定大范围，地区筛选在范围内再收窄。

### 2.3 净新增地区（本期真正要放闸的）
香港/澳门现在**已经**作为 domestic 流入（现有适配器保留大中华区）。所以本期真正要放开闸的净新增是：**美国、新加坡、全球远程**。新加坡现在被 `keepForChinaRadar` 过滤掉了 → 本期起归 overseas。

### 2.4 Remote（远程）口径
- location 含明确非大中华国家 token（如 `Remote - US`、`Remote, United States`）→ `country_code` 取该国 → `overseas`。
- location 为裸 `Remote` / 含中国/APAC token → 维持现有「可能在华」判断 → `domestic`（不误判）。
- 真正全球远程（location-agnostic）→ 由 source 的地区配置决定归属；海外源抓到的全球远程岗标 `overseas` Remote。

---

## 3. 上下文与现状（实证摸底，2026-07-02 三路探查 + 分类器审计）

### 3.1 海外岗为什么现在进不来（阻断点）
| 层 | 阻断点 | 文件 |
|---|---|---|
| 爬虫服务端参数 | Amazon `normalized_country_code[]=CHN`、Phenom `?location=China`、Google `?location=China`、Microsoft 14 个写死 CN 城市、Workday facet 锁大中华 | 各 `crawler/adapters/*.py` |
| 爬虫客户端过滤 | `is_china_location()`（normalizer.py:301-314）、`keep_for_china_radar()`（normalizer.py:350-356，含 `OVERSEAS_LOCATION_TOKENS` 剔 `Remote - US` 等） | `crawler/normalizer.py` |
| JS 抓取端过滤 | `keepForChinaRadar()`（`Singapore`/`New York` 返 false） | `lib/live-search.js` |
| 匹配城市别名 | `CITY_ALIASES`（china-keyword-expansion.js:228-270）只有中国城市 + 港/新 2 个；`normalizeChinaCity()` 不认海外城市 | `lib/china-keyword-expansion.js` |
| 打分地点 | 裸子串匹配 `location.includes(loc)`（scoring.ts:101-109），`新加坡` ≠ `Singapore` | `lib/scoring.ts` |
| 雷达地点闸 | `locationState()` 用 `normalizeChinaCity()`，对不上中国城市判 mismatch 剔除 | `lib/opportunities/eligibility.ts:58-67` |

### 3.2 数据模型现状
- `jobs.location` = 单个自由文本列（jobs-db/schema.sql:19），**无国家/是否海外结构化字段**。
- 唯一约束 = `(company, title, location, jd_url)` + `canonical_jd_url` active partial unique index。
- 计数函数 `count_valid_active_jobs()`（active + JD 正文≥60 字）、`active_companies`、`active_job_counts_by_company` 全在 `jobs-db/schema.sql`。

### 3.3 岗位卡标签对英文 JD 的支持度（审计结论，全部确定性规则、可补、零 LLM）
| 标签 | 文件:函数 | 英文支持 | 缺口 |
|---|---|---|---|
| **职能** 研发/产品/设计… | `china-keyword-expansion.js:classifyJobFunction`（607-620）+ `JOB_FUNCTION_RULES`（559-571） | ✅ 好 | Staff/Principal 无 engineer 锚点的落「其他」（可接受，优雅降级） |
| **招聘类型** 校招/社招/实习 | `china-keyword-expansion.js:recruitmentCategory`（500-539）+ `crawler/normalizer.py:extract_job_type`（154-182） | ⚠️ 部分 | 认 intern/new grad/campus URL；**缺** University Graduate / Entry Level / Senior / Staff / 资历词 |
| **教育** 本科/硕士/博士/大专 | `lib/education-rank.js:educationRank`（9-20）+ `crawler/normalizer.py:extract_education`（236-251） | ⚠️ 部分 | 只认 `bachelor/master`；**缺** `Bachelor's / Master's / B.S. / M.S. / B.A. / M.Eng. / Associate` 等真实写法 |
| **经验** 年限 | `china-keyword-expansion.js:_minRequiredExperienceYears`（450-460） | ⚠️ 部分 | 数字年限认（`5+ years`）；**缺** Senior/Staff/Principal/Entry 资历→年限映射 |
| **公司行业** | `lib/company-industry.js` | ✅ 好 | Google/Amazon/Microsoft 等已映射 |

**关键性质：分类器对英文 JD 会「优雅降级」（缺标签或落默认值），不会崩、不会瞎编。** 所以海外岗即便标签不全也是「不够好」而非「脏数据」，可增量迭代。

### 3.4 治理机制可复用性（回答用户「多爬虫治理能复用吗」）
| 机制 | 是否可复用 | 说明 |
|---|---|---|
| JD 正文富化（enrich / enrich-backlog） | ✅ 直接复用 | 外企 JD 正文全家族已打通逐岗 detail（memory 06-10）；按 jd_url 反推 detail 端点，地点无关 |
| 逐岗探活（liveness-sweep） | ✅ 直接复用 | 检测器按适配器挂（workday 404 / greenhouse / lever detail），**不认地点** |
| SPA 浏览器审计（dead-link-audit） | ✅ 直接复用 | google 等 SPA 走浏览器渲染判死，地点无关 |
| 撤岗删除（purge-expired / vacuum） | ✅ 直接复用 | 纯 status 驱动 |
| 质量门 + canonical 去重 | ✅ 直接复用 | jd_url 非空 + HTTP 200 + 页面含标题 + canonical unique |

**结论：治理栈几乎全可复用——它按「源/适配器」挂，不按地点。** 本期治理侧工作 = 把海外源**登记进**现有 sweep/audit 的 workflow 矩阵，而不是重造。

### 3.5 链接可靠性（回答用户「链接是否可靠」）
外企适配器**本来就逐岗产出 jd_url 并过同一道质量门**。放开地区**不碰**链接抽取代码——同一套能可靠产出「在华」workday 链接的逻辑，产出美/新岗链接一样可靠。**唯一要盯**：Workday 单例 `_host` 并发污染坑（曾致跨租户张冠李戴，已修=每源新实例隔离，commit fba4c56）。海外扩源租户更多、并发更高，**Phase 0 必须先回归确认该隔离扛得住**（见 §11 Phase 0）。

---

## 4. 架构与数据流（逐层，带文件触点）

### 4.1 爬虫适配器 —— 从「写死只抓中国」改成「按地区配置抓」
- **source 增加地区配置**：`sources` 表加一列 `regions text[]`（默认 `{CN}`；海外源配 `{US,SG,Remote}` 或 `{US}` 等）。适配器读它决定服务端参数 + 客户端过滤范围。
- **服务端参数参数化**：把写死的 `country_code=CHN` / `?location=China` 换成按 `regions` 生成（Amazon 多国 code、Phenom/Google location 参数、Microsoft 城市集、Workday facet）。
- **客户端过滤改 scope-aware**：`is_china_location()` / `keep_for_china_radar()` → 新增 `location_in_scope(location, regions)`，`regions` 含 overseas 时放行对应地区。**默认 `{CN}` 时行为与今天字节级一致**（回归保护）。
- 触点：`crawler/adapters/{workday,amazon,phenom,microsoft,google,greenhouse,lever,oracle,eightfold,smartrecruiters,ashby,apple}.py` + `crawler/normalizer.py` + `crawler/run.py`（读 source.regions）。

### 4.2 normalizer —— 推导结构化地区字段
- 从 `location` 文本推导 **`country_code`（ISO-2，如 US/SG/CN/HK）** + **`job_scope`（domestic/overseas，按 §2.1）**。
- 扩城市别名表：加海外城市（New York/纽约、San Francisco/旧金山、Seattle/西雅图、Singapore/新加坡、London/伦敦、Sunnyvale、Mountain View、Austin、Boston…）。
- 触点：`crawler/normalizer.py`（新增 `derive_country_code`、`derive_job_scope`）。

### 4.3 schema（香港自建库）—— 加结构化列
- `jobs` 加 `country_code text`、`job_scope text default 'domestic'`（回填存量为 domestic）。
- **首页计数用现有 `count_valid_active_jobs()` 全量（合并总数，不 scope-aware）**——国内+海外都过 JD 正文≥60 字质量门，故合并总数依然诚实。scope-aware 计数**非首页所需**，仅在需要「海外岗有效数」内部核验（如 Phase 1 验收）时按 scope 过滤，不影响首页展示。
- 唯一约束**不动**（仍 company+title+location+jd_url + canonical）——location 已含地区信息，不引入新去重维度。
- 触点：`jobs-db/schema.sql`（改列 + 函数）→ 走 `gh workflow run jobs-db-migrate` 幂等 apply。
- ⚠️ **canonical 三处同步铁律不变**：改任何 canonical/归一逻辑必须 `lib/canonical-url.js` + `crawler/normalizer.py` + `jobs-db/schema.sql` SQL 函数三处字节级一致（本期若不改 canonical 规则则无需动，但加 country_code/job_scope 派生要在 crawler 与 app 写层口径一致）。

### 4.4 匹配引擎 —— 中英桥（确定性，零 LLM）
见 §5 详述。触点：`lib/china-keyword-expansion.js`（CITY_ALIASES / normalizeChinaCity / 中英岗位名技能词典）、`lib/scoring.ts`（地点别名匹配）、`lib/jobs-store/search.ts`（location 归一）。

### 4.5 偏好 / 候选人档案 —— 加范围与地区
- `user_preferences` 加 `job_scope text default 'domestic'`（求职范围开关）+ `target_regions text[]`（国家级海外目标，如 `{US,SG,Remote}`）。
- `candidate_profiles` 加 `target_regions text[]` + **英文侧档案字段**：`en_target_roles text[]`、`en_skills text[]`、`en_target_keywords text[]`、`has_en_resume boolean default false`。
- 触点：`supabase/migrations/`（新迁移，前缀 `ls` 确认未占用）。

### 4.6 简历 —— 可选英文简历（复用现有那一次 LLM 调用）
- 现有简历解析 = 单次 LLM（`lib/resume-extract.js` + `app/api/resume/route.ts`，OCR 已 `chi_sim+eng`）。
- **可选英文简历**：用户在偏好/简历页多传一份英文简历 → 走**同一个** one-shot 解析器（英文输入产出同 schema）→ 结果写入 `en_target_roles/en_skills/en_target_keywords` + `has_en_resume=true`。**不新增任何 per-job LLM；每用户至多多一次用户主动触发的解析调用。**
- 海外范围打分时优先用英文侧档案；国内范围继续用中文档案。
- 不传英文简历者：靠 §5 确定性中英桥得到「够用」的海外匹配。

### 4.7 雷达 / 今日机会 —— scope-aware
- 召回（`lib/opportunities/service.ts`）与地点闸（`lib/opportunities/eligibility.ts:locationState`）按 `user_preferences.job_scope` 放行：
  - `domestic`：与今天完全一致（回归保护）。
  - `overseas`：召回 + 闸门放行 `job_scope='overseas'` 且命中 target_regions 的岗；用英文侧档案匹配。
  - `all`：两者并取。
- 新鲜/探活/STILL_OPEN 信号**不变**——海外岗吃同一套。
- 触点：`lib/opportunities/*`、`app/api/opportunities/route.ts`、`app/api/radar/*`。

### 4.8 UI —— 全局开关 + 地区筛选
- **全局「求职范围」开关**：放 Navbar（或 Today/Jobs 顶部），持久化到 `user_preferences.job_scope`。默认国内。
- **Jobs 筛选器加「地区/国家」筛选**（区别于现有「资方属地」——那是公司国籍，这是岗位所在地）：美国 / 新加坡 / 远程 / 全部海外；国内范围下隐藏或置灰。
- 城市输入框接受海外城市（走扩展后的别名表）。
- **首页计数永远显示合并总数**（国内+海外，`count_valid_active_jobs()` 全量），**不随求职范围开关变化**。因两者都过 ≥60 字质量门，合并总数仍是「真实可投的高质量岗」，不违反指标诚实。
- 触点：`components/Navbar.tsx`、`components/JobFilters.tsx`、`app/today-client.tsx`、`app/jobs/jobs-client.tsx`、首页计数组件。

---

## 5. 中英匹配桥（最关键、且必须零 LLM）

**目标**：中文简历用户在海外范围下能被匹配到相关英文岗（如「算法」→「ML Engineer」），传了英文简历则更精准。

### 5.1 三层桥（全静态词典/正则）
1. **城市别名双向表**：`新加坡↔Singapore`、`纽约↔New York`、`旧金山↔San Francisco/SF`、`西雅图↔Seattle`… 供打分地点匹配 + 城市筛选 + 雷达地点闸复用（一处扩，多处生效）。触点 `CITY_ALIASES`。
2. **岗位名/技能中英对照小词典**（一次性建好的静态表）：`产品经理↔Product Manager/PM`、`算法↔Algorithm/ML/Machine Learning`、`后端↔Backend`、`前端↔Frontend`、`数据↔Data`、`运营↔Operations`… 让中文档案的 target_roles/skills 展开出英文等价词，去命中英文 JD。**这张表可用一次性离线 LLM 生成再固化成静态文件，运行时零 LLM。**
3. **现有中英关键词互通**保留（`jobMatchesChinaKeyword` 已有 工程师↔engineer / 数据↔data 等锚点）。

### 5.2 英文简历路径（可选，精准）
传了英文简历 → `en_*` 字段直接是英文 target_roles/skills → 海外范围打分走英文侧，天然命中英文 JD，精度最高。

### 5.3 打分侧改动
`lib/scoring.ts` 地点匹配从裸子串改为「先过别名归一再匹配」；关键词/技能匹配在海外范围下并入 `en_*` 字段 + 中英对照展开词。exclude_keywords 已支持英文子串，保留。

---

## 6. 岗位卡标签英文化（确定性规则，零 LLM，JS+Python 双side同步）

按 §3.3 审计逐项补，**每处都 JS（读时纯函数）+ Python（爬虫写入）两侧同步 + 补测试**：

| 标签 | 补什么 | 映射规则 |
|---|---|---|
| **招聘类型** | 英文资历/应届信号 | `Intern/Internship`→实习；`New Grad/University Graduate/Graduate Program/Entry Level`→校招；`Senior/Staff/Principal/Lead/年限≥2`→社招；默认社招（信任 adapter 真类型不被正文覆盖，沿用现有分层判定） |
| **教育** | 真实英文写法变体 | `Bachelor's/B.S./B.A./B.Sc./undergrad`→本科；`Master's/M.S./M.Eng./M.Sc.`→硕士；`Ph.D./Doctor of Philosophy`→博士；`Associate degree`→大专 |
| **经验** | 资历词→年限 | `Entry/Junior`→0；`Mid`→3；`Senior`→5；`Staff/Lead`→8；`Principal/Distinguished`→12（数字年限优先，无数字才用资历词兜底） |
| **职能** | 边缘英文岗位名 | 补 `Staff Engineer/TPM/APM` 等到对应桶，或确保优雅降级到「其他」不误分 |

⚠️ 沿用「招聘类型分层判定」记忆：精度优先只认强信号，兜底社招；爬虫端信任 adapter 真类型。

---

## 7. 签证 Sponsorship 标签（这期做，JD 关键词识别，零 LLM）

- 新增字段 `sponsorship_signal text`（`available` | `none` | `unknown`），normalizer 从 JD 文本正则识别：
  - **none（不给）**：`does not sponsor` / `no visa sponsorship` / `must be authorized to work in the US without sponsorship` / `US citizens only` / `security clearance required` / `unable to provide sponsorship`
  - **available（给）**：`visa sponsorship available` / `will sponsor` / `H-1B sponsorship` / `sponsorship provided` / `relocation and visa support`
  - **unknown**：未命中
- 岗位卡渲染标签（如「⚠️ 不给 Sponsorship」/「✅ 提供 Sponsorship」）。
- **默认不硬过滤**（部分用户有身份）；Jobs 筛选可选「只看提供 sponsorship」。
- 触点：`crawler/normalizer.py`（识别写入）+ `jobs-db/schema.sql`（加列）+ 岗位卡组件（渲染）+ 筛选器（可选过滤）+ 测试。

---

## 8. 治理与成本（防岗位量爆炸 + 省 LLM）

### 8.1 地区严格锁 + 抓取分级
- 地区**只放美/新/远程**，不放开全球。
- 海外头部大厂 daily；长尾降频/按需（接现有「更新关注公司」/`/api/refresh`）。
- 海外源登记进 daily-crawl / enrich / liveness-sweep / dead-link-audit 的 workflow 矩阵（§3.4）。

### 8.2 探活一致性坑（必须避免）
- 逐岗 detail 探活地点无关 → 海外岗直接吃到，安全。
- **list-absence 探活（feishu 式）必须地区一致**：若某源 list-crawl 按 `{US}` 抓，其 list-absence 探活也必须按 `{US}` 抓全，否则「本次没抓到」会把在招岗误判死。海外源若用 list-absence，`regions` 配置必须在抓取与探活两端一致。

### 8.3 计数诚实
- 海外岗同过 JD 正文≥60 字质量门。
- **首页计数 = 合并总数**（`count_valid_active_jobs()` 全量，国内+海外，不随开关变）。诚实性由「全部过 ≥60 字质量门」保证，而非靠拆分范围——所有计入的都是真实可投高质量岗。

### 8.4 LLM 预算（硬约束落地）
- 爬虫打标签（职能/招聘类型/教育/经验/城市/sponsorship）**100% 确定性规则，零 LLM**。
- 中英对照词典**离线一次性生成后固化静态文件**，运行时零 LLM。
- 简历解析复用现有单次调用；英文简历 = 用户主动触发的至多一次额外解析。
- 职业洞察（career insights）对海外公司**本期不触发** T2/T3 检索（省搜索额度），维持现状。

---

## 9. 边界与失败预案（Edge & Failure — demo vs 生产分水岭）

| 场景 | 预案 |
|---|---|
| **首次抓取全是「新岗」污染动量** | 海外岗第一次入库 `first_seen` 全是今天，**不得刷爆「新机会/动量」信号** → 首轮批量入库不计入动量（沿用 6/15 库重建污染教训 + `job_events` append-only 口径）。 |
| **英文 JD 与用户关键词零重叠** | 靠职能分类 + 公司行业兜底召回，不硬筛掉；宁可召回多一点交给排序。 |
| **Workday 并发租户污染** | Phase 0 先回归 `_host` 每源新实例隔离（fba4c56）扛不扛得住海外更高并发/更多租户。 |
| **裸 Remote 归属歧义** | 按 §2.4：非大中华国家 token→overseas；裸 Remote/含 APAC→domestic，避免误判。 |
| **英文简历解析质量** | 中文提示词跑英文简历先验证抽取质量；不达标回退纯规则解析（现有 fallback），不硬塞脏档案。 |
| **老用户零感知** | `job_scope` 默认 domestic + 所有 scope-aware 分支在 `{CN}`/domestic 下与今天字节级一致，回归对照必须全绿。 |
| **台湾岗** | 维持不抓，不误入任一范围。 |
| **签证误标** | sponsorship 只在强信号命中时标，默认 unknown，不硬过滤，避免误杀。 |

---

## 10. 分阶段实施（Codex 按序做，Claude 逐阶段验收）

### Phase 0 — 地基与回归护栏（先做，防倒退）
- 加 `sources.regions`、`jobs.country_code/job_scope`、`user_preferences.job_scope/target_regions`、`candidate_profiles` 英文字段 + `target_regions` 迁移；存量回填 domestic。
- normalizer 加 `derive_country_code/derive_job_scope`；`location_in_scope(location, regions)` 默认 `{CN}` 与今天一致。
- **回归对照**：所有 scope-aware 分支在 domestic/`{CN}` 下与改动前字节级一致（快照测试）。
- 回归 Workday `_host` 隔离扛并发（§9）。
- **验收**：默认国内用户看板/计数/匹配零变化；四件套 + canonical 三处一致测试全绿。

### Phase 1 — 放闸抓美/新/远程 + 结构化入库 + 治理登记
- 参数化各外企适配器服务端参数 + 客户端 scope 过滤；给一批**已打通的**外企源配 `regions` 含美/新/远程（先复用现有 ~117 家外企，不新增）。
- country_code/job_scope 入库；海外源登记进 daily-crawl / enrich / liveness-sweep / dead-link-audit 矩阵。
- **验收**（需 live）：海外岗真入库、带 jd_url、点开即达、JD 正文≥60 字；死岗能被探活挤掉；`count_valid_active_jobs('overseas')>0`。

### Phase 2 — 标签英文化 + sponsorship + 中英桥 + 打分
- §6 四类标签英文扩展（JS+Python 双侧 + 测试）；§7 sponsorship；§5 城市别名 + 中英对照词典 + scoring 地点别名匹配。
- **验收**：抽检真实英文 JD，招聘类型/教育/经验/职能标签正确率达标；中文简历用户在海外范围能召回相关英文岗。

### Phase 3 — 求职范围开关 + 地区筛选 UI + 可选英文简历 + 雷达 scope-aware
- 全局开关 + 地区筛选；**首页计数保持合并总数（不 scope-aware）**；可选英文简历上传→`en_*` 档案；雷达/今日机会 scope-aware。
- **验收**：切「海外」后今日机会 + 岗位库出现美/新/远程 F500 岗；传英文简历后海外匹配精度明显提升；切回国内零变化。

### Phase 4（后置，非本期核心）— 定向补 F500 大厂
- 只**定向补缺失的 Fortune 500/1000 大厂**，必须 live 探活确认稳定产出真实岗位才入库（禁猜 slug）。
- 不铺量，接现有源质量验证 harness。

---

## 11. 验收标准（Done，可抽检——Claude 验收清单）

1. **回归**：默认国内用户看板/计数/匹配零变化（Phase 0 快照对照全绿）。
2. **入库**：切「海外」，今日机会 + 岗位库出现美/新/远程的大公司岗，**带 jd_url、HTTP 200 点开即达、JD 正文≥60 字**。
3. **匹配**：中文简历用户在海外范围下能被匹配到相关英文岗（如「算法」→「ML Engineer」）。
4. **英文简历**：传英文简历后海外匹配精度明显提升（en_* 档案生效）。
5. **标签**：抽检真实英文 JD，招聘类型（Intern→实习/New Grad→校招/Senior→社招）、教育（Master's→硕士）、经验、职能标签正确。
6. **sponsorship**：不给 sponsorship 的美国岗被正确标记。
7. **治理**：海外死岗被探活挤掉，不虚高计数；海外源在 sweep/audit 矩阵内真跑。
8. **成本**：全链路无新增 per-job LLM（代码审查确认）。
9. **回归四件套 + canonical 三处一致测试全绿**。

---

## 12. 约束与红线（Constraints — 不可违反）

- **零新增 per-job LLM**；打标签全确定性规则；中英词典离线固化。
- **canonical 三处同步**（lib/canonical-url.js + crawler/normalizer.py + jobs-db/schema.sql）字节级一致；改列/派生口径 crawler 与 app 写层一致。
- **schema 改动走 `jobs-db/schema.sql` + `gh workflow run jobs-db-migrate`**；Supabase 迁移走 `supabase/migrations/`（前缀 `ls` 确认未占用，seed 类带 `_seed_`）。
- **jd_url 准确性高于一切**；拿不到稳定详情链接只记 `partial_success`。
- **默认 domestic 行为字节级不变**（老用户零感知，回归护栏）。
- **不碰密钥**（.env* / service_role / JOBS_DATABASE_URL 值不读不打印）；沙箱 live 验证走 `dangerouslyDisableSandbox + source .env.local`，DDL 写走 jobs-db-migrate。
- **最小化改动**，不做无关重构/格式化；改一处必同步描述它的所有项目文件（CLAUDE.md/目录结构/测试/canonical/schema）。
- worktree 隔离：改动在草稿分支自动 commit，**push 等用户明确指令**。

---

## 13. 测试要求

- 纯函数优先：`location_in_scope` / `derive_country_code` / `derive_job_scope` / 城市别名双向 / 中英对照展开 / 招聘类型·教育·经验英文映射 / sponsorship 识别 / scope-aware 计数。
- crawler 用 unittest，单测不打真实网络（mock）。
- **domestic 快照回归**：改动前后 `{CN}` 路径输出字节级一致。
- canonical 双侧测试（tests/canonical-url.test.js + crawler/test_canonical.py）若涉及归一改动必同步。
- JS 与 Python 双侧分类器测试各补英文用例（真实 JD 变体，非仅 base form）。

---

## 14. 交给 Codex 的执行须知

- 按 Phase 0→4 顺序做，每个 Phase 收口跑该 Phase 验收 + 回归四件套，本地 commit（不 push）。
- 每个 Phase 结束在本文档 §15「实施记录」追加：改了什么、跑了哪些验证、结果、剩余风险。
- 遇到 §12 红线冲突或需 live/密钥的步骤，停下报告，不猜不硬推。
- Claude 逐 Phase 验收（对照 §11），不通过打回。

## 15. 实施记录（Codex 回填）

_（待实施）_
