# 06 实现入口：给实现 agent 的指引 v3

> 日期：2026-06-24
> 用途：把本文件 + 下列权威文档完整交给实现 agent。
> 取代：`2026-06-24-opportunity-timing-radar-agent-implementation-prompt.md`（Codex 三模式版）。

---

## 你的任务

把求职雷达落成 v3 方向：**一份"刚核验还在招、适合你"的官网机会清单**，核心护城河是"极少死岗"。**不要 sprint/watch/campus 三模式。**

权威文档（按此为准，旧文档只作背景）：

1. `产品方向v2-岗位保鲜雷达.md`（v3，地基）
2. `01-保鲜与运维硬化-spec.md`（**最重要**，护城河实现）
3. `02-抓取重构方向-spec.md`
4. `03-产品规格v3.md`
5. `04-技术规格v3.md`
6. `05-验收规格v3.md`（实现完照它自测）

---

## 实现基线（先看清楚再动手）

```bash
git status --short
git branch --show-current
ls supabase/migrations | sort | tail -8        # 主分支止于 159
```

- **6/23 pivot 产物在 `draft/radar-pivot-0623` 分支**：已含 `lib/opportunities/`（types/service/eligibility/scoring/grouping/profile/freshness/...）、`/api/opportunities|preferences|radar/open|company-watch|job-actions/[jobId]`、迁移 160–163、`classifyRecruitment`（`lib/insight-derive.ts`）、`company-industry.js`。
- **基于该分支扩展，不要重写**。身份已用 `experience_stage`、已无三模式——与 v3 一致。
- 新 Supabase 迁移从 **164** 起；jobs-db 改动走 `jobs-db/schema.sql` + `gh workflow run jobs-db-migrate`。

---

## 最高优先级原则

**必须做**：
- 身份（实习/校招/社招，来自 `experience_stage`）× 强度（active/passive，可手动 + 行为自调）取代模式；
- 强度只调日常推荐，**关键提醒（快截止/收藏岗关闭/校招通道开放）永远响**；
- 分层核验 SLA（today 24h / search 72h / 点击前临门 / admin 更宽，见 01 spec §2）；
- 点击有效率埋点（01 spec §5）——这是核心指标的前提；
- 信号当标签（STILL_OPEN 主力；NEWLY_DISCOVERED 仅官方 `posted_at` 可用时；动量不上 C 端）；
- ignored 必须 reason_code；普通用户主动爬取入口降级；
- 所有用户写入走鉴权 API，不接受客户端 user_id；feed 失败 503 不假成功。

**禁止做**：
- 不加 `radar_mode` / sprint/watch/campus；
- 对外不写"没有死岗(绝对)/全网最快/BOSS 没有/刚发布(仅 first_seen)"；
- 不展示岗位内容变更/重新开放；不做自动投递；
- 不引入向量库/Redis/队列/LLM 排名；不大规模铺源；
- 不把核验做成阻塞点击的长等待（>2.5s）；
- **不破坏三不变量**：expired sticky / summary preserve-if-empty / `enrich_checked_at` 不被列表重抓覆盖。

---

## 执行顺序（顺序闸：先护城河，后辅助）

> 方向 v3 §8：辅助信号在护城河做到滴水不漏前，只当便宜标签，不当工程项目投入。

**Phase 1 — 护城河（最高优先，01 spec）**
- 分层核验 SLA：`lib/opportunities/freshness.ts` 加 `meetsVerifyTier`；today 主清单接它；
- 点击前临门核验（非阻塞）+ liveness-check 扩 SPA 轻量信号；
- 点击有效率埋点（events：`opportunity_official_opened` / `job_liveness_at_click`）+ admin/health 展示；
- SPA 源新岗优先核验（`audit_dead_links --prioritize-new`）+ 自建源死亡标记核实。

**Phase 2 — 强度自调（03/04 spec）**
- 迁移 164 加 `radar_intensity` 等列；`/api/preferences` 读写强度；
- `lib/opportunities/intensity.ts` 的 `resolveIntensity`；onboarding 问两句；
- 分区按身份×强度动态生成（`grouping.ts`），关键提醒不被截断。

**Phase 3 — 时间记真 + 信号标签（02/04 spec）**
- `normalizer.extract_jobposting_ld` 抽官方 `datePosted`/`validThrough`；源能力盘点；
- `posted_at` 语义厘清、`confirmed_closed_at`、`job_events`（里程碑，按天去重，写失败不影响 upsert）；
- 信号派生：STILL_OPEN / DEADLINE_SOON / CLOSED_OR_STALE 上；NEWLY_DISCOVERED 仅官方 posted_at；防假动量守则。

**Phase 4 — 发现/保鲜分流 + 运维硬化（01/02 spec）**
- `daily-crawl.yml` 卸掉内联 sweep，保鲜交独立 workflow 按 SLA 调频；
- 便宜信号优先核验；源级失败自适应；db-report 加核验覆盖率。

> Phase 1+2 是产品可用最小闭环；3+4 是护城河做厚 + 长期可靠。时间紧不得牺牲 Phase 1。

---

## 必跑验证

```bash
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
npm run build
git diff --check
bash scripts/check-migrations.sh   # 若动迁移
```

不把未运行写成通过；不用 mock 冒充真实 DB 写成功；feed 失败不返回假 ok。

---

## 交付说明须写清

1. 实现了哪些文件 / 哪些 Phase；
2. 身份×强度如何生效、强度如何自调；
3. 分层核验 SLA + 点击有效率埋点是否接通（没接要标明，验收对应项不得宣称通过）；
4. 哪些信号已上（STILL_OPEN/DEADLINE/CLOSED 必上；NEWLY_DISCOVERED/动量状态）；
5. 是否做了 `job_events` / 结构化数据解析；
6. 普通用户主动爬取入口如何降级；
7. 测试命令与结果；已知未完成项；如何手动验收。

必须明确写：**未对外承诺"没有死岗(绝对)"；未展示岗位内容变更；未引入三模式。**
