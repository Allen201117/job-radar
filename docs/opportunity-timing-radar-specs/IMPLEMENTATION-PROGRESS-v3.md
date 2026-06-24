# v3 实现进度（draft/radar-pivot-0623）

> 起：2026-06-24。按 06-实现入口 的 Phase 顺序执行。基线已并 origin/main（拿到 spec + 过滤修复）。
> 三不变量不破：expired sticky / summary preserve-if-empty / enrich_checked_at 不被列表重抓覆盖。

## Phase 1 — 护城河（最高优先，01 spec）✅ 基本完成
- [x] 1.1 `freshness.ts` `meetsVerifyTier` + `VerifyTier`
- [x] 1.2 `Job.enrich_checked_at`/`confirmed_closed_at` 入类型；recall payload 带 `enrich_checked_at`
- [x] 1.3 today 主清单硬门（service 派生 STILL_OPEN 需 ≤24h 核验，否则落 waiting）
- [x] 1.4 单岗点击核验 API `POST /api/jobs/[jobId]/liveness`（封顶 2.5s、三态、判死写 expired+confirmed_closed_at）
- [ ] 1.5 `lib/liveness-client.js` SPA 轻量信号扩展（**未做**：现仍只 wt/hotjob/workday，SPA 接口级探活属 02 §3.1 延期项）
- [x] 1.6 前端点击 handler：瞬开 + `opportunity_official_opened` + 背景核验（服务端打 `job_liveness_at_click`）
- [x] 1.7 点击有效率四护栏聚合 + admin/health 展示
- [x] 1.8 `audit_dead_links.py --prioritize-new`
- [x] 1.9 测试：freshness-verify-tier / click-validity-metric / test_audit_prioritize_new

## Phase 2 — 强度自调（03/04 spec）✅ 完成
- [x] 2.1 迁移 164 `radar_intensity` 三列
- [x] 2.2 类型扩展（RadarIntensity / OpportunitySignal* / Opportunity/Feed）
- [x] 2.3 `intensity.ts` `resolveIntensity` + `resolveIntensityForUser`
- [x] 2.4 `profile.ts` 城市非硬门（`ready = hasContent`）
- [x] 2.5 `/api/preferences` 读写 radar_intensity + 拒 user_id + 503 错误码（preferences-input 纯函数）
- [x] 2.6 `grouping.ts` 按身份×强度动态分区，关键提醒不截断
- [x] 2.7 偏好页强度开关（active/passive）；onboarding 身份问句沿用既有
- [x] 2.8 测试：opportunity-intensity / profile-readiness / preferences-intensity / grouping

## Phase 3 — 时间记真 + 信号标签（02/04 spec）部分
- [x] 3.1 `deadline.ts` `parseDeadline`
- [x] 3.2 `signals.ts` `deriveOpportunitySignals`（STILL_OPEN/DEADLINE_SOON/CLOSED_OR_STALE；NEWLY_DISCOVERED/MOMENTUM 暂不上）
- [ ] 3.3 `normalizer.extract_jobposting_ld`（**未做**）
- [x] 3.4 jobs-db schema `confirmed_closed_at` + `job_events` 表（建表/列已加，待 jobs-db-migrate 应用）
- [ ] 3.5 `jobs_db.py`/`write.ts` 写 job_events（**未做**）
- [ ] 3.6 防假动量守则（**未做**；MOMENTUM 未上 C 端，无紧迫）
- [x] 3.7 测试：opportunity-deadline / opportunity-signals（jobposting_ld/jobs_db_events/momentum_guard 待 3.3/3.5/3.6）

## Phase 4 — 发现/保鲜分流 + 运维硬化（01/02 spec）未做
- [ ] 4.1 `daily-crawl.yml` 卸内联 sweep；保鲜交独立 workflow
- [ ] 4.2 enrich_backlog 源级失败自适应
- [ ] 4.3 db-report 加核验覆盖率（按 adapter enrich 年龄分布）

## 其它已满足（A–E 既有，复核通过）
- 普通用户主动爬取入口已 `MANUAL_CRAWL_UI_ENABLED` 门控（jobs-client）。
- Landing 文案已 v3（企业官网直达 / 持续确认仍在招 / 撤岗自动下架），无禁用绝对词。
- 文案禁用词扫描（§1）干净（仅「不做自动投递」等否定式声明）。

## 待 live（沙箱无法验，须用户本机/CI）
- `gh workflow run jobs-db-migrate`（应用 confirmed_closed_at + job_events 到香港库）后才生效。
- 迁移 164 push 到 main 自动应用。
- 真实点击有效率数字、单岗核验真探活：需线上 events + 香港库。

## 必跑验证
`node --test tests/*.test.js` · `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` · `npm run build` · `git diff --check` · `bash scripts/check-migrations.sh`
</content>
</invoke>
