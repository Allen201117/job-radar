# 求职雷达 · 爬虫与检索系统性改造（整合 spec：P1–P4）

> 日期：2026-06-09
> 一份 spec，四个子项目。**P1（呈现）+ P2（on-demand 获取）并行先行**；**P3（daily 元数据质量）+ P4（daily 提速）紧随**。
> P1/P2 = 纯前端 + Vercel API/lib，零 DB schema；P3/P4 = 爬虫 Python 侧。

---

## 1. 背景与诊断（`scripts/diagnose-jobs.js`，2026-06-09 生产库实测）

用户痛点：**库海量却只筛得出极小部分**（产品没价值）+ **联网爬取返回近乎为零**。

- 活跃岗位 **23,561**；元数据：`location` 空 3.2%、`summary` 空 **88.0%**、`job_type` 空 **59.0%**、`salary` 空 **100%**。
- 三桶：社招 81.1% / 校招 10.9% / 实习 8.0%；职能：**其他 37.7%** / 研发 30.7% / 产品 8.9% …
- 抓取端高产：379 源、9.5% 空岗、近 24h 入库 15k+（近期分页扩源的真实增长，非 bug）。

**筛选漏斗**（复用前端真实逻辑，城市 ∧ 类型 ∧ 关键词 硬 AND）：

```
深圳 + 社招 + 后端：23561 → 城市2150 → 类型1878 → 关键词 36   ←★ 关键词那刀砍掉 98%
上海 + 社招 + 算法：23561 → 城市4434 → 类型3919 → 关键词 330
```

**根因（数据驱动，已纠正初始「空地点」假设）**：

1. **关键词被元数据饿死（最致命）**：88% 空摘要 → 关键词只能匹配标题；中文标题碎而多变（"后端"岗常叫 Java 开发/服务端研发/高级软件工程师），字面命中率极低。
2. **类型桶失真**：59% 空 job_type → 默认堆社招，校招/实习被饿死。
3. **联网爬取的"零" = 窄路径 + UI 陷阱**：`/api/search` 只实时抓 baidu/jd 2 源（apple/ATS 是死代码）；discovery 返回后 `setOnlyNew(true)` 把 23k 库藏起来（[jobs-client.tsx:273](../../../app/jobs/jobs-client.tsx)、`:345`）。
4. **标签误判（用户亲点）**：`JOB_FUNCTION_RULES`「产品」裸词排在「研发」前 → 研发岗被打成产品；它也是检索"相关层"的依赖。
5. **88% 空摘要是结构性的**：主力适配器列表接口不含 JD 正文（`workday`/`oracle`/`amazon`/`moka-DOM` 写死 `summary=None`，`beisen` 列表接口不返回正文）；正文在详情页/详情接口里，适配器只抓列表。

**一句话**：问题不在抓取量，在 **元数据薄 + 匹配太严 + 标签不准 + 即时路径窄/有 UI 陷阱**。

---

## 2. 路线图与并行策略

| Phase | 子项目 | 轨道 | 文件域 | 性质 |
|---|---|---|---|---|
| **P1** | 检索召回 + 标签精度（含修 onlyNew 陷阱） | 呈现 | `lib/china-keyword-expansion.js`、`app/jobs/jobs-client.tsx`、`components/JobCard.tsx` | 纯前端/lib，可单测 |
| **P2** | 联网即时爬取强化·定向刷新已知源 | 获取·on-demand | `lib/live-search.js`、`app/api/search/route.ts` | TS，可单测；live 需网络 |
| **P3** | 爬虫元数据富化（详情抓取补摘要/薪资/发布日） | 获取·质量 | `crawler/adapters/*`、`crawler/run.py`、`crawler/normalizer.py` | Python，mock 单测；live 需 CI |
| **P4** | daily 并发提速 + 死源跳过 + 诊断常态化 | 获取·速度 | `crawler/run.py` | Python；live 需 CI |

**并行**：P1（前端/lib）与 P2（API/lib）文件域几乎不重叠，唯一交叉是 `jobs-client.tsx`（P1 改 `filtered` memo + 渲染分层；P2 改刷新 handler + 去 onlyNew）——按组件边界切，互不踩。
**协同**：P3 补摘要后，P1 的**精确层自然回血**（关键词又能匹配正文），相关层粗粒度问题随之缓解——P1 是缓解、P3 是根治，叠加最优。
**依赖**：P3 的详情抓取（N 次/源）只有靠 P4 并发才不拖垮 daily → P3、P4 协同落地。

---

## 3. P1 — 检索召回 + 标签精度

四组件，A 是 B 的前提；实现序 A→B→C→D。

### A 职能标签精度硬化（标签必须 JD 强相关）
`JOB_FUNCTION_RULES`「产品」规则含裸词 `产品`/`product` 且排在「研发」前 → 误判。
- 「产品」只在**角色锚定**时打：`产品经理|产品运营|产品策划|产品负责人|产品总监|产品专家|高级产品|product manager|\bpm\b|\bpo\b`——**删裸词 `产品`/`product`**。
- 删裸词后含 `研发|开发|工程师|算法|前/后端|测试|架构|engineer|developer|software` 的岗位自然 fall-through 到「研发」。
- 「产品设计师」移出「产品」→ 落「设计」。无强信号 → `其他`（诚实未知）。

**判定矩阵（锁测试）**：

| 标题 | 修前 | 修后 |
|---|---|---|
| 产品研发工程师 / 产品测试工程师 / 智能产品开发 / Product Engineer / 硬件产品工程师 | 产品 ❌ | 研发 ✅ |
| 产品经理 / 数据产品经理 | 产品 ✅ | 产品 ✅ |
| 产品设计师 | 产品 ❌ | 设计 ✅ |
| 算法工程师 | 研发 ✅ | 研发 ✅ |

### B 两层关键词匹配（精确 + 相关）
city ∧ type 仍硬 AND；keyword 由"一刀切"改两层。
- **tier-1 精确**：现有 `jobMatchesChinaKeyword`，**完全不动**（零回退）。
- **tier-2 相关**：新增 `KEYWORD_GROUP_TO_FUNCTION`（算法/前/后端/测试/运维/安全/硬件→研发；产品→产品；数据分析/工程→数据；设计→设计；运营/市场/销售各自；财务/人力/法务→职能；供应链→供应链；投研/管培/实习→不参与）。查询命中组 → 目标职能；岗位 `classifyJobFunction` ∈ 该集合即"相关"；**剔除已被兄弟细分组精确命中的岗位**（"后端"相关层去掉明确是"前端"的）。
- 新增纯函数 `keywordMatchTier(job, query) → "exact"|"related"|null`。
- **展示**：精确层在上，「相关岗位（同职能）」分割线，相关层在下、**默认限量 + 可展开**。无 keyword 不分层。

> 预期：深圳后端 `36 精确 + 一屏相关`。代价：研发类关键词相关层偏粗、"其他"职能岗照不到——P3 补摘要根治。

### C 去 onlyNew UI 陷阱（库始终可见）
删 `handleOfficialDiscovery`/`finishBrowserDiscovery` 里的 `setOnlyNew(true)`；改为新发现岗位**高亮置顶**进完整列表 + banner「本次新发现 N 个」，库始终可见；「只看新发现」降为手动开关。保留「发现 N 符合 M」诚实文案与 `relaxLocationAndType`。

### D 类型桶信号增强
`normalizeChinaJobType`/`recruitmentCategory` 增信号：jd_url 路径（`/campus` `/intern` `/shixi` `/xiaozhao` `/graduate`）+ 公司/源名"校招/实习"字样 → 真校招/实习别误判进社招。（彻底补 job_type 是 P3。）

---

## 4. P2 — 联网即时爬取强化·定向刷新已知源

**产品取向（用户定）**：on-demand 主职责 = 定向刷新已知源（非发现新公司）。daily 给广度，on-demand 给"用户筛选项下更新鲜的结果"。
**硬约束**：Vercel 跑不了 Playwright → 必分两档。

### A 源选择器（纯函数，可单测）
按用户筛选项从 379 源挑最相关的 N 个（cap 保 Vercel 不超时）：公司精确命中→直接刷该源（零外部搜索）；关键词→行业（复用 `lib/industries.ts`）；城市过滤。输出按相关度排序、分快档(httpx)/慢档(浏览器)两组。

### B 快档扩源（内联秒回）
接上死代码（apple/greenhouse/lever）+ 给 `workday`/`oracle`/`amazon`/`phenom`/`microsoft`/`hotjob` 补 TS 实时抓取器（**镜像 Python 适配器的 JSON API 调用**，住 `lib/live-search.js`）。选中快档源并行抓（`Promise.allSettled` + 单源 8s 超时），抓 → 过滤(query+city) → 质量门(`isHighQualityJdUrl`) → `upsertLiveJob`。

### C 慢档分流（异步）
选中源含浏览器源（北森/Moka/飞书/google）→ 触发 `/api/discovery/dispatch`→GitHub Actions→轮询（机制已存在）。UX 诚实分层：「已即时刷新 N 源（M 新岗）；另 K 个浏览器源已排队后台抓」。

### D 复用 P1
结果走 P1 管线（无 onlyNew 陷阱、两层匹配、准标签）；`upsertLiveJob` 尽量填全 API 返回的元数据。

---

## 5. P3 — 爬虫元数据富化（详情抓取补摘要/薪资/发布日）

**根因**：列表接口不含 JD 正文 → 88% 空摘要、100% 空薪资。

- **P3a 列表挖掘（先做，便宜）**：逐适配器审计，把列表**已返回却没接**的字段补上（如 workday `bulletFields`、各 JSON 接口的 desc/薪资字段）。零额外请求。
- **P3b 详情抓取（根治）**：给高产适配器（`beisen`/`workday`/`oracle`/`moka`/`amazon`）加 `fetch_detail(job)` 取 summary/salary/posted_at；`run.py` 对**缺摘要的新增/变更岗**调用，**有界 + 并发（靠 P4）**，单源 cap（如详情抓取上限 N 条/轮）防失控。
- **P3c 回填（存量）**：有界脚本分日富化存量 23k（每轮 cap，避免一次打爆）。
- **salary**：有则取、无则"官网未披露"，**不伪造**（中国官方岗位常不披露，低产出可接受）。
- **质量门升级**：`validate_job_quality` 之外增"元数据完整度"**软**信号（不挡，但记录），让诊断能跟踪富化进度。

## 6. P4 — daily 并发提速 + 死源跳过 + 诊断常态化

`run.py` 现为完全串行 `for source`，含大量 Playwright 浏览器源 → 几十分钟。

- **源分档并发**：httpx 源高并发（`ThreadPoolExecutor`，httpx I/O 释放 GIL）；浏览器源**低并发池**（2–3，各自 `sync_playwright`，受 CI runner 资源限制 cap 低）。
- **死源跳过**：读 `crawl_runs` 连续失败 streak，连败 ≥K 次的源本轮跳过（周期性重试探活）。
- **诊断常态化**：每轮产出 per-source yield 摘要（复用 `diagnose-jobs` 口径）写日志/`crawl_runs`，让"哪些源在产、哪些空转"可见。
- **约束**：CI runner 资源有限，浏览器并发必须 cap 低；先并发 httpx 源（占多数、最划算），浏览器源小池。

---

## 7. 测试（每 phase）

`node --test tests/*.test.js` + `python3 -m unittest discover -s crawler`，纯函数/mock 优先（不打真实网络）：
- **P1**：§3 判定矩阵全锁；`keywordMatchTier` 三态；后端召回研发且剔前端；空摘要稀薄岗 fixture；精确层零回退回归。
- **P2**：源选择器排序/分档；新 TS 抓取器对 fixtures 解析正确。
- **P3**：各 `fetch_detail` 对 mock 详情响应抽 summary/salary/posted；P3a 字段映射。
- **P4**：源分档逻辑、死源 streak 判定（纯函数，不起真浏览器）。

## 8. 验证与「能/不能本地 live 验证」（诚实边界）

- **本地可全验**：P1（lib 单测 + `npm run build` + 浏览器实测筛选）、P2 的纯函数与解析（单测 + build）。
- **需你本机/CI 跑**（沙箱连不上你的 Supabase / 跑不了重型并发浏览器）：P2 的真实 live 刷新、P3 详情抓取对真站、P4 CI 并发耗时。我会把这些做成可一键跑的命令 + 跑 `diagnose-jobs.js` 前后对比（关键词漏斗 36→几百、空摘要占比下降、标签误判数下降）。

## 9. 风险

- P1 相关层过宽 → 分割线 + 限量可展开；精确层不动。
- P2 Vercel 超时 → cap 源数 + 单源超时 + 部分成功可接受；TS 抓取器与 Python 漂移 → 只镜像 JSON API、fixtures 锁定。
- P3 详情抓取拖慢 daily → 有界 + 靠 P4 并发；只富新增/变更 + 分日回填。
- P4 浏览器并发吃资源/触发反爬 → 并发 cap 低、保留单源限速。

## 10. 建议实现顺序（"四个都做"的内部排序）

1. **P1**（lib + 前端，最快见效、解锁 P2/P3 的呈现）
2. **P2**（lib/live-search + api/search；与 P1 并行推进，按文件域切）
3. **P3a→P3b→P3c**（先便宜的列表挖掘，再详情抓取，再回填）
4. **P4**（并发 + 死源 + 诊断；与 P3b 协同，让详情抓取划算）

每步：写测试 → 实现 → `node --test` / `unittest` / `npm run build` 绿 → commit（天然边界）。
