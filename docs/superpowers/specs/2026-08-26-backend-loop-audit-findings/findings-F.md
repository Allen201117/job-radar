# 主线 F：职业洞察审阅发现（findings-F）

测量时间：2026-08-26。全部只读。数据源：Supabase PostgREST（分页拉全量）、香港 jobs 库只读 psql、gh CI 日志、80 条来源 URL curl 实测、30 条 active 洞察分层抽样（seed=42 可复现，明细 scratchpad/agent-f/sample30.json）。

## 0. 浓缩结论

- **覆盖**：active 洞察 6,164 条、覆盖 505/1,162 家在招公司（43.5%）；按岗位数加权覆盖 51.7%。真「点开全空白」只有 114 家（active 岗 <3，T1 派生也出不来）。无洞察公司岗位量 Top15 全是外企/车企/制造大户（JLL/强生/雅培/长城/吉利/汇丰…），因 T3 队列按 `founded_year desc` 排不上。现查快车道 2 个月仅触发 6 次、台账 6/6 永久 `queued`（workflow 不回写），但真跑了的 4 次全成功。产能 8 家/天（搜索额度封顶），补齐 657 家缺口 ≈ 82 天——前提是 LLM 活着。
- **P0 · T3 当前停摆**：2026-08-25 起 SiliconFlow 余额耗尽（HTTP 402），CI 实锤 40 次 LLM 全失败、wrote=0，且每天照常烧光 90 次搜索额度（检索先于 LLM；serper 是 2,500 次一次性总额度，纯净损耗）。402 未列入 account_error 分类。
- **质量（30 条分层抽样）**：真有信息差 30%；PR 套话 27%；维度错配尚有值 17%；严重问题 27%（行业新闻当公司洞察、政务新闻标「面试难度·fact」、融资新闻当年终奖、来源与结论脱钩、美的 listing 错标上交所——Wikidata P414 上游错、巨潮名匹配漏掉未纠错）。根因确诊：「样本 ≥5 + ≥2 源共识」两道门构造性必过——`sample_size=len(检索结果)`（insight_backlog.py:325）、publisher 按整包结果计（insight_engine.py:244）、`_pick_sources` 凑未判官核验的源填门（insight_backlog.py:241-253）；真正的闸只有单源判官（真实拦截率 42%），但它不校验公司/维度相关性。来源链接 80 条实测 200 占 74%，硬死链 2–5%。
- **时效**：staleness sweep 真在跑且有效（30/30 天绿、active 中 valid_until 过期 0 条、last_verified_at 全在 90 天内）；「近 3 年窗」有 ~5% 泄漏。
- **维度价值**：culture 2,537 条占 41%、约 1/3 PR 套话；path 被薪资内容系统性污染。更该做：真实薪资区间（salary_text 仅 1.5% 岗位有值，T1 派生失效）、面试流程轮次（查询包已有主题，改路由零新增成本）、裁员/收缩信号（T1 已算 tightening momentum 只是埋着）；部门口碑不建议做。
- **合规**：✅ 无红线违规——T3 只打 4 个搜索 API 官方端点、无 site: 定向、无直爬社区/招聘平台代码。一处灰区待拍板：insight_sources 引用 URL 出现 BOSS直聘点评页/智联问答页（搜索 API 前门返回、≤200 字摘录+回链，合规线内但观感有张力）。

## 1. 实测数据表

### 1.1 库存与覆盖
| 指标 | 实测值 | 口径 |
|---|---|---|
| insight_items | 6,310（active 6,164 / retired 146 / pending_review 0） | 全量分页 |
| active 按维度 | culture 2,537 / hiring 1,176 / path 1,123 / compensation_intensity 1,063 / listing 253 / timing 12 | |
| active 按 origin | public_web 5,890（95.6%）/ wikidata 179 / official 56 / manual 39 | |
| active 按 grade | experience 4,315 / fact 1,849 | |
| 覆盖公司 | 484 家（company_id 口径）；对齐在招公司 505/1,162 = 43.5%（含 aliases 宽松匹配） | |
| 岗位加权覆盖 | 196,829/380,653 = 51.7% | |
| company_profiles | 1,112；insight_checked_at null 仅 1；t3_checked_at null 620（56% 没跑过 T3） | |
| active 岗 <3 的公司 | 114 家（抽屉真空白） | |
| active 岗有 salary_text | 5,802/380,643 = 1.5% | |

### 1.2 供给产能（近 30 天）
- 搜索消耗：tavily 892 / serper 593 / qianfan 1,200 / bocha 0（未配 key）——三源日顶全打满。
- T3 吞吐 8 家/天（每公司 5 主题 × 3 源 ≈ 15 次检索）；每日新写 75–115 条，8/25 起归零。
- T2 队列已清空、每日 TTL 复核 2–8 家；`seeded ~90/天` 是分页缺陷造成的假数字。
- 判官拦截：08-23 run 89 claim → 52 active / 37 drop（42%）。
- retired 共 146 条（全部 replace-on-refresh 换代；巡检近 30 天 retired=0，最早 valid_until 在 2027）。

### 1.3 现查快车道
台账（discovery_runs mode='insight_enrich'）仅 6 行、6/6 永久 queued（insight-enrich.yml 无回写 step）；可核到的 4 次实际全部成功（08-24 各 ~4min）。抽屉端 grep enrich_now 0 命中——用户触发无感知。

### 1.4 时效
- 巡检 30/30 天绿 + ops_runs 每日台账；active 中 valid_until 过期 0 条。
- 259 条无 valid_until 的全是 official/wikidata/manual（drain TTL 复核）。
- last_verified_at：≤30d 2,060 / 31–90d 3,479 / null 0（首轮「625 unknown」是本地日期解析假象）。

## 2. 质量抽样明细（30 条，seed=42）
判定分布：真有信息差 9（30%）｜PR 套话 8（27%）｜维度错配尚有值 5（17%）｜严重问题 8（27%）。
严重问题逐条：华策影视（行业泛化新闻当公司洞察）、国投证券（行业统计）、星环（政务合作新闻标「面试难度·fact」）、Sierra（融资新闻当年终奖+三个不相关来源）、OKX（来源与结论脱钩）、百济神州（「加班文化」装薪酬分布+词表 diff 当来源）、Squarespace（面试难度讲办公氛围）、美的 listing 错标上交所（live 复核确认）。
门失效代码证据：insight_backlog.py:325（sample_size=len(results)）、insight_engine.py:244（publisher 按整包计）、insight_backlog.py:241-253（_pick_sources 凑源）。grade 由 writer 自报，public_web 标 fact 反而走更松的门（抽样 4 条 public_web fact 全有问题）。
链接可达性（80 URL）：200×59（74%）/ 403×13（知乎、一亩三分地、百科反爬，不算死）/ 400×3 / 超时×3 / 404×1。
重复检测：5,890 条 public_web 内容归一后重复(≥3)组数 = 0（「套话靠模板」证伪）。

## 3. 关键文件与行号索引
- app/api/insights/route.ts（T1 必算、快车道触发条件 jobCount>0 && !storedHasAny）
- lib/insight-derive.ts（T1 门槛 hiring≥3/timing≥5/salary≥5；classifyHiringSignal 已有 tightening 信号）
- lib/insight-verification.ts:65-77（experience 展示门）
- crawler/insight_backlog.py:295（T3 队列 founded_year desc）、:325、:241-253
- crawler/insight_engine.py:125（account_error 只认 401/403）、:244-245
- crawler/insight_sweep.py、.github/workflows/insight-{enrich,enrich-t3,staleness-sweep}.yml
- crawler/search_router.py + search_{bocha,tavily,serper,qianfan} + search_base.py（RECENCY_YEARS=3）

## 4. P0–P3 清单
| # | 级别 | 现象/根因 | 修复 | 工作量 |
|---|---|---|---|---|
| F-P0-1 | P0 | SiliconFlow 402 → T3 停摆且每日空烧 90 次搜索额度 | 充值（用户外部动作）+ T3 开头 LLM 预探活失败即停 + 402 入 account_error | <1h 代码 |
| F-P0-2 | P0 | 27% 严重问题 + 27% 套话；样本/共识门构造性必过 | 公司相关性门（judge 顺带判）+ 附源须判官通过（凑不满 2 个不展示）+ public_web 禁 fact 或白名单 + sample_size 从原文抽 | 2–4 天；产出 -30~50% |
| F-P1-1 | P1 | path/hiring 维度跑题污染 | judge 加维度贴合判定 | 1 天 |
| F-P1-2 | P1 | listing 无交叉验证，Wikidata 错则错 | A 股强制巨潮核验，不一致 exchange 留空；巨潮匹配放宽别名 | 1–2 天 |
| F-P1-3 | P1 | 覆盖与需求倒挂（岗位量 Top15 全无洞察） | 队列改「无洞察 × 在招岗位数 desc」 | 1–2 天 |
| F-P2-1 | P2 | 快车道台账永 queued、用户无感知 | workflow 回写 run_id 状态 + 抽屉空态提示 | 各<半天 |
| F-P2-2 | P2 | seed existing 查询未分页、每日虚报 seeded~90 | 改 db.fetch_all_rows | 15 分钟 |
| F-P2-3 | P2 | 3 年窗漏 ~5% 旧内容 | 写入端按结果 date 二次过滤 | 半天 |
| F-P3-1 | P3 | pending_review 全库 0 条、culture 标题混用等小债 | 顺手修 | <半天 |

## 5. 证伪掉的怀疑
- sweep 没真跑（伪）
- 58% 无洞察=点开空白（大部分伪，真空白 114 家）
- 搜索额度是第一瓶颈（伪，第一瓶颈是 LLM 欠费）
- 套话来自模板复制（伪，0 组重复）
- 判官形同虚设（半伪——判官真拦 42%，形同虚设的是样本门和共识门）
- 洞察偷爬社区（伪）

## 6. 未验证假设
- serper 一次性额度剩余量（需登控制台）
- 13 条 403 来源浏览器可开是推断
- 千帆/博查 ≤1 年过滤可靠性未单测
- 07-07 两次快车道 dispatch 成败未核到

## 7. 需创始人拍板
1. public_web 是否禁标 fact
2. 洞察引用里的 BOSS直聘/智联页面是否降权/过滤（合规线内但品牌观感）
3. 「面试流程」「裁员信号」两个低成本新维度是否立项
