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
- [~] 3.3 JSON-LD 接线（2026-06-25）：抽取器 `extract_jobposting_ld` + 优先级合并器 `resolve_official_times`
      （**官方 JSON-LD > adapter 直填 > 正文正则**；posted_at 刻意不取正文正则=§4 官方 only）已就绪+测好。
      **逐源能力 live 盘点**见 `source-jsonld-capability.md`：服务端 JSON-LD 实测**只在 Workday 外站 HTML + HSBC**，
      国内 SPA 源（moka/zhiye/hotjob/feishu/byd/meituan/vivo/163/ctrip…）全 JS 渲染抓不到、greenhouse 板页亦转 JS。
      ⏸️ **逐源 HTML 抓取接线暂缓**：唯一有 JSON-LD 的 workday 富化抓的是 cxs JSON 非 HTML，要 JSON-LD 得额外抓 HTML；
      而消费方 `NEWLY_DISCOVERED` 未上 C 端（热路径零收益加抓取不划算）→ 待其激活时按能力表给 workday 接线。
- [x] 3.4 jobs-db schema `confirmed_closed_at` + `job_events` 表（建表/列已加，待 jobs-db-migrate 应用）
- [x] 3.5 job_events 写入：`jobs_db.py` 纯 planner（plan_upsert_events/plan_close_event/plan_confirm_event）+ best-effort
      record_job_events + 接进 upsert_jobs_batch（FIRST_SEEN/OFFICIAL_POSTED/REAPPEARED，expired 不复活、按天去重、写失败不影响 upsert）；
      `write.ts` markJobExpiredById 记 CLOSED；`enrich_backlog.drain()` 巡检撤岗 → 批量记 CLOSED（best-effort，expired-only 低量）。
      ⏳ 仍缺：CONFIRMED_OPEN（每日 sweep 按天会 1 条/活岗 → 量大且无消费方，待 momentum 上线再开）、write.ts upsert 路径 FIRST_SEEN/REAPPEARED（planner 口径一致，thin wiring）。
- [ ] 3.6 防假动量守则（**未做**；MOMENTUM/NEWLY_DISCOVERED 未上 C 端，无紧迫）
- [x] 3.7 测试：opportunity-deadline / opportunity-signals / test_jobposting_ld / test_jobs_db_events（momentum_guard 待 3.6）

## Phase 4 — 发现/保鲜分流 + 运维硬化（01/02 spec）✅ 完成（待 live 验证 CI 跑通）
- [x] 4.1 `daily-crawl.yml` 卸内联 12k sweep；保鲜交 `liveness-sweep.yml`（提频到 4/12/20 UTC 3×/日）
      + 新增 `dead-link-audit-new.yml`（SPA 新岗 `--prioritize-new` 每 6h 小批，01 §3.1）
- [x] 4.2 enrich_backlog 源级自适应：`should_trip_adapter`（miss 率超线熔断该 adapter 本轮剩余 + warning，不默默失败）
- [x] 4.3 db-report 加核验覆盖率：2b 段（enrich_checked_at 年龄累计桶 24h/72h/7d/never）+ 第 3 段每 adapter `checked_24h`
- 测试：test_enrich_adaptive（5 例）；4 个 workflow YAML 已 ruby 校验解析通过
- ⚠️ CI workflow 改动沙箱无法 live 跑通——push 后须盯首轮 run（频率是可调旋钮，见各 yaml 注释）
- [x] 4.4 **C 类大厂保鲜覆盖（2026-06-25）**：7 源 clean httpx 逐岗撤岗探活器（关闭信号逐源 live 实测、禁猜）
      → `enrich.py` ENRICH_REGISTRY + `lib/liveness-client.js` LIVENESS + `liveness-sweep.yml` matrix（+7 adapter）：
      amazon(html 404)/apple(jobDetails 404)/meituan(status=0)/microsoft(pcsx search 0 命中)/sf_express(标题-404)/
      tencent(Code500/E1005)/vivo(code105002)。tencent/vivo 顺带返回正文。bilibili(detail 需 ajSessionId、SPA 壳)
      → `audit_dead_links._BROWSER_ADAPTERS` 浏览器审计兜底；phenom(SPA 壳+AMD/百事低相关) 诚实延后。
      测试：`crawler/test_cclass_liveness.py`(20 例) + `tests/liveness-client.test.js`(+8 golden)；
      **13/13 live 集成实测通过**（真 active 岗 alive、真撤岗岗 raise JobClosedError）。信号详见记忆 job-radar-cclass-liveness-signals。

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
