# 爬虫抓全「自愈层」方案 — 交接下个 session（2026-07-07）

> 上游已完成并上线：抓全率**可观测**三阶段（见记忆 `job-radar-crawl-coverage-observability`）。
> 本文档交接**下一步**：把"观测到抓不全 → 人工一个个改" 升级为 **自动治疗/自愈**。
> 这是**动爬虫框架地基的大改**，用户已认可方向、要求下个 session 做。先读本文再动手。

## 用户的诉求（原话意思）
"观测到抓全异常之后，有没有爬虫自己去治疗的自动触发机制？不能每次观测到异常都要我让你来改，那么多公司不能一个一个改。"

## 已上线的现状（可复用的资产）
- **契约**：`crawler/adapters/base.py` BaseAdapter 已有 `reported_total: Optional[int]`、`fetch_complete: bool` 类属性；抓取时 adapter 填、`crawler/run.py` 收尾写进 `crawl_runs`。
- **数据**：`crawl_runs.reported_total` / `coverage_complete`（迁移 176，Supabase）。每源每次抓取一行 = 每家抓全率时间序列。~25 个接口带 total 的 adapter 已挂 reported_total（阶段①）。
- **看板**：`/admin/health`「全库抓全率」卡（迁移 177 `crawl_coverage_snapshot()`）+「必投30家抓全率」（迁移 178 `must_apply_coverage(patterns)`）。看板已能按抓全率升序暴露"谁抓漏了、漏多少"。
- **翻到底范本**：`crawler/adapters/byd.py`（读 `data.total` 动态生成全部 offset + 抓不满即 `raise`）；`bytedance.py`（切片+reconcile+fetch_complete）；本轮 `tencent.py`（读 Data.Count 三板块翻到底）/`jd.py`（翻到"本页<pageSize"停）也是现成范例。

## 核心洞察：抓不全分两类，只有一类能自动
### 第一类 — 分页上限太低（本轮 ~80% 的病都是这个）→ 能自动，且有比"触发修"更好的解法
病根 = 每个 adapter 各自硬编码小上限（字节 max_pages=4、美团 20、腾讯 3、京东不翻页、moka/company_spa 吃基类 max_pages=4…）。
**正解不是"观测→报警→人工改上限"，而是让框架本来就"翻到 reported_total 为止"** → 这个病根本不发生，一次改框架、不用一个个改公司、新加的自动合规。

### 第二类 — 漏板块 / 接口改版 / 平台墙（百度登录墙、OPPO签名、滴滴预览接口、拼多多社招无接口）→ 自动修不了，必须人
需要人做诊断（发现新板块+逆向新接口 / 重新逆向改版接口 / 平台墙是技术边界）。
**不要假装能自动修这一类**（谁吹"自动自愈修接口改版"都是骗人）。观测在这里的价值 = 把人工从"不知道哪漏"变成"看板精确定位那几家"，大幅提效。

## 建议的自愈闭环（三层，按优先级）

### 层 1【治本·核心】框架级"翻到底"纪律
把"翻到 reported_total 为止 + 抓不满告警"下沉成分页 adapter 的**默认行为**，消灭"硬编码小上限"病根。
- ⚠️ 侦察结论（重要）：各 adapter 请求体/翻页参数五花八门、httpx 与 playwright 并存，**"一个通用 helper 吃所有"性价比低**。所以不是强塞一个大一统基类方法，而是：
  - 提供一个**可选的分页 helper**（输入：单页 fetch 闭包、pageSize；行为：翻到 total 或空页/不足页停 + 大安全上限 + 抓不满 log warn + 置 fetch_complete）。
  - 现有分页 adapter **逐步迁移**到它（从已挂 reported_total 的开始）；新 adapter 约定必须用它。
  - 范本直接抄 `byd.py` / `tencent.py` 的循环。
- **不改的**：纯 HTML(baidu/haier/siemens)、通用 ATS 单次返回(greenhouse/lever/ashby)、平台墙类——这些无 total 或无分页，保持现状。

### 层 2【补救·兜底】观测→自动重抓
一个 CI 定时 job（或接入现有 daily/enrich）：扫 `crawl_coverage_snapshot()` 里 `coverage_pct < 阈值` 且 adapter 是"分页型有 total"的源 → **自动重抓一次（翻到底模式）** → 仍不达标才标记进人工待治清单。
- 处理"官网突然扩招"（total 涨了我们暂时落后）这种**非 bug 的临时滞后**——自动补齐，不惊动人。
- ⚠️ 风险：自动重抓要控频率/限速（别把慢浏览器源、限流源打爆）；只对"httpx 分页型"自动重抓，浏览器源不自动（成本高）。

### 层 3【诚实边界】修不了的升级人工
接口改版 / 漏板块 / 平台墙 → 看板已自动报警 + 排进待治清单，人来诊断（像本轮 CC 做的 live 探接口）。**这部分不自动，别假装。**

## 起步建议（下个 session）
1. 先做**层 1**（框架级翻到底 helper + 迁移几个已知触顶的分页源）——覆盖最普遍的病、收益最大、风险可控。
2. 层 1 上线跑出数据后，再做**层 2**（自动重抓 CI），此时能用真实 coverage 数据判断哪些该自动重抓。
3. 层 3 一直是人工，靠看板驱动。
4. 全程 cc-codex-loop：CC 诊断+搭框架+live 验收，Codex 批量迁移 adapter。live 验收必做（真抓确认覆盖率，别信自评——本轮滴滴假接口、字节漏采都是 live 验收才拦住的）。

## 诚实结论（写给用户看）
- **能自动的**：分页上限类（最普遍）→ 框架翻到底，从根消灭，不用一个个改。
- **不能自动的**：接口改版/漏板块/登录墙 → 人工诊断，但观测帮人精准定位、大幅提效。
- 不存在"全自动自愈修一切"——诚实分清边界，把能自动的做到位、不能自动的用观测把人工效率拉满。

---

## ✅ 层 1 已完成（2026-07-07，commits 51c47c7 / 0f126cf / 2992a88，本地已 commit·待推）
- **helper 落地**：`crawler/adapters/base.py` 新增 `PageResult` + `paginate_all(fetch_page, *, page_size, first_page, max_pages, delay_seconds, logger, label) -> (items, total, complete)`。
  三种停止范式全覆盖：① 已知 item 总数翻到底（tencent/byd 范式）② 已知 `total_pages` 按页数翻到底（hotjob 范式，防瞬时短页误判）③ 二者都无靠短页兜底（jd 范式）。首页异常上抛记 failed、后续页异常保留已抓不炸穿。14 个纯函数单测（`crawler/test_paginate.py`）。
- **迁移 5 个真有缺口的 ATS adapter**（挑「仍硬编码小上限 / 压根没上报抓全率」的，不是已修好的大厂）：
  workday（观测盲区→补 flag，25→100）、wt（读了 rowCount 却没赋值→补观测 + 跨类型总预算护栏）、
  hotjob（`totalPage*pageSize` 假分母致「假不完整」→ 用 total_pages 修）、eightfold（250 封顶→**live 实测 HSBC 在华 647 岗**，25→100）、oracle（25→100）。
- **live 验收**（真抓真租户，非自评）：wt/wanda 626·complete、workday/mdlz 56·complete、hotjob/crc 73·complete、eightfold/hsbc 647·complete、oracle/bny 7。全 crawler 单测 642 绿。
- **协作方式**：cc-codex-loop——CC 诊断（survey 全 adapter）+ 搭 helper（TDD）+ live 验收；Codex 批量迁移 + 按复盘修 3 处。

### 层 1 剩余/后续（交下个 session）
- **未迁移的**：smartrecruiters（0 enabled 源，跳过）；phenom/microsoft/amazon（已翻到底、上限宽松，仅一致性收益，低优）；浏览器源 company_spa/moka/google（无 server total、无法干净翻到底，另立工作流）。
- **一处 latent 观测 bug 待修**：`crawler/adapters/china_ats.py` beisen 浏览器 replay 路径设了 `reported_total` 却漏设 `fetch_complete`（httpx 路径已对）。已建后台任务卡。
- **每个 adapter 只 live 抽验了 1 个租户**：迁移对全部租户生效（workday 70 / hotjob 121 / wt 35 源），逐租户差异靠 daily 抓取 + `/admin/health` 抓全率看板暴露——这正是层 1 观测的用途。
- **层 2（观测→自动重抓 CI）** 按原计划等层 1 上线跑出真实 coverage 数据后再做（此时能用真数据判断哪些该自动重抓）。层 3 人工不变。
