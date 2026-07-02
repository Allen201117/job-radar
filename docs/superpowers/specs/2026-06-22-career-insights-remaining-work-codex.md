# 职业洞察（Module B）— 剩余工作 spec（交 Codex 执行）

> 目标读者：Codex（不掌握此前对话上下文，需自包含）。
> 写于 2026-06-22。承接已完成的 v2.1 供给升级 + v2.2 Tier-1 内容扩面（见 `docs/superpowers/specs/2026-06-20-career-insights-supply-upgrade-design.md` §11）。

## 0. 先读：项目铁律（每项都必须遵守）

1. **TDD**：先写失败测试 → 看它失败 → 最小实现转绿。crawler 用 `unittest`，前端/lib 用 `node --test`。
2. **单测不打真实网络**：crawler adapter/HTTP 用 mock；纯函数（解析/分类/预算）直接测。TS lib 经 `tests/*.test.js` 的 `loadTsModule`（即时转译）测。
3. **合规线不放松**：官方源=`fact`；搜索源=去标识群体聚合 + LLM 判官核验 + ≥2 独立 publisher 共识；**不直接爬社区**（脉脉/知乎/小红书等），只走搜索 API 前门。`lib/insight-verification.ts` + `crawler/insight_engine.py` 的闸门不得放松。
4. **禁猜入库**：官方源的返回格式**没经 live 验证前**，一律 `gated` 默认关（env 开关），不写生产事实。
5. **迁移**：放 `supabase/migrations/`，前缀纯数字递增（先 `ls` 确认未占用），push 后 `migrate.yml` 自动 apply，勿手动跑 SQL。
6. **提交回归四件套**：`node --test tests/*.test.js` + `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` + `npm run build`（或 `npx tsc --noEmit`）+ `git diff --check`。
7. **文档同步**：改完更新 `CLAUDE.md` 相关段 + 在本 spec 对应项打勾；每项独立 commit；**push 等用户指令**。
8. **jobs 热表在自建香港 Postgres**（`JOBS_DATABASE_URL`，`lib/jobs-store/` 边界），**洞察表（company_profiles / insight_items / insight_sources / …）在 Supabase**。别混。

## 1. 当前状态锚点（Codex 先看这些文件了解现状）

- `lib/insight-derive.ts` — T1 派生（读时现算）：`deriveTiming` / `deriveHiring`（含 `classifyHiringSignal` 大小年信号 + `payload.hiring_signal`）/ `deriveSalaryBand` / `deriveCompanyInsights(jobs, now, opts)`。opts.headcountBand 已接入。
- `crawler/insight_backlog.py` — T2/T3 drain。T3 已是**多维查询包** `T3_QUERY_PACK`（加班文化/实习体验/年终奖/晋升/面试难度 → 各维度 culture/comp/path/hiring），`enrich_company_t3` 逐主题检索 + replace-on-refresh 跨维度退役；`write_experience(…, dimension, topic)`。`enrich_company`（T2）顺序 = EDGAR(美股 ticker) → 巨潮(A股名,gated) → Wikidata 回落。
- `crawler/official_edgar.py` — SEC EDGAR：`get_listing_by_ticker`（ticker→CIK→submissions→listing）+ `financials_from_companyfacts`（XBRL 营收/净利/同比/员工，折进同一 listing item 的 content + `payload.financials`）。
- `crawler/official_cninfo.py` — 巨潮 A 股：`get_listing_by_name` / `find_stock` / `exchange_from_code`。**默认关**（`INSIGHT_CNINFO_ENABLED`）。
- `crawler/search_router.py` — 多源搜索路由（博查/Tavily/Serper/千帆），各源日顶 `search_usage`（迁移 156），默认免费安全档。
- `crawler/insight_engine.py` — 接地→writer 抽取→judge entailment→共识 的验证引擎（纯决策 `decide_status/consensus_ok/final_status` 可单测）。
- `crawler/insight_sweep.py` + `insight-staleness-sweep.yml` — 过期下架（`valid_until` 过期→retired）。
- `lib/insight-verification.ts` / `lib/insight-bundle.ts` / `components/CompanyInsightDrawer.tsx` / `app/api/insights/route.ts` — 校验门 / 分组 / 抽屉渲染 / 读写 API。
- 五维 `dimension`：`timing / hiring / listing / compensation_intensity / path / culture`（CHECK 约束在迁移 013/023/135）。

---

## 2. 工作项（按优先级；每项独立可做、独立 commit）

### ☐ W1. 抽屉渲染 hiring_signal + financials 芯片（小·快赢·先做）

- **目标**：让已产出的「大小年信号」和「业绩」在 UI 显眼可见（现在只在正文文本里）。
- **现状**：大小年在 `payload.hiring_signal = {momentum: expanding|steady|tightening, intensity?: high|mid|low, trend, active_count}`；业绩在 listing item 的 `payload.financials = {fy, revenue, net_income, revenue_yoy_pct, employees}`。抽屉只渲染 `content` 文本、无专门芯片。
- **做法**：`components/CompanyInsightDrawer.tsx` 里，hiring 维度卡渲染 hiring_signal 芯片（扩张=绿/收紧=橙/平稳=灰 + 强度标）；listing 维度卡渲染 financials 芯片（营收/同比±%/员工数）。**照抄现有 listing 的 `QuoteLink` / equity-angle chip 渲染模式**（同文件内已有）。芯片文案短、金额用 B/M 缩写（参考 `official_edgar._fmt_usd`）。
- **测试**：前端展示为主，不强制单测；`npx tsc --noEmit` + `npm run build` 绿。
- **验收**：真机抽屉里，招聘动态卡有大小年芯片、上市卡有业绩芯片。

### ☐ W2. 巨潮 A 股源 live 验证 + 启用（小·需 live 网络）

- **目标**：把已建好但默认关的巨潮 A 股官方源开起来。
- **现状**：`crawler/official_cninfo.py` 完整、单测过，但 `INSIGHT_CNINFO_ENABLED` 默认关（守禁猜入库，因沙箱无法 live 验证 `szse_stock.json` 返回格式）。
- **做法**：① live 拉 `http://www.cninfo.com.cn/new/data/szse_stock.json` 确认结构含 `stockList:[{code,zwjc,orgId}]`；② 跑 `find_stock` 验证匹配正确（比亚迪→002594 深交所、顺丰控股→002352）；③ 结构相符 → 在 repo Variables 置 `INSIGHT_CNINFO_ENABLED=true`（`insight-enrich.yml` 已映射）；④ 结构不符 → 修 parser（**保持严格匹配防误配**：exact zwjc 或去后缀相等）。
- **验收**：dispatch `insight-enrich` 后，A 股公司出正确 listing 官方事实（`source_publisher=巨潮资讯`）。
- **注**：Codex 若无 live 网络 → 标注「需人工 live 验证后启用」，勿盲开。

### ☐ W3. 真·年度大小年（中·部分依赖数据累积）

- **目标**：把「当前窗口」招聘信号升级为「今年 vs 往年」年度大小年。
- **现状**：`classifyHiringSignal(activeCount, trend, headcountBand?)` 只给「近月扩张/收缩 + 相对规模强度」，非年度周期（诚实边界已在代码注释里）。
- **做法**（分两小步，a 可立刻做、b 依赖历史）：
  - **a（立刻）**：EDGAR 已抓的官方员工数 `payload.financials.employees` → 在 `crawler/insight_backlog.enrich_company` 里更新 `company_profiles.headcount_band`（用 `crawler/wikidata.headcount_band(n)` 分档；官方数比 Wikidata 更准）→ 喂给读时的 `classifyHiringSignal` 让相对强度更准。
  - **b（搭结构，等数据）**：建轻量月度聚合表（迁移：`company_hiring_monthly(company, ym, posted_count, primary key(company,ym))`）；每日 crawl 链路增量累加当月发岗数；`classifyHiringSignal` 加「同比」维度（本年 vs 去年同期），数据不足一年时**仍标当前窗口**、够一年才升级为年度。
- **文件**：`lib/insight-derive.ts`（YoY 分支）、`crawler/insight_backlog.py`（employees→headcount）、新迁移、crawl 写入链路（月度累加）。
- **测试**：`classifyHiringSignal` YoY 分支纯函数单测（tests/insight-derive.test.js，用 `loadTsModule`）；月度聚合纯函数单测。
- **验收**：有 ≥1 年历史的公司显示「今年 HC 较去年 +/−N%」；不足一年的仍显示当前窗口信号。
- **注**：短期只交付 a + 搭 b 的表；b 的年度判定等历史攒够再激活（避免假 YoY）。

### ☐ W4. 现查快车道②（中·成本敏感）

- **目标**：用户点开无洞察的公司，几分钟内出洞察（而非等到明天 cron）。
- **现状**：Phase 3 只做了「队列提前」（`app/api/insights` GET 对有岗无画像的公司建占位入队，等每日 drain）；快车道②（单公司即时 dispatch）延期。
- **做法**：`app/api/insights` GET（或新 `/api/insights/enrich-now`）对用户主动点开、且无新鲜洞察的公司，发 `workflow_dispatch` 单公司富化（复用 `/api/refresh` 的异步轨道 + `GITHUB_DISPATCH_TOKEN`+`GITHUB_DISPATCH_REPO`）。**严格节流幂等**：N 小时内已富化的不重发、全局每小时封顶 ≤N 家（防成本失控）；记录到 `discovery_runs` 或 `ops_runs`。workflow 接受单 company 入参，跑 `insight_backlog` T2+T3 单公司。
- **测试**：节流/幂等纯函数单测（是否该 dispatch 的判定）。
- **验收**：点开新公司 → 数分钟内洞察出现；重复点击不重复 dispatch；每小时不超上限。
- **注**：**别每次点击都 dispatch**——成本敏感，节流是硬要求。

### ☐ W5. 港交所（HKEX）港股官方源（中·先研究端点·可能不做）

- **目标**：补港股上市官方确认（比亚迪/众多中概港股）。
- **现状**：延期。官方「List of Securities」是 xlsx / 不稳定 AJAX，需新依赖；且 Wikidata 已覆盖多数港股 listing。
- **做法**：先研究 HKEX 是否有**稳定 JSON 端点**拿「港股代码 + 名称」。有 → 仿 `official_cninfo` 做 `crawler/official_hkex.py`（名→港股 5 位代码→listing official），接进 `enrich_company` 顺序（EDGAR→巨潮→HKEX→Wikidata），**gated 默认关**待 live 验证。无稳定端点/需重依赖 → **不做**，维持 Wikidata 兜底，并在本项标注「不做及原因」。
- **注**：禁猜入库；不引重型依赖（别为 xlsx 引 openpyxl，除非确无 JSON 途径且用户批准）。

### ☐ W6. A 股业绩（巨潮财务·中·需 live 验证）

- **目标**：给 A 股公司也补业绩（营收/净利/员工），对齐 EDGAR 美股业绩。
- **现状**：业绩只做了 EDGAR（美股）。
- **做法**：研究巨潮/交易所是否有 A 股财务数据接口 → `official_cninfo` 加财务解析，折进 A 股 listing item 的 content + `payload.financials`（**照 EDGAR 折进 listing 的同一模式**）。随 `INSIGHT_CNINFO_ENABLED` gated。
- **注**：端点格式必须 live 验证；禁猜入库。

### ☐ W7. 第一方「给-取」众包（大·护城河·建议单独立项）

- **战略意义**：这是「想要社区高赞帖价值」的**合规终极答案 = 自己当社区**（Glassdoor/Levels.fyi/Blind/脉脉皆此模式：用户主动交、给-取解锁）。见记忆 `job-radar-insights-crowdsourcing-deferred`。
- **设计**（Codex 需完整实现，建议分阶段）：
  - **数据**：新迁移 `insight_submissions`（用户匿名提交：company / dimension / grade / 结构化字段[评分+短文本] / status[pending|approved|rejected] / user_id / created_at）；审核通过后转成 `insight_items`（`origin='first_party'`）入现有展示池，过 `insight-verification` 门（去标识、聚合 ≥N 条才展示防单点偏见）。
  - **提交 UI**：`CompanyInsightDrawer` 加「我来贡献」结构化表单——维度选择（实习体验/入职体验/年终奖/面试难度/文化/晋升）+ 评分 + 短文本，匿名；登录用户，可选在职/邮箱验证。
  - **给-取解锁**：未贡献者看摘要、**贡献 ≥1 条才解锁**看全部经验洞察（Glassdoor 机制）。
  - **审核**：admin 后台看 `pending` 提交（复用 `/admin/insights` 模式 + service-role 写）。
  - **冷启动**：先用现有搜索聚合内容垫底，逐步转第一方。
  - **合规**：知情同意（用户提交自己的经历）、去标识、不针对个人、不展示可反识别信息。
- **文件**：新迁移、`app/api/insights/submit`（+ 解锁门 API）、`components/`（提交表单 + give-to-get 门）、admin。
- **分阶段建议**：P1 提交+审核+展示 → P2 give-to-get 解锁 → P3 在职验证/信誉。
- **注**：**这是最大项，建议单独立项**、不与 W1–W6 混做。

---

## 3. 交付顺序建议

W1（快赢，先做）→ W2（开巨潮，需 live）→ W3a（employees→headcount）→ W4（现查快车道）→ W5/W6（需研究+live，可并）→ W7（单独立项）。

每项：TDD → 四件套绿 → 同步 `CLAUDE.md` + 本 spec 打勾 → 独立 commit → push 等用户指令。
