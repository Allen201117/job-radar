# 主线 B：召回覆盖 — 完整审阅发现（findings-B）

测量时间：2026-08-26 17:38（基线）/ 2026-08-27 10:12（B1 主实验快照）。画像匿名为 A–G，映射只存 scratchpad/agent-b/selected-uids.json（不入报告、不入 git）。原始数据与脚本：scratchpad/agent-b/（driver.sql、eval.js、result-*.json、theo-*.ndjson、bench-b3*.log、driver.log）。

## 摘要

1. **B1 召回率：7 个真实画像，微平均 10.8%（1,443/13,317），逐画像 2.6%–40.9%**。JS 匹配门认定「该推给用户」的岗里约 89% 从未进入引擎，且 feed 永远显示满 20 张卡，漏报完全不可见。
2. 漏因分解（13,317 理论应召回）：73.0% budget_order（SQL 候选宇宙内但 900 名额竞争落选）；14.3% 结构漏（三层 tsquery 都够不着，search_doc 不含正文）；1.9% 校招/实习 LIKE 预筛误杀（「-27届」不含"校招"字样）；10.8% 被召回。
3. 用户可感知伤害：每人"最好的 20 个岗"平均只有 13 个被召回（最差 5/20、8/20）——漏的包括 score 93 的字节「AI产品经理」（用户目标岗位原词）。7/7 画像的"单个最高分岗"全部被召回。
4. **B3 证伪"预算贵"**：DB 执行时间对 budget 平坦（最重画像 900→3600 只 +3%，3.09s→3.18s），成本只在传输（~1.37KB/行线性）与 JS。900→1800 边际成本估 +0.3~0.8s 端到端；但纯加预算只能翻倍召回率，治不了根（宇宙 4k–66k 行，按"最新"排序取 K 是抽签）。
5. **真病根是排序**：三层内部按 城市命中→最新 排序，与"能否过 JS 门"无关 → 900 名额平均只有 23% 换来可展示岗（最差 2.1%）。company 层存活 1.3–12.9%（companyHit 不豁免 role 门，eligibility.ts:217/:231-234）、cityNew 层 0–9.3%；层间重复浪费 0–21%；scope=all 用户 cityFirst 把海外可投岗沉底（画像E 漏 92.8%）。
6. **B4 有便宜路径**：正文 FTS 不需三处同步（tokenizer `search_tokens` 已活在 DB，加 `summary_doc tsvector` 列+触发器即可）；job_function/城市/阶段物化列走「CI 夜间 Node 回填」单写入端，避开三端移植词库。
7. **B5**：召回窗口 top-20 公司占 26.5%（字节 7.8%）；过门集合集中度与理论集同构（字节多=供给事实）。展示层已有软 cap（grouping.ts:119-135）。建议暂不加召回层硬 cap。
8. 基线复核：§3 全部对上（active 380,595 精确一致）。新口径：900 的真实分母是 26.3 万（7 天窗+正文≥60 字），900 = 0.34%。

## 0. 基线复核（2026-08-26 17:38，单 psql 会话）

| 指标 | 任务书 §3 | 实测 | 口径 |
|---|---|---|---|
| active | 380,595 | 380,595（精确一致） | 裸 count(status='active') |
| 有效在招 | 373,117 | 373,454 | count_valid_active_jobs() |
| never-checked | 77,633 | 77,289 | active 且 enrich_checked_at is null |
| 近 7 天新增 | 28,643 | 28,614 | active 且 first_seen_at≥now()-7d |
| 公司数 | 1,162 | 1,162（精确一致） | count(distinct company) |
| 召回窗口行数 | —（新增） | 263,166 | active + last_seen_at≥7d + summary≥60 |

## 1. 方法与口径

- 39 个真实 user_preferences 选 7 个（A–G），覆盖 无阶段/校招/实习/社招 × 各行业 × 有无城市/公司/关键词 × domestic/all，全部经真实 buildRadarProfile 合成零手改。
  - A：AI 产品，2 roles+6 kw，沪深杭，2 公司，无阶段 / B：AI 产品校招，5 roles+23 黑话 kw，硕士 / C：天线射频硬件校招，珠三角 / D：数分/游戏PM 实习，6 城 / E：销售采购社招，成都，scope=all / F：材料化工校招，无城市（唯一单层） / G：数据中台校招，北京，13 家目标公司，排除「工程师/产品经理/算法」
- 同快照：一个 REPEATABLE READ READ ONLY 事务内完成 7 份真实 buildRecallSql(900) → 7 份全窗口三层 tsquery 成员标记 → 全窗口 263,867 行 dump（按 uuid 分 8 片多 statement 同事务）。driver.log 0 error。
- 理论集：离线对全窗口逐行跑真实 computeMatchFacts+checkEligibility+scoreOpportunity（tests/_load-ts.js 转译，业务代码零改动）；sourceMeta 用 Supabase sources 1,444 行；排除词与 stage-1 同一条 LIKE；actioned 两侧一致；freshness now=snap_now。
- 诚实边界：summary 均为 left(btrim,300)——与线上 stage-2 同口径，故测的是「stage-1 相对 stage-2 的漏」；按完整正文算理论集只会更大，**漏报率是下界**。SINCE 宽 0.7 天的行被 freshness 判 stale 不进理论集。

## 2. B1 逐画像召回率

| 画像 | 理论应召回 | 可展示 | 召回900中过门 | 召回率 | top-20 命中 | top-50 | 最高分岗召回 |
|---|---|---|---|---|---|---|---|
| A | 2,273 | 2,249 | 60 | 2.6% | 11/20 | 11/50 | ✅(90) |
| B | 273 | 273 | 19 | 7.0% | 5/20 | 7/50 | ✅(100) |
| C | 944 | 944 | 181 | 19.2% | 20/20 | 45/50 | ✅(87) |
| D | 508 | 508 | 208 | 40.9% | 16/20 | 27/50 | ✅(88) |
| E | 3,736 | 3,312 | 268 | 7.2% | 8/20 | 22/50 | ✅(72) |
| F | 5,086 | 5,086 | 546 | 10.7% | 19/20 | 46/50 | ✅(70) |
| G | 497 | 497 | 161 | 32.4% | 13/20 | 38/50 | ✅(93) |
| 合计/微平均 | 13,317 | 12,869 | 1,443 | **10.8%** | 平均13.1/20 | | 7/7 |

被漏的具体岗（全 roleTier=exact、budget_order）：B 漏 score 93 字节「AI产品经理（内容安全/商业化系统方向）」；G 漏 score 90 美团「视觉生成基座研究员」、小红书「大语言模型基础技术研究员」；A 漏 score 80 字节「大模型产品经理」；D 漏 score 81 网易「安全策略交付实习生」（结构漏）。
为什么用户感觉不到：grouping.ts main 区封顶 dailyLimit(20)，7 画像过门岗都 ≥19 → feed 张张填满，candidate_capped 只是布尔值，漏报零外显。

## 3. 漏因归因（同快照三层成员标记）

| 漏因 | 数量 | 占理论集 |
|---|---|---|
| budget_order（宇宙内 900 名额落选） | 9,718 | 73.0% |
| tsquery_structural（search_doc 只索引 标题/公司/城市/类型，schema.sql:186-189；方向词只在正文的岗 SQL 不可见，opportunities.ts:176-179 自承） | 1,906 | 14.3% |
| stage_prefilter（校招 pattern=校招/校园/应届/campus/graduate，opportunities.ts:123-129，不含「届」：C 被杀 92、F 148） | 250 | 1.9% |
| 已召回 | 1,443 | 10.8% |

SQL 候选宇宙：A 65,946 / B 25,226 / C 13,317 / D 3,968 / E 25,683 / F 13,302 / G 7,227。召回率与 900/宇宙 强相关——召回本质是「宇宙里按时间抽签」。

## 4. B2 三层加权轮转

机制正常（正面）：名额转移真实生效（单层画像 900/900、两层 850 无饿死）；权重比兑现（~450/180/270）。
三个实测缺陷：
1. 层内排序与过门无关 → 900 名额平均 23% 换来过门岗（A 6.7%、B 2.1%、F 60.7%）。company 层存活 1.3–12.9%（companyHit 不豁免 role 门，SQL company 层却召任意职能）；cityNew 层 0–9.3%（设计说它是正文方向岗的唯一通道，实测产出接近零）。
2. union all 层间重复不去重，浪费 0–21% 名额。
3. cityFirst 对 scope=all 反向优化：海外岗永落"其余"桶。画像E 理论 top=Salesforce 215/Bayer 156/Abbott 131，召回前排=国内噪声，漏 92.8%。

## 5. B3 预算瓶颈（EXPLAIN ANALYZE + payload）

budget 900/1800/3600 各 3 遍取中位（热态）：B（最重）3.09/3.13/3.17s（4×+2.7%）；G 1.59/1.62/1.66s；D 0.476/0.485/0.499s。payload ~1.37KB/行严格线性（900 行 1,237KB）。
结论：DB 成本与 budget 无关（GIN 扫全命中行+top-N 排序，900 与 3600 一样贵）；DB 变量是画像 tsquery 重量（0.48–3.1s）。边际成本=传输+node-pg+JS：按线上埋点折算 1800 约 +0.3~0.8s、3600 约 +1.2~2.5s。纯加预算治标：A 宇宙 66k，3600 也只 ~10%。次要：最重画像排序 spill 磁盘（work_mem=8MB）。

## 6. B4 物化/下推方案（不拍板）

结构性前提：search_doc 只含 title/company/location/job_type（schema.sql:182-197）；JS exact 档 haystack 含 summary+salary_text（china-keyword-expansion.js:769-775）→ stage-1 原理上不可能是 stage-2 超集。

**P1（本周，只改 opportunities.ts）**：① 校招预筛补 `%届%`（找回 250/7画像）② company/cityNew 层内 roleRef 命中优先排序（纯排序零漏报风险）③ scope≠domestic 桶序改「region 命中→城市→其余」④ budget 900→1800。预期微平均 10.8%→25-35%，top-20 命中 13→16-18/20。
**P2（两周，一次迁移无三处同步）**：`summary_doc tsvector` 列+触发器 `to_tsvector('simple', search_tokens(left(summary,1000)))`+GIN。tokenizer 已活在 DB，单一 SQL 函数，两写入端零改动。GIN 估 200-500MB（盘富余）；回填分批+statement_timeout 1800s（迁移 144 教训）；bigram AND 是子串命中超集，语义安全；注意 daily-crawl upsert 变慢观察。
**P3（架构决策档）**：物化 job_function/recruitment_category/city_norm 建索引真正下推硬门。三分类器只活在 JS（922 行词库）——**不建议三端移植**（canonical 三处同步的十倍体量）；推荐「CI 夜间 Node 单写入端回填」：列 nullable、SQL 对 NULL 放行（superset-safe）、词库改版刷 NULL 重算；CLAUDE.md 须写明 upsert 不得覆写这三列（复用 _PRESERVE_IF_EMPTY）。被否：ts_rank（07-31 实测 3.9s）、向量检索（重依赖不对症）。

必须保留（复核过勿回退）：排除词留 SQL；SUMMARY_TRUNC≥200（eligibility.ts:182）；jd_url 不砍出 RECALL_COLUMNS；单连接单往返。

**顺带发现（进「问错的问题」）**：SUMMARY_TRUNC=300 使 today 路径 keywordMatchTier 永远只见正文前 300 字（p50 正文 390 字）——关键词在 300 字后的岗召回了也判不中方向。量级未测（未验证假设）。

## 7. B5 公司多样性

窗口 1,087 家、top-20 占 26.5%、字节 7.8%。raw 召回 top-1 公司 7–35%。但过门集合集中度与理论集同构（D 理论字节 62% vs 过门 64%）= 供给侧事实非算法偏爱。展示层已有软 cap（takeWithCompanyDiversity，perCompanyCap=max(2,30%×limit)）。建议暂不加召回层硬 cap：feed 已兜、名额效率才是矛盾、partition 开窗有性能风险。若 P1 后 top-1 仍 >50% 再评估排序式软 cap。

## 8. 证伪 & 未验证

证伪：① "900 瓶颈是 2vCPU/SQL"→DB 时间平坦 ② "轮转层饿死/转移失效"→机制正确 ③ "大厂挤占是算法造成"→供给事实 ④ "漏报主要是 search_doc 缺正文"→结构漏仅 14.3%，73% 是排序抽签 ⑤ "基线对不上"→全对上。
未验证：SUMMARY_TRUNC=300 对判档杀伤量级；P1 收益量化（25-35% 是外推，实现后按同方法复测，评测管线可复用）；work_mem spill 时延贡献；生产同城每 MB 传输时延。

## 9. 问题分级

| 级别 | 问题 | 证据 | 修复 | 工作量/风险 |
|---|---|---|---|---|
| P0 | 召回静默漏 89% 应推荐岗（含目标岗位字面命中高分岗），feed 恒满不可见 | B1 表、missedSample | P1 三项+budget 1800（本周）、P2 正文 FTS（两周） | 小/低 |
| P0 | 校招预筛不认「27届」类标题，校招画像被杀 ~10% | C 92 个、F 148 个 | pattern 加 %届%（对齐 grad_class） | 一行/极低 |
| P1 | company/cityNew 层设计性低效（~40% 预算换 <10% 产出）；companyHit 不豁免 role 门 | 存活率数据 | 层内 roleRef 优先；「目标公司豁免方向门」属产品决策 | 小/低 |
| P1 | cityFirst 对 scope=all 反向优化 | 画像E 漏 92.8% | 桶序按 scope 分支 | 小/低 |
| P2 | 层间重复浪费 0-21%；排序 spill | EXPLAIN | 近似去重；work_mem | 小/低 |
| P3 | candidate_capped 恒 true 无信息量，漏报零观测 | 7/7 capped | feed.timing 加抽样率或周期性离线评测 lane | 中/低 |

## 10. ROI 动作清单

1.（本周）校招预筛补 %届% — 一行。
2.（本周）company/cityNew 层内 roleRef-first + scope 感知桶序 — 名额效率 23%→40%+。
3.（本周）budget 900→1800 — +0.3~0.8s；与 1、2 叠加预计 10.8%→25-35%；改完按同方法复测。
4.（两周）summary_doc 正文 bigram FTS — 消 14.3% 结构漏大部分。
5.（架构决策）三列物化+CI 单写入端回填+硬门下推 — 创始人拍板；不走三端移植。
6.（产品）关键词卫生 — 23 关键词画像最差（5/20），移交主线 A/产品。
