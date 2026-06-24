> ⚠️ **已被取代（2026-06-24）**：本文为早期三模式版，已被 `03-产品规格v3.md` 取代（见 `README.md`）。仅作背景参考。

# 个人机会时效雷达 Product Spec

> 日期：2026-06-24
> 状态：新版产品规格，供实现 agent 直接执行
> 对应战略文档：`docs/opportunity-timing-radar-specs/产品转型方案-个人机会时效雷达.md`
> 技术规格：`docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-technical-spec.md`
> 验收规格：`docs/opportunity-timing-radar-specs/2026-06-24-opportunity-timing-radar-acceptance-spec.md`

---

## 0. 执行摘要

本次转型要把产品从“用户找岗位 / 用户触发爬取”改成“系统持续监控机会变化，并交付低噪音行动队列”。

核心定位：

> **当与你有关的求职机会发生时效变化时，职达告诉你：发生了什么、为什么与你有关、为什么现在值得行动。**

V1 用户侧只展示五类信号：

1. 新机会；
2. 最近确认仍在招；
3. 截止临近；
4. 招聘动量；
5. 关闭 / 陈旧。

V1 不展示岗位内容变更，不承诺重新开放，不承诺全网最早，不承诺竞品没有。

---

## 1. 产品目标

### 1.1 用户目标

用户要完成的任务不是“搜索更多岗位”，而是：

- 快速知道今天有没有值得处理的新机会；
- 避免把时间浪费在失效岗位上；
- 不错过校招、实习、关注公司和高匹配岗位；
- 能理解系统为什么推荐；
- 能通过反馈减少下次噪音。

### 1.2 产品目标

产品要完成：

- 将官方岗位库转化为个人机会队列；
- 将 `first_seen_at / last_seen_at / status / deadline` 等技术字段转化为用户能理解的时效信号；
- 将不同求职状态抽象成三种模式，而不是三套产品；
- 将动作反馈变成下一次推荐的输入；
- 降低主动爬取、source、workflow 等技术概念在普通用户侧的存在感。

### 1.3 不做什么

本轮不做：

- 自动投递；
- 简历润色；
- AI 聊天求职顾问；
- HR 直聊；
- 竞品平台覆盖对比；
- 社交关系推荐；
- 岗位内容变更提示；
- 重新开放提示；
- 年度招聘趋势；
- 新 crawler adapter 扩张。

---

## 2. 用户模式

用户首次进入或在偏好页必须选择一个模式。模式不是标签，而是影响 feed 阈值、提醒频率、UI 文案和排序权重的核心输入。

### 2.1 模式枚举

```ts
type RadarMode = "sprint" | "watch" | "campus";
```

### 2.2 冲刺找工作 `sprint`

适用用户：

- 正在积极投递；
- 每天愿意处理机会；
- 对高匹配和仍有效敏感；
- 希望减少筛选劳动。

默认设置：

- `daily_limit`: 15；
- feed 每天可生成；
- email 默认关闭，用户可开；
- 优先展示新机会、高匹配、截止临近；
- 允许少量拓展机会；
- aging 仅在 verified 候选不足时展示。

画像完整度：

```text
profile_ready =
  (target_roles OR target_keywords OR target_companies)
  AND target_locations
```

核心文案：

- 标题：`今天优先处理这些机会`
- 空状态：`今天没有新的高可信机会。我们会继续检查你关注的方向。`
- CTA：`打开官网投递`

### 2.3 长期机会观察 `watch`

适用用户：

- 当前不急着跳槽；
- 想观察目标公司或方向；
- 不希望每天被打扰；
- 只想看高价值变化。

默认设置：

- `daily_limit`: 8；
- 默认摘要频率为 weekly，用户可改 weekdays；
- feed 更严格，默认不展示普通 related；
- 重点展示关注公司、新机会、招聘动量、关闭/陈旧；
- 不展示 aging 机会，除非它是用户已保存/关注的岗位。

画像完整度：

```text
profile_ready =
  target_companies
  OR target_roles
  OR target_keywords
```

目标城市不是硬门；缺失城市时，城市相关原因不展示，岗位卡片标记 `城市未限定`。

核心文案：

- 标题：`你的机会观察`
- 空状态：`暂时没有值得打扰你的变化。`
- CTA：`加入值得投`

### 2.4 校招 / 实习窗口 `campus`

适用用户：

- 找校招或实习；
- 对截止日期和批次开放敏感；
- 关注公司、城市、岗位方向；
- 需要避免错过窗口。

默认设置：

- `daily_limit`: 20；
- 默认工作日提醒；
- 阶段硬门优先；
- 截止临近权重最高；
- 招聘动量以“批次新开 / 公司集中开放”为主要表达；
- 城市可作为硬门，但允许“全国 / 多地 / 远程”通过。

画像完整度：

```text
profile_ready =
  experience_stage in ("校招", "实习")
  AND (target_roles OR target_keywords OR target_companies)
```

核心文案：

- 标题：`别错过这些窗口期`
- 空状态：`当前没有新的校招/实习窗口。你可以补充目标公司，我们会持续看官网。`
- CTA：`查看官网截止时间`

---

## 3. 五类用户侧信号

所有 feed 卡片必须至少命中一个 `signal_type`。不能只因为“匹配分高”就进入“今日机会”。

### 3.0 阈值总表

本表是产品侧唯一阈值总览。实现时以 technical spec 中的公式为准，但不得偏离本表的用户语义。

| 信号 | sprint | watch | campus | 必要证据 | 不满足时 |
|---|---:|---:|---:|---|---|
| `NEW_MATCH` | score >=45，`first_seen_at > novelty_since` | score >=70 或关注公司命中，`first_seen_at > novelty_since` | score >=45，`first_seen_at > novelty_since` | active、summary 有效、freshness verified、通过硬门 | 不展示为新机会 |
| `STILL_OPEN_PRIORITY` | score >=70，非新机会 | score >=85 或关注公司命中，非新机会 | score >=65，非新机会 | active、freshness verified、source metadata 可用 | 不写“最近确认仍在招” |
| `DEADLINE_SOON` | 截止 <=7 天 | 截止 <=7 天，仅 saved 或关注公司 | 截止 <=14 天 | deadline 可解析为日期，active，freshness verified/aging | 不显示截止标签 |
| `COMPANY_MOMENTUM` | 近14天 >=3 且比前14天 +2，或前14天 <3 且近14天 >=5 | 仅关注公司或高匹配公司，其他同 sprint | 同 sprint，优先校招/实习阶段 | 代表岗位 >=2，verified 比例 >=50%，7天内未重复提醒 | 不展示动量 |
| `CLOSED_OR_STALE` | saved/viewed/已提醒岗位 status 异常或 stale | saved/关注公司 status 异常或 stale | saved/校招窗口岗位 status 异常或 stale | status in expired/removed/error 或 freshness stale | 不进入主推荐，只作为状态提示 |

全局规则：

- `unknown` freshness 不得触发 `NEW_MATCH`、`STILL_OPEN_PRIORITY` 或 `DEADLINE_SOON`；
- `aging` 只允许进入 `DEADLINE_SOON` 或“等待再次确认”，不得伪装成最近确认；
- `content_hash` 变化不产生用户侧 signal；
- `score` 只用于排序和阈值，不向用户展示数字；
- signal 不足时宁可少展示，不用无关岗位补齐 daily_limit。

### 3.1 `NEW_MATCH` 新机会

用户问题：

> 有什么刚出现、适合我、值得今天看的岗位？

触发条件：

- job `status='active'`；
- summary 有效；
- freshness 为 `verified`；
- 通过用户模式对应硬门；
- `first_seen_at > novelty_since`；
- sprint/campus: score >= 45；
- watch: score >= 70，或命中 target company。

用户文案：

- `新发现`
- `今天首次发现`
- `自你上次查看后新增`

禁止文案：

- `全网首发`
- `最早发现`
- `BOSS 没有`

### 3.2 `STILL_OPEN_PRIORITY` 最近确认仍在招

用户问题：

> 哪些高匹配岗位最近被官方源确认还有效？

触发条件：

- job `status='active'`；
- freshness 为 `verified`；
- 不是 `NEW_MATCH`；
- score >= 70；
- 用户未 saved / ignored / applied；
- sprint/campus 展示；
- watch 仅展示 target company 命中或 score >= 85。

用户文案：

- `最近确认仍在招`
- `官方源最近确认`
- `高匹配，仍有效`

说明：

- 这里的“仍在招”只能代表系统最近在官方源或 ATS 发现该岗位仍处于 active 列表，不代表投递一定成功；
- 如果 source metadata 缺失，不能展示此信号。

### 3.3 `DEADLINE_SOON` 截止临近

用户问题：

> 哪些机会快来不及了？

触发条件：

- `deadline` 可以解析成明确日期；
- 解析日期 >= 今天；
- sprint/watch: 距离截止 <= 7 天；
- campus: 距离截止 <= 14 天；
- job active；
- 通过硬门；
- freshness 为 `verified` 或 `aging`。

排序：

- deadline 越近越靠前；
- 已过期不展示为 opportunity，改为 closed/stale；
- campus 模式中，`DEADLINE_SOON` 优先级高于普通 `STILL_OPEN_PRIORITY`。

用户文案：

- `7天内截止`
- `本周截止`
- `校招窗口临近`
- `请以官网截止时间为准`

禁止文案：

- 不得在无法解析日期时展示“快截止”；
- 不得从岗位标题臆测截止时间。

### 3.4 `COMPANY_MOMENTUM` 招聘动量

用户问题：

> 哪些我关注的公司或方向最近明显在招？

触发对象：

- 公司级，不是单岗位级；
- 可关联 1–5 个代表岗位；
- 优先 target companies，其次用户目标方向中高匹配公司。

V1 触发条件：

- 近 14 天该公司 active 新发现岗位数 >= 3；
- 且近 14 天数量 >= 前 14 天数量 + 2，或前 14 天不足 3 但近 14 天达到 5；
- 代表岗位至少 2 个通过用户硬门；
- source freshness 分布中 verified 比例 >= 50%；
- 同一公司同一用户 7 天内最多展示一次 momentum。

用户文案：

- `这家公司最近在集中开放机会`
- `近两周新增多个与你相关的岗位`
- `据本平台已覆盖官方源观察`

必须带限定：

- `据本平台已覆盖官方源`
- `近两周`
- `与你相关`

禁止文案：

- `公司今年扩招`
- `招聘大年`
- `HC 暴涨`
- `官方宣布扩招`

### 3.5 `CLOSED_OR_STALE` 关闭 / 陈旧

用户问题：

> 我之前看过、保存或关注的机会是否已经不值得继续投？

触发条件：

- 用户 saved / viewed / target company 命中过；
- job `status in ('expired', 'removed', 'error')`；
- 或 active 但 freshness 为 `stale`；
- 不进入普通推荐区，进入“需要确认的关注机会”或 saved/applied 辅助提示。

用户文案：

- `可能已关闭`
- `长时间未确认仍在招`
- `建议以官网状态为准`
- `可以从值得投中移除`

禁止文案：

- `公司拒绝你`
- `岗位一定失效`
- `已招满`

---

## 4. 明确不展示的信号

### 4.1 `JOB_CONTENT_CHANGED_INTERNAL`

内容 hash 变化只能作为后台事实，不进入用户卡片。

后台可记录：

- `old_content_hash`
- `new_content_hash`
- `observed_at`
- `source_id`
- `changed_fields`，初期为空数组

前台不展示：

- `岗位内容更新`
- `JD 有变化`
- `要求变了`
- `薪资变了`

除非未来能做字段级结构化 diff，并通过误报评估。

### 4.2 `REOPENED`

重新开放不进入 V1。

原因：

- 当前 `expired` sticky 语义会避免列表重爬复活 detail 探活确认撤岗的岗位；
- `removed` 可以复活，但没有事件历史时无法可靠区分“漏抓恢复”和“真实重新开放”；
- 用户侧误报成本高。

---

## 5. 页面与信息架构

### 5.1 主导航

顺序：

1. 今日机会 `/today`
2. 搜索岗位 `/jobs`
3. 关注与偏好 `/preferences`
4. 值得投 `/saved`
5. 已投递 `/applied`

处理：

- `/today` 是登录后默认首页；
- `/jobs` 是探索工具，不是主产品；
- `/path` 从一级导航移除，保留路由；
- `/me` 放入账号区域；
- `/sources`、`/admin/health`、`/admin/insights` 只给管理员入口。

### 5.2 Landing `/`

目标：

- 解释产品不是岗位搜索，而是机会时效雷达；
- 引导用户设置模式和目标；
- 不讲 crawler、workflow、source 技术细节。

首屏文案：

```text
别每天刷岗位了。
职达替你看企业官网，只提醒真实、对口、仍有效、现在值得处理的机会。
```

三张价值卡：

1. `新机会`：自你上次查看后新增；
2. `仍在招`：最近从官方源确认；
3. `快截止`：校招、实习和目标岗位不要错过窗口。

证据文案：

```text
每个机会都给出官方链接、最近确认时间和推荐原因。
```

禁止：

- 展示 crawler 数量作为主卖点；
- 展示“全网最全”；
- 展示“自动投递”；
- 展示“岗位变更监控”。

### 5.3 Onboarding

首次登录后，如果没有模式或画像不完整，进入 onboarding。

步骤：

1. 选择模式；
2. 选择目标岗位 / 关键词 / 关注公司；
3. 选择城市或城市偏好；
4. 选择阶段和学历；
5. 可选上传简历补全技能；
6. 进入今日机会。

每一步都可保存草稿，但未达到 `profile_ready` 前不展示随机岗位。

### 5.4 今日机会 `/today`

统一结构：

```text
Header
  模式名 + 今日摘要 + 最近生成时间

信号摘要条
  新机会 N / 仍在招 N / 快截止 N / 动量 N / 需要确认 N

主要分区
  根据 mode 重排

机会卡片
  信号标签
  推荐原因
  最近确认时间
  官方链接
  处理动作
```

#### sprint 分区

1. `新出现的对口机会`
2. `今天优先处理`
3. `即将截止`
4. `拓展看看`
5. `等待再次确认`

#### watch 分区

1. `关注公司变化`
2. `少量高价值新机会`
3. `本周招聘动量`
4. `你保存的机会状态变化`

#### campus 分区

1. `新开的校招/实习窗口`
2. `即将截止`
3. `高匹配岗位`
4. `关注公司批次变化`

### 5.5 机会卡片

每张卡必须包含：

- 公司；
- 岗位；
- 城市；
- 阶段；
- 官方链接；
- 信号标签；
- 最近确认时间；
- 2–4 条推荐原因；
- CTA；
- 负反馈入口。

标签优先级：

1. `快截止`
2. `新发现`
3. `关注公司`
4. `最近确认仍在招`
5. `招聘动量`
6. `等待再次确认`

推荐原因示例：

- `方向匹配：产品经理`
- `目标城市：上海`
- `你关注的公司：字节跳动`
- `校招岗位`
- `技能匹配：SQL、数据分析`
- `官方源最近确认仍在招`

不要展示：

- 内部 score 数字；
- 权重；
- source id；
- crawler method；
- content hash；
- workflow run id。

### 5.6 关注与偏好 `/preferences`

必须包含：

- 当前模式；
- 目标岗位；
- 目标关键词；
- 排除词；
- 目标城市；
- 关注公司；
- 行业；
- 阶段；
- 学历；
- 每日机会上限；
- 通知设置；
- 关注公司覆盖状态。

关注公司状态：

| 状态 | 文案 | 用户可做 |
|---|---|---|
| `covered` | `已覆盖官网岗位` | 正常观察 |
| `queued` | `已加入接入队列` | 等待 |
| `researching` | `正在确认官方源` | 等待 |
| `unsupported` | `暂不支持自动覆盖` | 可删除或保留 |

不展示：

- crawler 运行按钮；
- source adapter；
- discovery run；
- 搜索引擎调用；
- jobs_created 数。

### 5.7 搜索岗位 `/jobs`

角色：

- 主动探索全库；
- 支持用户搜索、筛选、保存；
- 不承担“今日机会”的主叙事。

处理：

- 普通用户默认隐藏主动刷新；
- 可保留管理员或 feature flag 入口；
- 岗位卡片继续显示官方链接和新鲜度；
- 搜索结果不能反向污染 Today 排序，除非用户有显式动作。

### 5.8 值得投 `/saved`

角色：

- 已保存机会的工作台；
- 显示状态变化和陈旧提醒；
- 引导用户标记已投递或移除。

卡片新增：

- `最近确认仍在招`；
- `可能已关闭`；
- `长时间未确认`；
- `截止临近`。

### 5.9 已投递 `/applied`

角色：

- 用户投递记录；
- 不自动判断投递成功；
- 岗位下线后仍保留 snapshot。

---

## 6. 用户动作与反馈

### 6.1 主动作

每个岗位同一时间最多一个主动作：

- `saved`：值得投；
- `ignored`：不合适；
- `applied`：已投递。

辅助动作：

- `viewed`：看过；
- `opened_official`：打开官网链接，建议用 events 记录，不必作为 job_actions 主动作。

### 6.2 忽略原因

忽略必须要求选择原因：

```text
role_mismatch
location_mismatch
industry_mismatch
seniority_mismatch
education_mismatch
compensation_mismatch
company_not_interested
already_seen_elsewhere
not_job_seeking
other
```

产品文案：

- `方向不对`
- `城市不合适`
- `行业不想去`
- `年限不合适`
- `学历/阶段不合适`
- `薪资不合适`
- `不想看这家公司`
- `别处看过了`
- `暂时不找工作`
- `其他`

反馈原则：

- 单次反馈不自动改用户偏好；
- 连续反馈可在偏好页提示用户是否调整；
- 负反馈用于指标和后续降噪。

---

## 7. 通知与摘要

### 7.1 默认策略

- 邮件摘要默认关闭；
- 用户主动开启；
- sprint 默认 daily；
- watch 默认 weekly；
- campus 默认 weekdays；
- 用户可随时关闭。

### 7.2 摘要内容

摘要只包含：

- 新机会；
- 快截止；
- 关注公司动量；
- saved 机会关闭/陈旧。

不发送：

- 普通 related；
- aging；
- 未经验证 still-open；
- 内容变更。

### 7.3 防打扰规则

- 同一岗位同一用户 7 天内不重复提醒，除非 signal_type 从普通变成 deadline；
- 同一公司 momentum 7 天内最多一次；
- 用户 ignored 后不再提醒同岗位；
- 用户 applied 后不再提醒同岗位；
- 用户 watch 模式中，低于高匹配阈值不提醒。

---

## 8. 指标与埋点

### 8.1 必须记录的事件

```text
radar_onboarding_required
radar_mode_selected
radar_profile_saved
radar_feed_generated
radar_feed_opened
opportunity_card_viewed
opportunity_official_opened
opportunity_saved
opportunity_ignored
opportunity_applied
opportunity_undo
digest_enabled
digest_disabled
digest_sent
digest_opened
company_watch_requested
company_watch_status_changed
```

### 8.2 禁止记录的 payload

不得在 events payload 中写入：

- 用户邮箱；
- 简历原文；
- 手机号；
- 身份证；
- 自由文本 reason_text；
- 完整 JD 正文；
- 完整官方 URL query 中可能包含的 token。

允许记录：

- `mode`
- `signal_type`
- `job_id`
- `company_hash` 或标准公司名，按当前项目隐私约定选择；
- `score_tier`
- `freshness`
- `section`
- `reason_code`
- `daily_limit`
- `profile_ready_missing_fields`

### 8.3 产品漏斗

核心漏斗：

```text
profile_ready
→ feed_generated
→ feed_opened
→ card_viewed
→ official_opened / saved / ignored / applied
```

北极星：

```text
weekly_processed_valid_opportunities_per_active_user
```

---

## 9. 空状态与降级

### 9.1 未登录

跳转登录：

```text
/login?next=/today
```

### 9.2 未完成画像

不展示随机岗位。

文案：

```text
先告诉我们你想找什么。
设置目标岗位、公司或城市后，系统会每天从企业官网中筛出值得处理的机会。
```

### 9.3 没有机会

根据模式展示：

- sprint：`今天没有新的高可信机会。你可以放宽城市或补充目标公司。`
- watch：`暂时没有值得打扰你的变化。`
- campus：`当前没有新的校招/实习窗口。我们会继续关注截止和批次开放。`

### 9.4 数据源异常

如果 source metadata 查询失败：

- 不展示 `最近确认仍在招`；
- 可展示普通搜索结果；
- Today 返回可解释降级；
- 记录服务端 warning；
- 前台提示 `部分来源状态暂时无法确认`。

### 9.5 Feed 不足

宁可少展示，不填充无关岗位。

如果不足 daily_limit：

- 展示实际数量；
- 给出可操作建议：补充公司、放宽城市、上传简历；
- 不使用“最新 active 岗位”盲兜底。

---

## 10. 验收口径

产品验收必须证明：

1. 三种模式都能保存并影响 feed；
2. 每张 Today 卡片至少有一个 signal_type；
3. 不能展示岗位内容变更；
4. 主动爬取普通入口已降级；
5. ignored 必须收集 reason_code；
6. saved/applied/ignored 不会重复出现在 Today 主队列；
7. deadline 只在可解析日期时触发；
8. momentum 有样本门槛；
9. source freshness 无法确认时不伪装成 verified；
10. 空状态不展示随机岗位。
