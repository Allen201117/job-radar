# 主线 D：岗位可靠性（死岗/假 active 治理）— 审阅发现

审阅时间：2026-08-26 17:00 ~ 2026-08-27 10:20（北京时间）。全程只读。
口径说明：除特别标注外，「active」= `jobs.status='active'` 裸计数（治理视角看行数，不是首页展示口径）；
「never-checked」= `status='active' and enrich_checked_at is null`；数据源 = 香港 jobs 库 psql 只读 + Supabase ops_runs/events/sources + gh CI 历史 + live 抽样核验（httpx/curl/真浏览器渲染）。

## 0. 结论速览

| 问题 | 结论 | 关键数字 |
|---|---|---|
| D1 never-checked 趋势 | 横盘不收敛（±0.5k/日） | 08-26 17:38 = 77,289；08-27 10:13 = 77,704（active 380,595→382,619） |
| D2 三层覆盖 | httpx 层过配（每岗 2×/天）；浏览器层产能坍缩（07-29 起每晚超时）；展示层名存实亡 | sweep ~40.8 万次/天 vs audit ~4.7k/天；盲区 ~20.6k 岗零治理 |
| D3 展示态死链率 | ≈ 3%（5/160，全是 feishu 坏链非撤岗） | 大盘随机 ≈ 5%（6/123 确认死）+ 已知系统性暗死 4,028 条（≈1.1% 全库） |
| D4 absence 红线 | feishu ✓ 安全；beisen 幸在 dry-run，开 apply 前有 PortalId 口径坑；bytedance 全集性本机无法核验 | 华为已钉死 False ✓ |

## D1. never-checked 是增长还是收敛？→ 横盘，不收敛

**总量趋势**（同口径三次测量）：
| 时刻 | active | never-checked |
|---|---|---|
| 2026-08-26 上午（任务书基线） | 380,595 | 77,633 |
| 2026-08-26 17:38 | 380,595 | 77,289 |
| 2026-08-27 10:13 | 382,619 | 77,704 |

日净变化 ±0.4k，产能账勉强打平、不在收敛。

**按 first_seen_at 年龄分桶**（08-26 17:38，never-checked 77,289）：
| 年龄 | never-checked | 该龄 active 总数 | nc 占比 |
|---|---|---|---|
| <7d | 6,834 | 28,578 | 24.1% |
| 7-14d | 6,469 | 28,788 | 22.5% |
| 14-30d | 9,884 | 58,224 | 16.9% |
| 30-60d | 22,107 | 162,646 | 13.6% |
| 60-90d | 31,995 | 102,414 | 31.2% |
| >90d | 0 | ~0 | 全库最老 first_seen ≈ 90d（6 月中旬销毁式重建痕迹，非治理功劳） |

解读：新岗约 76% 在 7 天内被首检，长尾拖 1-3 个月；60-90d 桶 32k 是重建初期欠账。一个岗从入库到第一次被验证，最坏要等 2-3 个月。

**产能账**（近 7 天日均）：流入 ~4,082/日（httpx 2,068 + 浏览器 1,806 + 盲区 208，全 NULL 入池）；流出 httpx 当日清掉 ~2.1k、浏览器实际 ~2-3k/日 ≈ 流入的浏览器类 → 净 drain ≈ 0，与总量横盘互证。

**never-checked 按 adapter 集中地**（08-26）：
| adapter | 源数 | active | never-checked | nc% | 治理层归属 |
|---|---|---|---|---|---|
| beisen | 332 | 68,280 | 18,749 | 27.5% | 浏览器 audit |
| moka | 375 | 51,656 | 15,177 | 29.4% | 浏览器 audit |
| bytedance_campus | 1 | 8,058 | 6,703 | 83.2% | 浏览器 audit |
| feishu | 66 | 10,366 | 6,259 | 60.4% | 浏览器 audit + absence |
| jd | 1 | 3,173 | 3,173 | 100% | 无任何治理 |
| byd | 1 | 5,936 | 2,746 | 46.3% | 浏览器 audit |
| ashby | 20 | 2,718 | 2,718 | 100% | 无任何治理 |
| netease | 1 | 3,633 | 2,225 | 61.2% | 浏览器 audit |
| antgroup | 1 | 2,046 | 2,046 | 100% | 无任何治理 |
| baidu | 1 | 2,389 | 1,735 | 72.6% | 浏览器 audit |
| workday | 100 | 92,769 | 1,291 | 1.4% | httpx sweep（健康） |
| haier/mihoyo/iguopin/meituan_campus/phenom/tencent_music/alibaba_campus/pinduoduo | 各1-5 | ~4,838 | 全部 | 100% | 无任何治理 |
| successfactors | 14 | 7,815 | 1,059 | 13.6% | 有探活器但不在 sweep matrix |
| hotjob/wt/oracle/smartrecruiters/eightfold/其余 httpx | — | ~90k | ≈0 | 0-0.4% | httpx sweep（健康） |

## D2. 三层探活的实际覆盖率与命中率

### 层① liveness-sweep（httpx 逐岗 detail）— 覆盖极好且过配
- ops_runs 近 14 天：每天 checked 40.3万-41.7万、54 runs（18 adapter × 3 cron）、判死 123-1,558/天、failed=0。
- httpx 18 adapter active 存量 ≈ 18.3 万 → 每岗每天被重检 ~2.2 次；nc≈0、24h 保鲜。
- 近 14 天判死大户：amazon 3,264 / wt 1,866 / hotjob 1,670 / greenhouse 1,421。
- **缺口 1（配置漏）**：successfactors 在 ENRICH_REGISTRY 里但不在 liveness-sweep.yml matrix（18 个无它）→ 7,815 岗有工具没上岗。
- **缺口 2**：结构盲区（见 D1 表）。
- **缺口 3（信号盲区，本轮最重新发现）**：sweep 探的是数据接口不是用户页面。4,028 个「接口报活、页面必死」的岗被天天盖「已检」章。

### 层② dead-link-audit（浏览器渲染 SPA）— 产能坍缩近一个月无人发现
- 每晚 22:00 6-shard 主轮转自 2026-07-29 起连续 13+ 晚 run 级 cancelled/failure：job 级实测（run 32905022433，08-25）6 shard 中 2 个 90min 整被 timeout 杀；08-13 6/6 全灭。被杀 shard 部分工作不写 ops_runs。
- 日吞吐 11,800/天（07-28 前）→ 1,900-7,800/天（日均 ~4,700）。时间点与 commit a3011f4（按源摊名额）+ --must-apply-first 上线重合——按源摊名额后候选散布到大量慢渲染租户，1,500 岗/90min（~3.6s/岗）不够。**「CI 绿灯≠有产出」现行案例：run 列表里是 cancelled，没人看。**
- 覆盖 17 个 SPA adapter，存量 ≈17.7 万 → 当前速度全量轮一遍 ~37 天（设计 ~17 天）。
- 命中率 expired/checked ≈ 14-20%（nulls-first 打最老未检岗）——浏览器源未检存量死岗浓度不低。
- 辅助车道健康：dead-link-audit-new（4×/天×300）与 must-apply 保鲜（2×/天×2×400）都在跑 --apply。

### 层③ 展示时/点击异步探活 — 名存实亡
- 批量端点只支持 10 个 httpx adapter（恰是 sweep 已 24h 保鲜的那批，「24h 内检过就跳过」→ 增量≈0）；SPA 一个不支持。
- 点击单岗核验：events 近 14 天 job_liveness_at_click 仅 23 次、22 次 unknown（2.5s 封顶探不动）。实际拦截 ≈ 0。

### 三层都够不着的盲区（完全零失活治理）
11 个 adapter、12,775 个 active 岗、100% never-checked：jd 3,173 / ashby 2,718 / antgroup 2,046 / haier 1,238 / mihoyo 1,081 / iguopin 1,008 / meituan_campus 608 / phenom 363 / tencent_music 360 / alibaba_campus 133 / pinduoduo 47。
加 successfactors 7,815 → **~20.6k 岗（5.4% 全库）「永不验证」**。抽样佐证：phenom 随机抽 1 条即 404。主线 C 的「京东反超官网 +1,450」与 jd 100% 零治理互证。

### 观测性缺口
db-report.yml 上次运行 2026-07-11（无 schedule）——停摆 6 周，never-checked 趋势、audit 坍缩均无人看见。

## D3. 抽样真实死链率

### 方法
- 展示态样本：Jobs 页真实口径（active + summary≥60 字 + first_seen_at desc）最新 3,000 抽随机 180。
- 大盘对照：全库 active tablesample system(2%) 抽 150（块抽样对物理聚簇略偏：moka 欠采、workday 过采）。
- 判定：httpx 类调生产同款撤岗信号（import crawler/enrich.py ENRICH_REGISTRY）；SPA 类 httpx 探 hard-404/DEAD_MARKERS + 可疑子集真浏览器渲染（19 页面）+ 租户全量列表 API 成员核验（beisen/feishu，56+17 岗）。
- 本机够不着的 host（字节读超时、百度/美团/京东/比亚迪 TLS EOF，双栈均败）从分母剔除单列。

### 展示态结果（n=180）
| 判定 | 条数 | 说明 |
|---|---|---|
| 确认活 | 155 | httpx 信号 96 + 列表在册 43 + 渲染活 8 + ctrip 误报 3 纠正 + 其他 |
| 用户点开即死 | 5 | 全是 feishu「租户门户已关闭」坏链 |
| 判不了 | 6 | ccccltd 4 + dingtalk 壳 + bytedance 壳 |
| 本机够不着 | 14 | 字节 5、百度 2、美团 2、京东 1、小米飞书 2、hotjob 1、chagee 1 |

**展示态死链率 ≈ 5/160 ≈ 3.1%（95%CI 1-7%）。真·已撤岗 = 0——坏体验全部来自坏链。**

**feishu「租户门户已关闭、API 还在吐岗」**：68 租户逐一探测，11 个 100% 硬 404（sensetime/momenta/ponyai/bambulab/modelbest/infinigence/huanle/xreal/didatravel/jzyxgames/dedao），合计 **1,192 个 active 岗用户必 404**（bambulab 390 / momenta 259 / ponyai 158 / modelbest 131 / sensetime 78 / infinigence 57 / huanle 37 / xreal 34 / didatravel 31 / jzyxgames 14 / dedao 3）。
铁证：sensetime 列表 API 返 75 在招岗、目标 id 在册，但 detail 对任意 id 都 404，真浏览器同「Not Found」。
**恶性循环**：audit 渲染 Not Found → 标 expired → purge 永删 → 次日 daily-crawl 重抓 → first_seen 重置 → **坏链岗永远顶在 Jobs 最前**（huanle 37/37 first_seen 全在 3 天内）。受影响的恰是高价值公司：Momenta、Pony.ai、商汤、面壁、拓竹、XREAL。

### 大盘对照结果（n=150）
| 判定 | 条数 | 明细 |
|---|---|---|
| 确认活 | 117 | httpx 信号 97 + 列表在册/渲染活 20 |
| 确认死 | 6 | phenom AMD 404；beisen 大华停招；moka 阿克苏诺贝尔+完美世界停招；netease 77716 软死（骨架页无内容，audit 也测不出）；haixin 北森整租户 Not Found |
| 判不了 | 9 | ymtc 4、ccccltd、starbucks（渲染跳首页疑死）、dfmc-moka 1、bytedance_campus 壳 2 |
| 本机够不着 | 22 | bytedance_campus 15、bytedance 3、byd 2、meituan 1、baidu 1 |

**大盘随机死链率 ≈ 6/123 ≈ 4.9%（判不了折算后上界 5-8%；moka 欠采——moka 抽 5 死 2）。**

### 系统性「暗死」存量（信号盲区，必须单列）
1. **wecruit「渠道未发布」存量未动**（e55171e 只修增量）：新城控股 1,219 + 歌尔 468 = 1,687 条仍 active、100% 72h 内被盖「已检」章；真浏览器实测无限转圈。荣耀 411 条同病同批。合计 ~2,378。
2. **dfmc.hotjob.cn NXDOMAIN**（东风汽车）：1,650 条全 active、全被盖章。根因 enrich_backlog.py L188-193：网络错误按 miss 处理照样盖 enrich_checked_at，对「域名永久消亡」无升级路径；enrich_fail_count 在涨但无人消费。

**合计 ≈4,028 条确定性暗死（≈1.1% 全库，hotjob 类 22%）。** 主线 C「腾讯 +920 / 比亚迪 +3,400 / 京东 +1,450」与此同构：接口信号盲区（tencent）、audit 轮不到（byd）、零治理（jd）各占其一。

### 汇总口径
- 展示态：点开即死 ≈ 3%，几乎全坏链（feishu 租户病），真撤岗≈0。
- 大盘：确认死 ≈ 5%，上界 ~8%；另 1.1% 确定性暗死 + 20.6k 零治理盲区（死亡率未知）。
- 展示态零 moka 是结构性巧合：moka 列表岗无正文进不了有效岗口径，意外保护了用户。

## D4. absence 红线复核

**开关面**（grep 实证）：
| adapter | supports_absence_liveness | 实际生效 |
|---|---|---|
| feishu + nio/xiaomi/xpeng/horizon 变体（feishu.py L41） | True | 真 apply（daily-crawl httpx tier LIVENESS_ABSENCE_APPLY=true，workflow L94） |
| bytedance / bytedance_campus（bytedance.py L399/L545） | True | 真 apply |
| beisen（china_ats.py L423） | True | 强制 dry-run（LIVENESS_ABSENCE_OBSERVE 默认含 beisen，run.py L431） |
| huawei | False | test_huawei_adapter.py::test_absence_liveness_must_stay_off 钉死 ✓ |
| moka / company_spa / 其余 | 无属性 | 不参与 ✓ |

护栏在位：fetch_complete 前置 + plan_absence_sweep 50% 闸 + min_active_floor=8（jobs_db.py L303-340，test_absence_sweep.py 三态覆盖）。enrich-crawl.yml 未设 APPLY → 那条道全 dry-run（安全方向缺口）。

**逐个全集性核验**：
- feishu ✓：sensetime live 对拍 API 75 vs 库 78（列表是超集方向）；11 个坏链租户的岗都在 API 列表里 → absence 不会误删。
- beisen ⚠️（幸在 dry-run）：PortalId 是门户页级的——qilu-pharma 从 /social 抽的 PortalId 列表不含其 7 条样本岗，但渲染抽验 2 条全在招。Category=[] 修了类别维度、Portal 维度仍非全集。**开 apply 前必须对 top-20 租户对拍，覆盖 <95% 的不开。**
- bytedance 未验证：本机网络够不着（标未验证假设，建议 CI 内对拍）。
- 观测缺口：daily-crawl 日志 grep 不到任何 [absence] 行——candidates=0 与从未触发无法区分，建议 run.py absence 分支加永久打印。

## 证伪掉的怀疑
1. 「sweep 又跑了等于没跑」→ 证伪（0 fail、httpx nc≈0；三个历史病均未复发）。
2. 「展示态死岗是撤岗检测失灵」→ 证伪（真撤岗 0/160，全是坏链；问题在链接质量门）。
3. 「never-checked 恶性增长」→ 部分证伪（横盘；真问题是长尾+盲区）。
4. 「ctrip 岗大量已下线」→ 证伪（SPA bundle 文案误报，DEAD_MARKERS 不可用于 raw HTML）。
5. 「absence 已在乱杀」→ 证伪（护栏全在位；风险是前瞻性的 beisen Portal 口径）。

## 未验证假设
- bytedance/bytedance_campus 列表全集性（CI 内对拍可验）。
- ymtc/ccccltd/starbucks 的「加载失败/跳首页」是地域/反爬还是真死（9 条影响大盘死链率 ±3pp）。
- audit 坍缩确切根因（需被杀 shard 逐岗耗时日志，或 timeout 150 + limit 1200 做 A/B）。
- 20.6k 盲区真实死亡率（phenom 1/1 死是孤证；可各抽 30 条估计）。

## 问题清单（P0-P3）
| # | 级别 | 问题 | 根因（证据） | 影响面 | 修复方案 | 工作量 | 风险 |
|---|---|---|---|---|---|---|---|
| D-1 | P0 | 4,028 条暗死岗天天被盖活章 | sweep 只探数据接口；wecruit 渠道未发布存量+dfmc NXDOMAIN；miss 也盖 enrich_checked_at（enrich_backlog.py L188-193） | 全库 1.1%，hotjob 类 22%；荣耀是必投头部 | 存量按 should_skip 判据出逐条清单人工复核标 removed（核验样本量=影响面）；NXDOMAIN ≥3 天升级撤岗候选；enrich_fail_count≥K 持续 M 天进死信复核队列 | 1-2 天 | 低（渠道级判据已 live 验证） |
| D-2 | P0 | feishu 11 租户 1,192 坏链岗循环重生、顶在 Jobs 最前 | 租户关门户 API 照吐；audit 杀→purge 删→重抓→first_seen 重置；jd_url 质量门从未探 feishu detail 可达性 | 展示态坏链 3% 主要来源；Momenta/商汤/Pony.ai 等 | adapter 每租户每轮抽 1 条 detail 探可达，404 则该租户跳过入库（wecruit should_skip 模式自愈）+ 存量 1,192 标 removed | 半天-1 天 | 门户恢复自解除；无误杀面 |
| D-3 | P1 | audit 产能坍缩 27 天无人知 | 07-29 按源摊名额后 1,500 岗装不进 90min，shard 被 timeout 杀，部分工作不落 ops_runs | 17.7 万岗轮转 17→37 天；nc 停止收敛直接原因 | timeout 90→150 或 limit→1000 先试其一；cancelled 连续 ≥3 天告警；慢租户单独降档 | 半天 | CI 时长+50% |
| D-4 | P1 | 20.6k 岗零治理盲区 | 11 adapter 三层全不覆盖 + successfactors 漏排 matrix | 长期堆死岗 | ① successfactors 加 matrix（一行）② jd/antgroup/mihoyo/tencent_music/iguopin 公开 JSON 源照 ENRICH_REGISTRY 各写探活器 ③ ashby 404 即死 ④ 其余并入 audit | ①10min；②③各半天 | 信号先 live 验证再上 |
| D-5 | P1 | 展示层对 SPA 无能为力+点击探活 96% unknown | liveness-client 只映射 10 httpx adapter（都被 sweep 保鲜=白探） | 层② 实拦≈0 | 建议不修，预算挪 D-2/D-3 | 降级不修 | — |
| D-6 | P2 | nc 长尾 1-3 月 + 60-90d 桶 32k 欠账 | audit 产能+必投倾斜分流 | 老岗死亡率未知 | 随 D-3 收敛；可手动 dispatch 数轮清欠账 | 随 D-3 | — |
| D-7 | P2 | db-report 停摆 6 周、absence 零日志 | 无 schedule；absence 分支不打印 | 问题指标上看不见 | db-report 加每日 schedule；absence 永久打印；ops_runs 加 nc 快照 | 半天 | 无 |
| D-8 | P2 | beisen 开 absence apply 前的 Portal 全集性坑（前瞻） | PortalId 门户页级抽取，多门户租户列表非超集（qilu-pharma 实锤） | 现零损失；开闸即有误杀面 | 开 apply 前 top-20 租户对拍，<95% 不开；写进摘除 checklist | 对拍半天 | 不开闸零风险 |
| D-9 | P3 | sweep 每岗每天重检 2.2 次过配 | 3 crons × limit 50000 » 存量 | ~40 万请求/天纯成本 | 降 2 crons 或 limit 减半，省出预算挪 audit | 10min | SLA 12h→24h 仍满足 |

## ROI 排序
1. D-4①（successfactors 补 matrix）：10 分钟/7,815 岗。
2. D-3（audit 超时参数+告警）：半天，轮转 37→17 天。
3. D-2（feishu 租户探活门+存量清理）：1 天，展示态坏链 3%→~0.5%。
4. D-1（暗死 4,028 清理+miss 升级路径）：1-2 天，大盘 -1.1pp。
5. D-9+D-7（sweep 降频+观测补洞）：半天，防复发。
6. D-4②③（盲区逐个补探活器）：每个半天，按存量 jd→ashby→antgroup 排。
7. D-8（beisen 对拍 checklist）：开闸前必做。

关键涉证文件：crawler/enrich.py ENRICH_REGISTRY L467 / crawler/enrich_backlog.py L159-193 / crawler/audit_dead_links.py L43-64 / .github/workflows/liveness-sweep.yml matrix / .github/workflows/dead-link-audit.yml timeout-minutes / crawler/run.py L425-439 / crawler/adapters/feishu.py L41、china_ats.py L423、bytedance.py L399 / lib/liveness-client.js L216-230
