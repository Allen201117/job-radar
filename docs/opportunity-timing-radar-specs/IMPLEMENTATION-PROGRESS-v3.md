# v3 实现进度（draft/radar-pivot-0623）

> 起：2026-06-24。按 06-实现入口 的 Phase 顺序执行。基线已并 origin/main（拿到 spec + 过滤修复）。
> 三不变量不破：expired sticky / summary preserve-if-empty / enrich_checked_at 不被列表重抓覆盖。

## Phase 1 — 护城河（最高优先，01 spec）
- [ ] 1.1 `lib/opportunities/freshness.ts` 加 `meetsVerifyTier(job, tier, now)` + `VerifyTier` 类型
- [ ] 1.2 `Job.enrich_checked_at` / `confirmed_closed_at` 入 `lib/types.ts`；recall payload 带 `enrich_checked_at`
- [ ] 1.3 `service.ts` today 主清单硬门接 `meetsVerifyTier(today)`
- [ ] 1.4 单岗点击核验 API `POST /api/jobs/[jobId]/liveness`（封顶 2.5s、三态、判死写 expired+confirmed_closed_at）
- [ ] 1.5 `lib/liveness-client.js` SPA 轻量信号扩展；`/api/jobs/liveness-check` 覆盖 SPA
- [ ] 1.6 前端点击 handler：临门核验（非阻塞）+ 埋点 `opportunity_official_opened` / `job_liveness_at_click`
- [ ] 1.7 点击有效率指标聚合 + admin/health 四护栏展示
- [ ] 1.8 `crawler/audit_dead_links.py` `--prioritize-new`
- [ ] 1.9 测试：freshness-verify-tier / click-validity-metric / test_audit_prioritize_new

## Phase 2 — 强度自调（03/04 spec）
- [ ] 2.1 迁移 164 `radar_intensity` 等三列
- [ ] 2.2 类型扩展 types.ts：RadarIntensity / OpportunitySignal* / 扩展 Opportunity/Feed
- [ ] 2.3 `lib/opportunities/intensity.ts` `resolveIntensity`
- [ ] 2.4 `profile.ts` readiness 城市非硬门（`ready = hasContent`）
- [ ] 2.5 `/api/preferences` 读写 radar_intensity + user_id 拒绝 + 503 错误码
- [ ] 2.6 `grouping.ts` 按身份×强度动态分区，关键提醒不被截断
- [ ] 2.7 onboarding 问两句（身份 + 强度）
- [ ] 2.8 测试：opportunity-intensity / profile-readiness / preferences-intensity / grouping

## Phase 3 — 时间记真 + 信号标签（02/04 spec）
- [ ] 3.1 `lib/opportunities/deadline.ts` `parseDeadline`
- [ ] 3.2 `lib/opportunities/signals.ts` `deriveOpportunitySignals`（STILL_OPEN/DEADLINE_SOON/CLOSED_OR_STALE/CAMPUS_WINDOW；NEWLY_DISCOVERED/MOMENTUM 暂不上 — 依赖 job_events）
- [ ] 3.3 `normalizer.extract_jobposting_ld`（JSON-LD JobPosting → posted_at/deadline）
- [ ] 3.4 jobs-db schema `confirmed_closed_at` + `job_events`（append-only）
- [ ] 3.5 `crawler/jobs_db.py` + `lib/jobs-store/write.ts` 写 job_events（best-effort、按天去重、expired 不复活）
- [ ] 3.6 防假动量守则纯函数 + 测试
- [ ] 3.7 测试：opportunity-deadline / opportunity-signals / test_jobposting_ld / test_jobs_db_events / test_momentum_guard

## Phase 4 — 发现/保鲜分流 + 运维硬化（01/02 spec）
- [ ] 4.1 `daily-crawl.yml` 卸内联 sweep；保鲜交独立 workflow
- [ ] 4.2 enrich_backlog 源级失败自适应（高 miss% 降并发/跳过 + warning）
- [ ] 4.3 db-report 加核验覆盖率（按 adapter 的 enrich_checked_at 年龄分布）

## 必跑验证
`node --test tests/*.test.js` · `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` · `npm run build` · `git diff --check` · `bash scripts/check-migrations.sh`
</content>
</invoke>
