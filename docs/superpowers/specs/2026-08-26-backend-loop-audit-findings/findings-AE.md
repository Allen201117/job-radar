# 主线 A + E 审阅发现（findings-AE）

**测量口径**：2026-08-26；香港库 `status='active'`=380,639；真实画像 39 份（Supabase 全量，已匿名）。**方法**：离线 harness 用生产代码原样重放 Today 全链路（`buildRadarProfile`→`buildRecallSql(900)` 真跑香港库→`computeMatchFacts`/`checkEligibility`/`scoreOpportunity`，sources 元信息真取），同批岗并行跑 Jobs 路径 `scoreJob` 对拍。抽 6 个真实画像：#37 AI产品经理·校招·沪深杭 / #1 数据科学·校招·北京 / #2 设备运维测试·校招·陕西 / #9 机械·实习·宁波 / #15 运营行政·校招·南昌 / #38 射频硬件·校招·珠三角。原始数据与脚本在 scratchpad/agent-ae/（harness.js / leak.js / experiment.js / run-p*.json / prefs.json）。

## 浓缩摘要（关键数字）

- **误报率**：6 画像可见层 top-N 逐岗人工标注 102 岗，明显不该出现 70 个 ≈ **68.6%**（分画像 9%→95%：#37 1/11、#1 10/20、#2 15/20、#9 4/6、#15 19/20、#38 21/25）。
- **漏报率**：用「标题级强匹配+目标城市+7天在架」理论池跑同一套硬门：#37 应展示 163、实际 12，**漏 92.6%**（漏掉的含字节 `AI产品经理（策略方向）杭州`——字节是该用户手填目标公司）；#38 应展示 6、实际 3，漏 50%（漏掉 TCL`天线工程师`，却展示 TCL 模具/IE 工程师）。另 29.5% 的 active（11.2 万岗）last_seen 超 7 天，任何画像永远进不了 Today。方法局限：理论池是标题锚定，真实漏报只会更高；严格值归主线 B 全库扫描。
- **degraded 分布**：「≥3 维 unknown 放行」在 895 个展示岗中仅 1 个（0.1%）——初步怀疑 2 证伪。真形态是「location+education 双维 unknown」为校招画像常态（展示岗中 location-unknown 62%、education-unknown 71%），每维仅 -2 分。库缺失率：location 7.4%（campus 源 >50%）、education 33.8%、job_type 48.2%、experience 66.5%。
- **related 贡献**：101/895 = **11.3%**，质量差但不是主要病灶——初步怀疑 1 方向错了，**误报大头在 exact 档**。
- **两条路径口径差**：同岗同人结论大面积相反——Today 拒掉但 Jobs 打 ≥40「高匹配」的岗：#1 345 / #15 347 / #38 306 / #37 114。Jobs 的 40 分徽章可由 城市20+公司15+新鲜10 零 role 命中凑出（字节`财务实习生`对 AI 产品用户=45 分标高匹配）；scoreJob 完全没有 stage 概念。应统一到 computeMatchFacts 事实层，徽章加 role 命中前提。
- **筛选器最严重 3 个问题**：① 省份/区域目标城市全链路按字面子串——「陕西」只命中 404 岗、西安 2,635 岗被 Today 硬拒（39 画像中 5 个/13% 填了省或区域，这些用户的 Today 基本不可用）；② 城市浏览计数错 5 倍且结果为任意子集——北京 FTS 候选 41,572 > cap 8,000，截断无 ORDER BY，翻页也翻不到其余 3.3 万；③ 关键词筛选 exact 档正文泛词污染——搜「测试」时 top-20 有 15 个非测试岗标 exact。

## A-P0-1｜exact 档被三个机制击穿（误报主因，全部实证）

1. **AND 单元「泛词单元靠标题、具体单元撞正文」**（china-keyword-expansion.js:400-428）：「测试工程师」=[测试组 AND 工程师组]，任何标题带「工程师」的研发岗 JD 里必有「测试」→ exact。画像#2 实证 474 个展示里 客户端开发/C++后台/大模型算法/前端/销售工程师 成片 exact。「硬件工程师」同理吃掉 TCL 模具/IE/工艺岗。2026-06-11 设计的职能门只治跨职能、治不了同职能内子方向污染——设计盲区非回归。
2. **classifyJobFunction 的 summary 兜底 + 职能例外回落**（:717-730）：字节`招聘HR（抖音）`JD 写「支持的岗位类型包括…产品经理…」→ 例外回落全文 → jobFn=产品 → 过职能门 → exact score 90 推给 AI 产品经理（#37）。美团`公共关系岗/法务岗/门店管理储备岗` JD 含「技术/AI」→ 兜底判研发（#1 top-20 有 10 个）。2026 年所有 JD 都写 AI，这个兜底把职能门整个泄了底。
3. **查询词经组扩展退化成裸泛词**（:370-374）：'产品落地'≡'产品'、'数据中台'≡'数据'；'机器学习'扩出 'AI' → `AI招聘Builder`标题命中 exact。
- **收紧实验**（补丁：2 字 CJK/≤3 字母词正文不算 + summary 兜底禁判研发，同召回集对拍）：#2 误报 473→224（-53%，误伤 ~1-2%）；#1 141→122（-13%）；#37/#38 基本不动 → 收紧有效但不充分，根治要「多单元查询里具体单元必须命中标题」+ 修分类器。

## 其余确诊问题（带证据）

- **A-P1｜行业硬门用公司标签杀岗位**：#38 有 225/749（30%）industry_mismatch；#37 的 TCL`AI产品经理（大数据）`被硬拒（TCL→制造 override）而 Jobs 页搜得到。建议 mismatch 降为重罚或 role-exact 时放行降档。
- **A-P1｜location 空但标题带城市绕过城市门**：#15（只要南昌）展示 71 个中 70 个 location 空，标题却写着`直播运营（长沙）`——locationState 只读 location 字段（eligibility.ts:68-91）。修法：空 location 时从标题提取「（城市）」，1 天。
- **A-P1｜exclude_keywords 撞全文静默过度排除**：#1 排除「算法」→ recall SQL not-like 整个 summary → JD 顺带提「算法」的数据分析好岗被整体排掉。
- **A-P0｜召回公司层饿死**：TIER_WEIGHTS company=2/10 ≈180 名额面对字节 2 万在架岗 → 用户点名公司的对口岗漏 151 个。速修：公司层 SQL 收窄成 company AND role。
- **A-A5｜简历→偏好污染系统性**：根因 lib/resume-parser.js:85（skills 原样灌 target_keywords 截 16）+ app/api/resume/route.ts:457（mergeUnique 累积不清洗，#37 攒到 23 个）。13 个有 keywords 的画像 7 个（54%）混入工具/证书词（Word/Excel/计算机二级/英语专八/Vue3/JWT）；roles 有 7 个非职位词；1 个 target_companies=['无']。每个 keyword 都是独立 exact 查询。
- **E1 逐维**：公司=DB 真值+子串，可信；城市=~40 城别名硬编码、无省份，FTS 路径把 28,238 个空 location 岗全排除（仅 894 可达），与 JS「缺失降级放行」设计矛盾（search.ts:106-117 超集注释对 tsquery 路径不成立）；类型=硬编码三桶+超集下推，可信；学历=educationMatch，两路径唯一完全一致的维度；经验=无筛选（缺失 66.5%，合理）；行业=Jobs 无此维度但 Today 有硬门（能力不对称）；资本来源=名单法未深审（未验证假设）；默认匹配排序只看最新 2.8 万行（7.4%），计数实为「最新 2.8 万里的匹配数」。
- **E3 口径差六处**：硬门 vs 软分；城市匹配两套函数（cityMatchTokens vs includes）；城市缺失三层三个行为（JS 降级放行 / FTS 排除 / Today 照收）；行业硬门 vs 无维度；exclude 6 字段 vs 2 字段（scoring.ts:180 只看 title+summary）；阈值 40/15 vs 70/45/30 互不换算。
- **E4 可自动推断**：jobType←experience_stage、城市←target_locations、学历←简历 highestEducation、地区←target_regions；建议 Jobs 页默认「按你的偏好筛选中」芯片组+一键清除。
- **P3**：classifyJobFunction 顺序 bug——`销售工程师`判「研发」（研发规则先于销售且含/工程师/，:675）。

## 被证伪的怀疑
- related 主因论（×，占 11.3%）
- 四维 unknown 常态论（×，0.1%）
- Today 城市门对英文 location 失明有实害（×，国内 active 纯拉丁 location=0 行，机制分叉但零实害）
- 兄弟组排除逻辑本身有 bug（×，脏在上游 classifyJobFunction 喂错职能）

## 修复 ROI 排序
1. 修 exact 三机制（1 文件+4 套测试，2-4 天，有回归 harness，最差画像误报砍半以上）
2. 省份映射+标题城市兜底（各 1 天，救活 13% 用户）
3. 召回公司层 company×role 收窄（1 天 SQL）
4. 偏好写入端清洗（1-2 天，治本）
5. 行业门降档+徽章口径统一（3-5 天）
6. 城市计数独立 count+稳定排序（半天）

## 未验证假设
- 资本来源名单精度
- 漏报严格值（归主线 B 全库扫描）
- 误报为单人标注（建议创始人抽 2 画像×20 岗复核，20 分钟）
- grouping/dailyLimit 截断未纳入（只影响排序分区不影响资格）
