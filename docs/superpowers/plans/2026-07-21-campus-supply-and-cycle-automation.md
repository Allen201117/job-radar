# 校招供给 + 往年时间线 自动化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. 分两轨，Track A 先做（地基、无红线），Track B 后做（洞察、带官方门）。

**Goal:** 让塌陷行业（传媒/物流/教育/金融）的校招数据**自动逐渐覆盖**，不靠人工：① 每日爬虫自动补它们的**校招岗位源**；② 每日 cron 自动补**往年时间线洞察**，只自动发布官方源能核实的（宁缺不编）。

**决策（2026-07-21 创始人拍板）**：时间线走**机器自动发布、无人工**，但**门 = 只发官方源能核实的**（选项 A）——官方招聘域名 grounding + 多源一致才 auto-verify；够不着官方证据的停 `draft`、不展示。覆盖到多少取决于官方页写没写，诚实标注。

## Global Constraints

- **红线不变**：宁缺不编。时间线 auto-verify 必须 ≥1 条 grounding 源的 host 命中该公司官方招聘域名 + judge 判 entailment；否则 `verify_status='draft'`（用户读不到）。绝不把社区搜索推断当"据往年 fact"自动发布。
- **精度门不变（Track A）**：新校招源只入"探活通过 + 真有在招校招岗 + 标题核验防张冠李戴"的，猜错/无岗自动丢（复用现有探活工艺 [[job-radar-must-apply-breakthrough]]）。
- **账单可控**：Track B cron 预算门控（复用 `search_router` 日顶 + SILICONFLOW），每日 drip 少量公司、逐渐补，不一次性 blast。
- **不动已 verified 的官方 seed**：Track B 只新增 observation，不覆盖 183 的 10 家 seed（immutable，改错走 superseded_by）。
- **测试**：纯函数/解析器优先 node --test 或 crawler unittest（不打真实网络）；live 探测单独跑、不进单测。commit 用显式路径，push 等用户指令。

---

# Track A — 校招岗位源接入自动化（先做）

**现状（investigation 实测）**：每日 `auto-discover` 在跑、塌陷行业公司在目标池，但两个洞导致最该补的 ~47 家"有社招无校招"覆盖不到：
1. `plan_targets()` 只探"库里完全没有源"的公司 → 已有社招源的 47 家被去重跳过、永不探校招板块。
2. `discover_domestic.py` 里 **feishu / moka 探测器只探社招板块**（feishu `portal_type:2`、moka `social-recruitment`），没探校招板块。hotjob/wt/beisen 已探校招。

### Task A0: Live 摸清 feishu / moka 校招板块的真实接口（前置，必须先做）

**为什么**：feishu 校招用哪个 `portal_type`（社招是 2）、moka 校招是 `campus-recruitment` 还是 `campus_apply` 路径、返回结构——这些**代码里没有、必须 live 探**。猜接口 = 违反"不猜 slug/板块"红线。

- [ ] 挑 2–3 家已知有 feishu 源、且官网有校招板块的公司（从 `sources` 表查 `source_url like '%feishu%'` 的公司），live 请求其校招板块候选端点（feishu 试 `portal_type:1`/校招 portal、moka 试 `campus-recruitment/{sv}`、`campus_apply`），确认哪个返回真实校招岗 + 返回结构。**用 dangerouslyDisableSandbox + 本机网络**，只读探测、不写库。
- [ ] 把确认到的端点模板 + 返回字段记进 Task A1 的实现依据。若某平台校招板块接口探不通/结构不稳 → **诚实记录，该平台校招探测本轮不做**，不硬猜。

### Task A1: 给 discover_domestic.py 加校招板块探测

**Files:** Modify `crawler/discover_domestic.py`（`feishu_probe` / `moka_probe` / `to_*_candidates`）；Test `crawler/test_discover_domestic.py`（或新增，unittest 不打网络，测候选生成 + 校招 URL 标记）。

- [ ] 按 A0 确认的端点，给 `feishu_probe` 加校招 portal 探测、`moka_probe` 加 campus 路径探测，各自产出**独立的校招源候选**（URL 命中 `CAMPUS_URL_RE`，`notes` 标"校招板块"）。
- [ ] 复用现有探活质量门（`probe_one` / `valid>0` / 标题核验）——校招板块也要"真有在招校招岗"才入。
- [ ] Test：mock 返回，断言校招候选被正确生成 + `isCampusSource` 判定为 true（对齐 `lib/campus-sources.ts` 的 `CAMPUS_URL_RE`）。

### Task A2: auto_discover 加"有源但缺校招源"重探路径

**Files:** Modify `crawler/auto_discover.py`（`plan_targets()` / `existing_source_keys()`）；Test `crawler/test_auto_discover.py`。

- [ ] 新增一条目标路径：对**已在 `sources` 但没有校招源**的必投公司（判定复用 crawler 侧等价于 `lib/campus-sources.ts` 的 hasCampusSource 逻辑：该公司所有 enabled 源里无一命中 `CAMPUS_URL_RE`），把它们放进"补校招板块"探测队列——**绕过**现有 company 级去重（该去重只防"整家重复探"，不该挡"补缺失板块"）。
- [ ] 该队列优先塌陷行业（`industry ∈ {传媒,物流,教育,金融}` 权重高），预算门控（每日限量，drip）。
- [ ] Test：给定"有社招源无校招源"的公司集，断言它们进入重探队列；已有校招源的不进（幂等，不重复补）。

### Task A3: 接线 + 观测

- [ ] 确认两个 `auto-discover*.yml` 会带上新路径（无需改 workflow，若逻辑在 `auto_discover.py` 内）；跑一次 `--dry-run` 看塌陷行业候选产出。
- [ ] 管理员看板"自动扩源"卡能看到校招板块新增（复用现有 discovery 台账，无需新表）。
- [ ] 全量 crawler 回归：`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`。

---

# Track B — 往年时间线每日 cron（后做，带官方门）

**可复用（investigation 实测）**：`insight_engine.py` 的接地→judge→共识管线、`search_router.py` 多源+≥2 publisher 去重、`insight-enrich-t3.yml` cron 模板、新表 182 的 draft/verified/source_kind/confidence/evidence 字段全就绪。缺的是①结构化月份 writer ②官方源门 ③写 RCO 表 ④cron。

### Task B1: 结构化月份 writer + 解析器（纯函数 TDD）

**Files:** Create `crawler/campus_cycle_extract.py`（writer prompt + `parse_cycle_claims(llm_json) → list[dict]`）；Test `crawler/test_campus_cycle_extract.py`。

- [ ] writer prompt（复用 `insight_engine` 的"每条结论必须在来源原文找到支撑 + 引用片段 + 拿不准就不输出"纪律），要求输出 JSON 数组，每条 `{season, batch, event, month_start, month_end, value_text, source_idx, quote}`。season/batch/event 限枚举（同表 CHECK）。
- [ ] `parse_cycle_claims`：校验枚举 + 月份 1–12 + value_text 非空 + 必带 source_idx/quote；非法条丢弃（不 raise）。**纯函数、不打网络、可 unittest**。
- [ ] Test：合法 JSON→结构化 dict；缺 source_idx/quote 丢弃；非法枚举/月份丢弃；空数组→[]。

### Task B2: 官方源门（纯函数 TDD，红线核心）

**Files:** Create `crawler/official_gate.py`（`is_official_grounding(url, company_official_hosts) → bool` + `decide_cycle_status(claim, groundings, judge_verdict) → ('verified'|'draft', source_kind, confidence)`）；Test `crawler/test_official_gate.py`。

- [ ] `is_official_grounding`：grounding 源的 URL host 是否命中该公司官方招聘域名集（来自该公司 `sources.source_url` 的 host ∪ 官网域名）。子域/大小写归一。
- [ ] `decide_cycle_status`：**auto-verify 条件** = judge verdict == entailment（该源原文确实写了这个时间）**且** ≥1 grounding 命中官方域名 → `('verified','official_notice','high')`；否则 → `('draft', 'public_aggregate'/'llm_draft', 'low')`（用户读不到）。
- [ ] Test：官方域名+entailment→verified；只有社区源+entailment→draft；judge neutral/contradiction→draft；无 grounding→draft。**这是宁缺不编的机器落地，测全分支。**

### Task B3: 单公司 drain + 写 RCO 表

**Files:** Create `crawler/campus_cycle_backlog.py`（`drain_one_company(company)`：`search_router` 查"{公司} 校招 提前批 正式批 时间 月份"→ B1 writer → `insight_engine.judge_claim` → B2 门 → 写 `recruitment_cycle_observations`）；复用 `crawler/db.py` / `jobs_db` 无关（RCO 在 Supabase，走 `db.get_supabase()`）。

- [ ] `write_cycle_observation(company_id, claim, status, source_kind, confidence, evidence_url, evidence_excerpt, grad_class, valid_until)`：insert draft/verified 行；`created_by='cron'`；绑当前 `grad_class`（2027届）+ `valid_until=2027-06-30`。
- [ ] 幂等：同公司+季+批次+事件+届别已有 verified → 跳过（不重复插）；draft 可刷新。
- [ ] 预算门控：`search_router.remaining()` 不足则跳过；每次跑限量公司（塌陷行业优先）。

### Task B4: 每日 cron workflow

**Files:** Create `.github/workflows/campus-cycle-enrich.yml`（clone `insight-enrich-t3.yml`：SILICONFLOW + search keys/caps + SUPABASE + timeout；cron 每日一个错峰时段，如 `0 22 * * *`）。

- [ ] 跑 `campus_cycle_backlog.py`，`--limit N`（每日少量）、塌陷行业优先。
- [ ] `workflow_dispatch` 支持手动 + `--company` 单公司现查（调试用）。
- [ ] 失效：RCO 的 RLS 读已过滤过期（`valid_until >= current_date`），无需额外 sweep；每年滚动靠新增下一届 observation（Track B cron 自然产出新届）。

### Task B5: 全量回归 + live 冒烟

- [ ] `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` + `node --test tests/*.test.js` + `npm run build` 全绿。
- [ ] Live 冒烟：`campus_cycle_backlog.py --company <一家官网有校招时间的塌陷行业公司> --limit 1`，确认 verified 只在官方 grounding 时产生、社区源停 draft（**用 dangerouslyDisableSandbox；会耗少量 LLM/search 额度，别反复跑**）。

---

## Self-Review（对照用户诉求）

- **"校招源接上、塌陷行业覆盖"**：Track A 补校招岗位源（A0 live 摸接口→A1 探测器→A2 重探 47 家）。✓
- **"时间线不靠人、自动补"**：Track B 每日 cron 全自动。✓
- **"宁缺不编"守住**：B2 官方源门 auto-verify 只在官方 grounding+entailment；否则 draft 不展示。✓
- **"尽快覆盖全"的诚实边界**：覆盖 = 官方页写了时间的那些；写了就自动长出，没写停 draft。Track A 让活校招岗照样出现（不依赖时间线）。✓
- **红线决策来源**：官方门 = 创始人 2026-07-21 选项 A。✓

**诚实风险**：① Track A 的 feishu/moka 校招接口需 live 摸（A0），摸不通的平台本轮不做、不硬猜；② Track B 塌陷行业官方页常不写"提前批7月"→ 自动覆盖可能偏低（这正是宁缺不编的代价，用户已知情选 A）；③ live 步骤耗额度，不进单测、单独节制跑。
