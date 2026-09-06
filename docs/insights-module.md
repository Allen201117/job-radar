# 模块 B 职业洞察层 · 细节

> ⚠️ **优先级：本文是「归档细节」，与 `CLAUDE.md` 冲突时一律以 `CLAUDE.md` 为准。**
> 红线看正文，这里只查数字、来由和个案；正文更新后本文可能滞后，别拿它推翻正文。

> 从 `CLAUDE.md` 拆出来的模块内部细节，原文照搬未改一字。
> **做洞察模块（供给 / 展示 / 后台 / 检索额度）之前必读本文**；CLAUDE.md 正文只留合规红线。

### 模块 B 职业洞察层（migration 013/014，与岗位层严格分离）

| 表 | 用途 | 权限 |
|---|---|---|
| company_profiles | 公司画像（company 唯一 + aliases 对齐 jobs.company） | 所有人读，admin/service 写 |
| insight_items | 洞察条目（dimension/grade/content/时效/payload） | 读仅 `active+deidentified`，admin/service 写 |
| insight_sources | 溯源（链接 + 短摘要，禁整段原文） | 读仅 `deidentified`，admin/service 写 |
| insight_item_sources | 条目↔来源 多对多 | 所有人读，admin/service 写 |
| insight_disputes | 通知-删除申诉（§7.3） | 用户可插/读自己，admin 读全部+改状态 |
| company_hiring_monthly | 月度招聘量聚合结构（年度大小年历史底座；数据不足一年时不得用于 YoY 结论） | service_role 写，admin 读 |

五维 `dimension`：`timing`(事实为主) / `listing`(上市/股票，事实，migration 023/024，易变行情不落库数字只存 payload.quote_url 链接) / `compensation_intensity` / `path` / `culture`(做浅重免责)。
AI 辅助录入：`/api/insights/admin/ai-draft`（仅 admin、单次 LLM 调用、复用 lib/llm，产出仅草稿强制 status=retired，必人工核对+补真实来源过门后才展示；不进 cron、不按用户触发，控账单）。
三级 `grade`：`fact`(须带来源) / `experience`(须 sample_size≥5 且多源) / `rumor`(默认拦截)。
展示前必过 `lib/insight-verification.ts` 的分级/时效/去标识/归因门；无可信结果返回 `insight_unverified` / `insight_outdated`。
**数据来源（v2.0 三层供给）= T1 派生（自有岗位库现算 timing/hiring/salary，读时零成本）+ T2 官方事实（Wikidata + SEC EDGAR 上市，cron）+ T3 经验（多源搜索 `search_router`→判官核验，cron）+ 人工策展 seed/admin 录入。合规线不变：官方源=fact、搜索源=去标识聚合+判官+≥2源，不直接爬社区；admin AI 辅助草稿仍须人工核对过门才展示。** **供给自动化（2026-06-20 升级，2026-07-02 补现查快车道）**：T3 检索多源化（`search_router`，见「百度千帆额度」段）；T2 加 SEC EDGAR 官方上市源；**现查触发**（`/api/insights` GET 对有在招岗位但无新鲜存储型洞察的公司，先幂等 upsert 画像，再按 `INSIGHT_ENRICH_COOLDOWN_HOURS` / `INSIGHT_ENRICH_HOURLY_CAP` 通过 `discovery_runs(mode='insight_enrich')` 节流台账触发 `insight-enrich.yml` 单公司 `workflow_dispatch`；workflow 跑 `insight_backlog.py --company` 的 T2 + T3，缺 service role/GitHub dispatch 配置时只返回 `enrich_now.skipped`，不影响抽屉展示）；**过期下架**（`insight-staleness-sweep.yml` 每日把 `valid_until` 过期的 active → retired，治「又旧」）；**即时性窗**（搜索四源统一限**近 3 年**：Tavily `start_date`/Serper `tbs` 加时间窗，千帆/博查本就 ≤1 年；T3 经验洞察写入带 `valid_until`=+1 年 → 过期巡检自动退役、180 天复核续期；重富化先退役旧代 public_web culture，不堆积老聚合）。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。 014 种子为待人工核实草稿；015 已用真实公开链接核验 experience 来源；016 把 culture 的「（避坑提示）」改「温馨提示」、9 条 experience 正文改通俗（去掉逐条媒体罗列，正文只留一句轻量归因「据公开讨论/据公开报道」以过 `passesAssertionLint`，统一「来源聚合·去标识」声明只在抽屉顶部 banner 出现一次）。抽屉会把 `payload.hiring_signal` 渲染为招聘动态芯片，把 listing `payload.financials` 渲染为业绩芯片。
**日常维护全程网页、零 SQL**：admin 在 `/admin/insights` 增/改/下架洞察、贴来源、处理申诉（走 `/api/insights/admin` + `/api/insights/dispute/resolve`，service-role 写、必过校验门）；在 `/sources` 用「添加源」表单加招聘源（走 `/api/sources`）。`adapter_name` 取值见 `lib/source-adapters.ts`（须与 `crawler/run.py` 的 ADAPTERS 对齐；greenhouse/lever 是通用 ATS，填公司名+ATS 地址即可）。

## 百度千帆额度

免费「百度搜索」每日 50 次。控制台 0/50 或未付费时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，`/api/discovery` 直接返回 `provider_rate_limited` / `rate_limited=true`，前端稳定展示不崩。额度耗尽时不要反复点「发现」或跑 5-query live 验证。

**职业洞察 T3 检索已扩为多源路由**（`crawler/search_router.py`：博查/Tavily/Serper/千帆，配哪个 key 用哪个、未配自动跳过、各源 `*_DAILY_CAP` 日顶走 `search_usage` 表 + 迁移 156；**免费额度保守日顶**=代码默认 tavily 30 / serper 20 / bocha 50、千帆 40，**绝不一次性用完**［Serper 2500 为一次性总额、Tavily 1000/月、千帆 50/天每日重置=常驻主力］，可在 repo Variables 上调）。千帆仍受上面 50/天全局额度（`qianfan_usage`），但**不再是唯一检索源** → T3 富化吞吐不再被它单独卡死。新增 env（GitHub Secrets + 本地 `.env.local`）：`BOCHA_API_KEY` / `TAVILY_API_KEY` / `SERPER_API_KEY`（+ 可选 `*_DAILY_CAP`）。合规不变：仍只走搜索 API 取去标识聚合 + 判官核验 + ≥2 源，不直接爬社区。设计见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md`。

