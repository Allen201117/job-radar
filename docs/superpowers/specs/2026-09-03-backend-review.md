# 后端体检报告：两个核心价值 × 可持续性 × 扛量（2026-09-03）

审阅对象：岗位库供给与治理链（抓取 / 扩源 / 富化 / 探活 / 清理）、职业洞察供给链、接口层。
证据来源：线上香港库与 Supabase 实测、30 天 GitHub Actions 运行统计、三路只读代码审查、数据路线联网调研。
所有「必须改」都做过线上或代码级复核；审查员报的两条误报（告警开关未开、探活分片白跑）已剔除。

---

## 0. 三句话结论

1. **路线对**：对「中国企业官网岗位 + 逐岗官网链接」这个定位，自建爬虫是唯一能落地的主力路线。国内 ATS 厂商 API 全部要企业逐家授权；国内数据商的数据来自第三方平台、没有官网原链接；Google for Jobs 在国内不可用。补充路线只有三条：国聘（已接）、搜索 API 找入口（已在用）、用户贴链接众包（可做成缺口漏斗的入口）。
2. **治理链基本健康，但洞察链有一条正在咬人的生产 bug**：Supabase 接口默认一次最多返回 1000 行，公司画像 1152 行、在架洞察 6238 行，洞察的接口和爬虫队列全线没分页 → **看板上 84% 的洞察条目根本没被读到**，55% 的公司从未进过 T3 富化队列。这条直接砸在第二个核心价值上。
3. **扛量的第一块倒的是香港库连接**：100 个连接位，空闲时已占 58 个（31 个是 CI 爬虫、19 个是 Vercel 函数），没有连接代理；20 个函数实例并发就打满，超出后 8 秒超时报 500。千级 DAU 前必须上 PgBouncer；万级 DAU 前必须升库；十万级要重做搜索。

---

## 1. 线上实测数字（2026-09-03）

| 指标 | 数值 | 判读 |
|---|---|---|
| 库大小 / jobs 表 / 索引 | 1.8 GB / 1.6 GB / 0.6 GB | 机器内存 2 GB，表+索引已超内存，缓存命中率 90%，剩下 10% 走磁盘 |
| active / removed / expired | 393,446 / 23,029 / 600 | 有效在招（有正文）386,186 |
| 每日新增岗 | 4,000~6,300 | 供给稳定 |
| 从未探活的 active | 61,060（15.5%） | 8 月 28 日治理后持续下降 |
| 7 天未探活 | 95,512（24%） | 探活吞吐不够，见 §3 |
| 14 天列表未见但仍 active | 102,105（26%） | 其中 69k 近 14 天探活确认在招（列表只返子集的源），16.5k 从未探活 |
| 无正文 active | 7,268（1.8%） | 薄卡已压到很低 |
| 连接占用（空闲时） | 58 / 100 | 31 CI + 19 Vercel + 其他 |
| 30 天 CI 运行 | 2,000 次，成功率 96.3%，日均 1,139 分钟 | 每天约 19 小时 runner 时间 |
| 接口耗时（冷 / 热） | stats 4.2s / 0.9s；search 5.4s / 1.1s；companies 3.7s / 0.9s | 网络本身 0.7s，冷启动服务端开销约 3.5s |
| 洞察可用性接口里的香港库聚合 | 2.4s，每次看板渲染都算一次，无缓存 | 见 §2 必须改 |
| company_profiles / 在架 insight_items | 1,152 / 6,238 | 两者都越过 PostgREST 1000 行上限 |

---

## 2. 必须改（真实故障或数据错误，本轮直接修）

### M1 洞察链全线 PostgREST 1000 行截断（第二核心价值直接受损）

- 证据：`app/api/insights/availability/route.ts:39-44` 整表拉 company_profiles + 在架 insight_items；`app/api/insights/route.ts:69`（GET 主路径）、`:242`、`:422`、`:448`、`:464`；`app/api/insights/submit/route.ts:53`；`app/api/career-path/route.ts:27`；`app/api/insights/admin/route.ts:26,112,114`、`admin/cycles/route.ts:15`、`admin/submissions/route.ts:26`；`app/api/company-watch/admin/route.ts:20,119`；`app/api/sources/route.ts:45`。爬虫侧 `crawler/insight_backlog.py:58,78,395-435`（seed 去重集、T2 队列、T3 队列）、`crawler/insight_sweep.py:31`（过期退役）。
- 线上复核：不带 Range 直接查，company_profiles 返 1000/1152，insight_items(active) 返 1000/6238；632 家画像从未进过 T3。
- 影响：抽屉 / 芯片对大部分公司显示「无洞察」；公司名归一化对尾部公司失效 → 现查触发给错公司建占位；过期条目退役不完整。
- 修法：全部改走 `lib/supabase-paginate.ts`（TS）/ `db.fetch_all_rows`（Python）；insight_items 按请求公司过滤后再取；sweep 改为服务端条件过滤后分页。加契约测试钉死「洞察表读取必须分页或按 id 过滤」。

### M2 洞察可用性接口每次看板渲染都做一次 2.4s 的全库聚合

- 证据：`app/api/insights/availability/route.ts:34` 调 `activeJobCountsByCompany()`，在 39 万行 active 上按公司聚合，无缓存；`lib/insight-client.ts:113` 说明每次看板渲染都会打这个接口。
- 影响：每个看板加载额外占一条香港库连接 2.4 秒；是连接池被占满的主要贡献者之一。
- 修法：聚合结果用 `unstable_cache` 10 分钟（所有用户一样，可跨实例共享）；company_profiles 轻列（id/company/aliases）同样缓存；insight_items 只按命中的公司 id 取。

### M3 CI 排班撞车把连接推到上限

- 证据：`liveness-sweep.yml:18` cron `0 5,13,21`，`enrich-backlog.yml:14` cron `0 */3` → 21:00 UTC 同时启动；峰值 4×7 + 5×9 = 73 连接 + Vercel ≥ 19 → 逼近 100。
- 修法：enrich-backlog `max-parallel` 5→3（它平均只跑 1.7 分钟，降并发几乎不影响产出），峰值降到 55；同时给 liveness-sweep 的 cron 错开到 22:00。

### M4 「空产出 = 成功」不进台账，adapter 静默坏掉发现不了

- 证据：`crawler/run.py:389-393` parse 返回空列表记 success/jobs_found=0；`run.py:561-565` empty_count 只打印；run_crawl 不写 ops_runs → ops-watchdog 看不到。
- 修法：run_crawl 收尾写一条 ops_runs（metrics 含 sources_total / empty_count / failed_count），watchdog 规则可接。

### M5 扩源两处静默零产出

- 缺口漏斗 P1→P2 交接失效：`gap-funnel.yml:76-80` 注释自证「P1 当轮交接 18 家，同 run P2 只看到存量 1 家」。修法：P1 把 unknown_spa 公司名写成 artifact 文件，P2 读文件。
- 静态清单枯竭仍报 success：`auto_discover.py:365-371`，LLM 喂料 8 月 27 日已关，清单烧完后每天绿灯零产出。修法：targets 为空且清单非空时记 `status=warning`。

---

## 3. 建议改（万级 DAU 前做；本轮不动）

| # | 项 | 证据 | 价值 |
|---|---|---|---|
| S1 | 香港库前加 PgBouncer（transaction mode），函数池 max 5→2 | `lib/jobs-store/client.ts:34` | 连接位从「20 个实例」变「几百个实例」；软件免费，需登录服务器安装 |
| S2 | 香港库升内存到 4~8 GB | 表+索引 2.2 GB > 2 GB 内存 | 缓存命中 90%→99%，搜索 P95 明显下降；约每月几十元级 |
| S3 | 探活吞吐：liveness-sweep 单轮最长 384 分钟、24% 岗 7 天没探 | GH 统计 | 按 host 再分片或提 workers，前提是 S1 到位 |
| S4 | 偏好保存 `syncCoverage` 5~7 次串行跨洋往返 | `app/api/preferences/route.ts:28-113` | 保存从 ~1s 降到 ~300ms |
| S5 | 管理员判定走 JWT claims，不再每次查 profiles | `lib/apiAuth.ts:38-56` | 需 Supabase 自定义 claims hook |
| S6 | `/api/insights` GET 现查触发按公司去重节流 | `app/api/insights/route.ts:249-296` | 多用户同时点同一公司只算一次 |
| S7 | T3 退役旧条目的条件改为「本轮有新 active 条目」 | `crawler/insight_backlog.py:485-489` | 避免整家公司洞察一天全空 |
| S8 | 校招缺口反探扩到 beisen | `crawler/auto_discover.py:203-207` | 目前只支持 moka |
| S9 | 用户贴岗位链接 → 平台指纹 → 缺口漏斗 | 调研结论 | 众包做成扩源入口，零合规风险 |

---

## 4. 扛量路线图

假设峰值 = DAU × 20 请求，集中在 4 小时，再乘 3 倍突发。

| DAU | 峰值 QPS | 先倒的层 | 要做什么 | 花钱与否 |
|---|---|---|---|---|
| 1 千 | ~8 | 香港库连接（8 QPS × 2s 持连接 ≈ 16 并发，接近 20 上限） | S1 PgBouncer + 本轮 M2 缓存 | 不花钱（自装） |
| 1 万 | ~80 | 香港库连接与 CPU 同时爆；Vercel Hobby 函数并发不够 | S1 + S2 升库 + Vercel Pro + Redis 共享缓存（候选、公司列表、偏好） | 每月几百元级 |
| 10 万 | ~800 | 2 核库扛不住 28,000 行扫描的搜索；搜索 JS 打分吃函数并发 | 库升 8C16G 或托管弹性 PG + 只读副本；`job_function` 物化列把打分下推 SQL；搜索候选缓存进 Redis | 每月数千元级 |
| 100 万 | ~8,000 | 整体架构 | 搜索换 OpenSearch；用户行为数据进 Redis 集群；jobs 库分片；落地页全 CDN | 重构级 |

Vercel 计划：代码里 `maxDuration=60` 顶着 Hobby 上限，判断当前是 Hobby（未确认，请核）。Hobby 禁止商用，正式收费前必须升 Pro。

---

## 5. 做得好、别误改的地方

- upsert 三条不变量两端一致（`crawler/jobs_db.py:42-74` / `lib/jobs-store/write.ts:75-81`）：expired 黏住、簿记列不在 UPDATE、空值 COALESCE 保旧值。
- 香港库连接自愈：7 次退避重连 + TCP keepalive + 取用前 `live_conn`；guard job 区分「runner 出口被掐」与「库真挂」。
- list-absence 撤岗三道闸（显式开关 + 50% 安全闸 + 观察模式）。
- 每源新建 adapter 实例、每线程独立 Supabase 客户端、按 host 限流。
- 本地 JWT 验签 + 模块级 JWKS 缓存；`/api/jobs/stats` CDN 缓存；campus 页 `unstable_cache`；搜索打分三层记忆化。
- LLM 成本闸 fail-open、先探 LLM 可用再花搜索额度、真实 token 记账。

---

## 6. 本轮执行拆分

- 批 A（TS，Sonnet 子 agent，本工区）：M1 的 app 侧全部文件 + M2 缓存 + 契约测试。
- 批 B（Python，Codex 独立工区）：M1 爬虫侧（insight_backlog / insight_sweep）+ M4 + M5 两处 + 单测。
- 批 C（主 agent）：M3 两个 workflow 改动。
- 验收：四件套 + lint 全绿 → 合并 → push → 线上复核 availability 返回的公司数与洞察数。
