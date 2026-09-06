# 审查证据与全集覆盖表

对应 [主报告](../2026-09-06-first-principles-review.md)。代码基线 `1154512ccfd9ef3019ea5a8f3dab61fcb19dddf7`；2026-09-06。

## 证据边界

本表是静态控制流审查，不能据此声称 1,351 个线上租户全部健康。检查了 adapter 目录全部 69 个 Python 文件（14,581 行，包括基类和 helper），以及 ENRICH_REGISTRY 全部 35 个 key / 33 个独立 detail 函数。表中“安全/合理”均限于所列异常、完整性和判死分支；不代表全文件无缺陷。源码注释中的历史 live 验证不是本轮 live 验证。

“缺两条件”不自动构成 bug。官方逐岗详情端点精确返回撤岗业务码，可以是足够强的单一信号；应判断信号是否绑定当前岗位、能否把服务异常与撤岗分开。本轮确认的反例见主报告 F1–F6，潜在上游协议变化列为补测对象。

## 隔离反例

以下脚本调用仓库真实函数，使用合成输入和 mock 数据库/HTTP/浏览器，无生产连接、无环境文件读取；脚本里的模拟 apply 只会写内存捕获器。反例在该基线上运行通过，含义是“成功复现缺陷”，不是“缺陷已修”。未来修正业务代码后，这些断言预期需要更新。

```bash
python3 docs/reviews/2026-09-06-evidence/crawler-repro.py
python3 docs/reviews/2026-09-06-evidence/governance-repro.py
node docs/reviews/2026-09-06-evidence/insight-repro.js
node docs/reviews/2026-09-06-evidence/matching-repro.js
```

| 脚本 | 观测结果 | 能证明什么 |
|---|---|---|
| crawler-repro.py | 第 1 页成功 100 行、第 2 页失败，函数直接抛异常；1/10 岗不完整抓取仍 success；已知完整空源 sweep 调用为 0；robots wildcard 漏拦 | 四个当前代码边界缺陷；未量化线上影响 |
| governance-repro.py | 正文含 404123 判 dead；HTTP 空串回 alive 并盖戳；browser suspect 盖戳；canonical 消失后同 URL 创建新行 | 生命周期与证据三态错误；无生产修改 |
| insight-repro.js | 同样两个窗口各新增 30 岗，旧窗口 27 岗关闭后“趋势”由 0% 变 +900%；基线缺失输出“平稳” | 当前 active 队列不能倒推历史发岗趋势，更不能推出 HC |

## 已运行的现有定向回归

```bash
(cd crawler && python3 -m unittest test_paginate test_base_adapter test_robots test_run_concurrency test_jd_campus)
PYTHONPATH=crawler python3 -m unittest crawler.test_enrich_row_liveness crawler.test_audit_hash_route_nav crawler.test_audit_prioritize_new crawler.test_audit_source_fairness crawler.test_jobs_db_upsert
node --test tests/liveness-client.test.js
node --test tests/insight-derive.test.js tests/insight-verification.test.js tests/insight-library.test.js
```

分别 74、41、19、72 项通过，共 206 项。另有匹配专项 8 文件 110 项通过，完整命令见匹配取证账本。不是全仓回归。审查交付只增加报告与隔离反例，未修改应用代码，也没有声称 build、全部集成测试或生产部署通过。匹配回放及其补充验证另见主报告。

## 补充取证

- [生产计数与台账口径](data-measurements.md)：07:32Z 快照和近 7 天聚合。
- [匹配与登录 GET 账本](matching-measurements.md)：17 画像简化回放、谓词差异 SQL、测试账号 GET 字节/耗时及 TLS 证据边界。
- `matching-repro.js`：合成管培生后置可过却被前置漏掉；正文角色后置可过但不进入角色全文索引。主线程已执行并核对输出。

## Adapter 全集（文件路径均相对于 crawler/adapters）


“共享分页”表示使用 `paginate_all`，后页异常会保留前页并把 `fetch_complete=False`；“自写分页”需逐个看异常边界。“浏览器引用”不等于主抓取必起浏览器，结论列给出实际路径。

| # | 文件 | 主路径 / 分页 | 覆盖、限流与审查结论 |
|---:|---|---|---|
| 1 | `__init__.py` | 注册辅助 | 无抓取逻辑。 |
| 2 | `abchina.py` | Playwright，自写翻页 | SM4 明文只在页面内存；用共享 cap；浏览器档正确。 |
| 3 | `alibaba.py` | httpx，自写分页 | 固定页数；异常路径有局部保留处理；不受全局 list cap。 |
| 4 | `alibaba_campus_portal.py` | httpx，自写分页 | 校招门户；固定页数；未发现 absence 开启。 |
| 5 | `amazon.py:127` | httpx，自写分页 | **F5 后页异常**：后页 HTTP 失败抛出，已收前页随整源失败丢弃。 |
| 6 | `antgroup.py:107` | httpx，自写分页 | **F5 后页异常**；固定 80 页，无共享 list cap。 |
| 7 | `apple.py` | httpx，共享分页 | 0.15s 页间隔；异常保留前页并标 incomplete。 |
| 8 | `ashby.py` | httpx，单请求 | 单页 API；无 absence。 |
| 9 | `avature.py` | httpx SSR，共享分页 | 1s 页间隔；支持 pathname/processID 变体；共享异常语义安全。 |
| 10 | `baidu.py` | httpx，共享分页 | 0.1s 页间隔；共享异常语义安全。 |
| 11 | `bankcomm.py` | httpx，共享分页 | 使用全局 cap；会话请求路径完整。 |
| 12 | `base.py` | 基类、分页、重复刹车 | `resolve_list_cap` / `RepetitionBrake` / `paginate_all` 契约整体合理；另见主报告 F5、F6。 |
| 13 | `bilibili.py:55` | httpx，自写分页 | **F5 后页异常**；固定 20 页，无页间隔/重试。 |
| 14 | `bilibili_campus.py` | httpx，自写分页 | 分页异常有保护；固定 cap；无 absence。 |
| 15 | `byd.py:69` | httpx 列表+详情，Playwright 生成详情路由 | **F5 后页异常**（列表后页）；内部详情 10 线程，见主报告 F6；浏览器仅用于 Vue router URL。 |
| 16 | `bytedance.py` | httpx，自写完整翻页 | 有 0.15s 请求间隔、405 重试；支持 absence 且完整性门存在。 |
| 17 | `ccb.py` | httpx，共享分页 | 使用全局 cap；先热会话；共享异常语义安全。 |
| 18 | `china_ats.py` | Moka/Beisen/company_spa 多协议 | 详见专项结论；Moka/未缓存 Beisen/company_spa 浏览器，缓存 Beisen 可 httpx；absence 路径有主动降级。 |
| 19 | `china_location.py` | 地点解析 helper | 无 I/O；静态解析已覆盖。 |
| 20 | `chnenergy.py` | httpx，共享分页+详情 | 使用全局 cap、0.15s 页间隔；共享异常语义安全。 |
| 21 | `cmb.py` | httpx，共享分页 | 固定 cap；共享异常语义安全。 |
| 22 | `cmbc.py` | httpx，共享分页 | 固定 cap；共享异常语义安全。 |
| 23 | `cmcc.py` | httpx，共享分页 | RSA 请求头本地生成；固定 cap；共享异常语义安全。 |
| 24 | `cn_portal_tls.py` | TLS helper | 无分页；只处理国内门户 TLS 客户端兼容。 |
| 25 | `cnstaff.py` | httpx，单接口/类目合并 | 接口类别 union；无 browser；无 absence。 |
| 26 | `ctrip.py` | httpx，自写分页 | 代码虽有页面相关字样，`fetch` 是纯 httpx；后页异常有局部处理。 |
| 27 | `eightfold.py` | httpx，共享分页 | 共享异常语义安全；固定 cap。 |
| 28 | `feishu.py` | httpx-first、浏览器回退，自写分页 | 使用全局 cap；支持 absence；HTTP 完整性判定保守。运行路由把它列 httpx，冷 httpx 失败时浏览器回退在无 Chromium 的 daily 会整源失败。 |
| 29 | `gllue.py` | httpx SSR，共享分页 | 0.1s 页间隔；共享异常语义安全。 |
| 30 | `google.py` | Playwright DOM | 浏览器串行档正确；代码中没有可证的公开 JSON 替代。 |
| 31 | `gree.py` | httpx，共享分页 | 固定 cap；共享异常语义安全。 |
| 32 | `greenhouse.py` | httpx，单请求 | 官方 board JSON；无需分页。 |
| 33 | `haier.py` | httpx，共享分页 | 固定 cap；共享异常语义安全。 |
| 34 | `hikvision.py:57` | httpx，自写分页 | **F5 后页异常**；固定 30 页。 |
| 35 | `hotjob.py` | httpx，共享分页+详情 | `totalPage` 模式；详情内部 4 线程；无 absence；共享 helper 对 `totalPage` 提前空页仍判 complete，现有测试明确固化了该语义。 |
| 36 | `huawei.py` | httpx，自写分页+详情 | absence 明确未开；列表非全集的历史约束得到保留。 |
| 37 | `huawei_campus.py` | httpx，自写分页 | 无浏览器；分页错误保留前页/标 incomplete。 |
| 38 | `icbc.py` | httpx，共享分页+详情 | 使用全局 cap；共享异常语义安全。 |
| 39 | `iguopin.py` | httpx，共享分页+详情 | 详情内部 3 线程；严格公司核名；无 absence。 |
| 40 | `jd.py:49` | httpx，自写分页 | **F5 后页异常**；有 0.1s 页间隔，但固定 100 页。 |
| 41 | `jd_campus.py` | Playwright | 代码注明冷 httpx 返回 JDOA XHTML；浏览器串行档和测试断言正确。 |
| 42 | `kuaishou.py` | Playwright 拦截 | 页面 JS 签名；浏览器串行档正确，代码中无可证 httpx 降级。 |
| 43 | `kuaishou_campus.py` | httpx，自写分页 | 公开接口，运行路由为 httpx 正确；固定 cap。 |
| 44 | `lever.py` | httpx，单请求 | 官方 postings JSON；无需分页。 |
| 45 | `meituan.py:55` | httpx，自写分页 | **F5 后页异常**；社招/校招变体同路径，固定 80 页。 |
| 46 | `microsoft.py` | httpx，自写/游标分页 | 公开 pcsx；后页有错误保护；固定 cap。 |
| 47 | `midea.py` | httpx，共享分页 | 固定 cap；共享异常语义安全。 |
| 48 | `mihoyo.py:63` | httpx，自写分页+详情 | **F5 后页异常**；详情内部 6 线程；固定 20 页。 |
| 49 | `netease.py` | httpx，自写分页 | 实际纯 httpx；后页异常有局部保护；固定 cap。 |
| 50 | `netease_campus.py` | httpx，自写分页 | 公开接口；后页异常有局部保护；固定 cap。 |
| 51 | `oppo.py` | httpx，自写分页 | 实际纯 httpx；固定 cap；异常路径有保护。 |
| 52 | `oracle.py` | httpx，共享分页 | 动态 host/site 状态已由 run 每源新实例隔离；共享异常语义安全。 |
| 53 | `phenom.py` | httpx，共享分页/多入口 | widgets 0.2s 页间隔；共享异常语义安全。 |
| 54 | `pinduoduo.py:56` | httpx，自写分页 | **F5 后页异常**；固定 20 页。 |
| 55 | `playwright_base.py` | Playwright 拦截基类 | 浏览器每次新 context；异常会分类；可捕获 ATS entry hint。 |
| 56 | `sf_express.py` | httpx，自写分页 | 使用全局 cap、0.35s 页间隔，单页重试后可保留前页。 |
| 57 | `siemens.py` | successfactors 轻子类 | 继承 httpx 路径；无独立风险。 |
| 58 | `smartrecruiters.py` | httpx，共享分页 | 官方 public API robots allowlist 精确到 host/path；共享异常语义安全。 |
| 59 | `spdb.py` | httpx，共享分页+详情 | 共享异常语义安全；固定 cap。 |
| 60 | `successfactors.py` | httpx，共享分页 | SSR/API；共享异常语义安全。 |
| 61 | `tencent.py` | httpx，自写分页 | 0.1s 页间隔；错误路径可保留前页/标 incomplete。 |
| 62 | `tencent_campus.py:71` | httpx，自写分页 | **F5 后页异常**；固定 40 页。 |
| 63 | `tencent_music.py:44` | httpx，自写分页 | **F5 后页异常**；两个 board 任一后页失败会丢整源。 |
| 64 | `tonghuashun.py` | httpx，共享分页 | 共享异常语义安全；固定 cap。 |
| 65 | `vivo.py:42` | httpx，自写分页 | **F5 后页异常**；固定 20 页。 |
| 66 | `workday.py` | httpx，共享分页 | 429 读 `Retry-After` 并重试一次；动态 host 已由每源实例隔离。 |
| 67 | `wt.py` | httpx，共享分页 | 使用全局 cap；共享异常语义安全；无 browser。 |
| 68 | `xiaohongshu.py` | httpx，自写分页 | 使用全局 cap；后页失败保留前页并标 incomplete。 |
| 69 | `zto.py` | httpx，共享分页+详情 | 0.2s 页间隔；社招/校招变体均共享异常语义安全。 |


## 后台逐岗探活全集（行号均对应 crawler/enrich.py）


约定：表中“alive”指源码能拿到正向在招证据；“unknown”指不构成撤岗证据。当前实现并没有完整承载该三态：`JobClosedError=dead`，非空正文通常=alive，空字符串会在已有 summary 的 sweep 路径被误解释成 alive（主报告 F3）。除 bankcomm 外的函数均使用 `_raise_if_gone()` 的 404/410 判死（`enrich.py:42-47`），表内不重复写的地方以“+404/410”表示。

| registry key / 函数 | dead 条件 | alive 正向证据 | unknown / 保守分支 | 双条件与误杀评估 |
|---|---|---|---|---|
| workday `_detail_workday` 51-61 | 404/410 | 2xx + `jobPostingInfo.jobDescription` | URL 不合式、其它非 2xx、无正文 | 判死单一 HTTP 信号；未知空串会受 主报告 F3 |
| oracle 64-84 | 404/410；2xx `items=[]` | `items[0]` 且有描述字段 | URL 不合式、其它非 2xx、条目无正文 | `items=[]` 依赖端点契约；若上游权限/过滤异常也返空，有批量误杀面 |
| eightfold 87-100 | 404/410 | 2xx + `job_description` | id 不合式、其它状态、空正文 | 未知空串会受 主报告 F3 |
| smartrecruiters 103-117 | 404/410 | 2xx + jobAd sections | 路径不合式、其它状态、空正文 | 同上 |
| greenhouse 120-132 | 404/410 | 2xx + content | token/id 不合式、其它状态、空正文 | 同上 |
| lever 135-149 | 404/410 | 2xx + description/lists/additional | site/id 不合式、其它状态、空正文 | 同上 |
| hotjob 158-182 | 404/410；`state=1017` | data 中 workContent/serviceCondition | 参数缺失、其它状态、无正文 | 业务码明确；未知与 alive 共用空串风险 |
| wt 189-215 | 404/410；`req_state=9501` | `postInfo` 正文（9200 预期） | 参数缺失、其它状态、空正文 | 只认 9501，保守；未知空串风险 |
| amazon 223-228 | 404/410 | 预期为页面 200 | **所有非 404 响应均空串，包括 403/429/500** | 三态丢失最明显，主报告 F3 直接可达 |
| apple 231-240 | 404/410 | 预期为 API 200 | path 缺失；**非 404 状态也空串** | 同上 |
| meituan / meituan_campus 243-260 | 404/410；`status=0` 且无 data | `status=1 + data`（但仍返回空串） | 参数缺失、其它状态 | 判死有双条件；alive/unknown 在返回层合并 |
| microsoft 263-306 | 404/410；search `positions=[]` | 精确 displayJobId 命中 | 非 2xx；有结果但无精确命中；正文二跳失败 | 0 命中若由搜索服务降级产生可误杀；至少已排除非 2xx |
| successfactors 309-325 | 404/410；最终 URL 含 `/errorpage` | 2xx + jobdescription span | 其它状态、正文结构不命中 | errorpage 未核错误类型，站点维护统一跳 errorpage 时有批量误杀面 |
| sf_express 328-339 | 404/410；title 精确 `顺丰人才招聘系统-404` | 其它预期招聘标题（但返回空串） | 非 2xx、无/其它 title | 精确标题较安全；返回层三态仍丢失 |
| tencent 342-360 | 404/410；Code=500 **且** Data=E1005 | Code=200 + Data dict | 非 JSON、E1003/其它码 | 双条件，保守 |
| vivo 363-381 | 404/410；code=105002 | code=0 + data.job_desc | 参数缺失、其它状态/空正文 | 只认专有码，保守 |
| siemens / avature `_detail_avature` 391-411 | 404/410；HTTP 403 **且** main 含 page-not-found 或 error 文案 | 2xx + main 文本 | 其它 3xx/4xx/5xx、空 main | 状态+文案双层；`an error has occurred` 仍偏宽，但限定 403 |
| google 418-431 | 404/410；2xx main 含 `Job not found` **或** `taken down` | 2xx main 文本 | 其它状态/空 main | 站点专用英文，误杀面低于全局 marker |
| huawei 446-477 | 404/410；name 空 **且** filled fields <=8 | payload 不满足空骨架；mainBusiness 可取 | 非 dict/半截但字段多/其它状态 | 双条件正确，宁漏勿杀 |
| jd 485-500 | 任意 301/302/303/307/308；404/410 | 2xx + `h1.post-name`，可抽正文 | 2xx 无标题、其它错误 | **所有重定向判死偏宽**；若站点加 canonical/login/地域跳转会批量误杀 |
| antgroup 506-534 | 404/410；success=true 且 content=null | success=true + content dict | success=false、非 dict | 成功位+null 双层，合理 |
| haier 537-551 | 404/410；专用 `div.cb-page404` | 2xx + `div.cb-wordwrap` | 其它状态/无容器 | 结构化容器，较安全 |
| ashby 554-580 | 404/410；title=`Jobs` **且**无 ld+json | 有合法 JobPosting ld+json | URL 不合式、无/坏 ld+json但 title非Jobs | 双条件正确 |
| mihoyo 586-608 | 404/410；code=1080001052 | data dict + 正文 | 参数不合式、其它 code/data | 专有码，保守 |
| tencent_music 611-638 | 404/410；JSON `code=404` | data dict + duty/requirement | 缺参数、其它码/数据 | 注释提到 msg，但代码不核 msg；源码注释记载该业务码已验证，本轮未逐站联网复核，建议补 code+msg 防码复用 |
| iguopin 641-663 | 404/410；code=2001；code=200 且 data.status=2 | code=200 + contents | 其它 code/空 contents | 两类专用业务信号，较安全 |
| pinduoduo 666-690 | 404/410；success=true 且返回 id != 请求 id/为空 | success=true 且 id 精确匹配 | success=false | success+id 双层；若上游偶发空 result 会误杀，建议再核 `normal=false` 或第二次确认 |
| chnenergy 693-716 | 404/410；错误文案出现 **且**“招聘岗位”缺席 | 页面可抽岗位职责 | 其它状态/半截页 | 双条件正确 |
| spdb 777-803 | 404/410；正文空 **且**两个固定错误壳 marker 都在 | 可抽正文 | 其它状态/半截页 | 双条件正确；但完整旧详情长期存在，不能确认真实截止，源码已诚实注明 |
| icbc 834-872 | 404/410；retCode=9 + “岗位已失效”；或 retCode=0 + data dict + applyState=2 **且**截止日已过 | retCode=0 + data，正文可解 | 请求参数错、其它码、空/坏 payload | 双条件/三条件正确 |
| ccb 895-933 | 404/410；SUCCESS=true + planStatus=2；或 SUCCESS=true + 四业务字段全空 | SUCCESS=true + 非空详情 | 冷会话/登录提示、坏 JSON、其它状态 | 先热身且只认 SUCCESS，保守；空骨架为四字段合取 |
| bankcomm 977-1011 | 不调用通用 404/410 判死；详情失败后，社招/校招两板块都成功答复且都无精确 id | 详情成功；或任一板块精确列出 id | 任一列表调用没答成 | 两跳+双板块，全集中最稳健 |
| cmcc 1020-1060 | 404/410；code=2000 **且** msg 含“未查询到职位信息” | code=0000 + data dict | 签名错/空 id/其它码/坏 payload | code+message 双条件正确 |

`_detail_siemens` 只是 `_detail_avature` 别名（414-415）；registry 中 `siemens`/`avature` 共用同一函数。`meituan_campus` 同样复用 `_detail_meituan`（1099-1101）。35 个 registry key、33 个独立 detail 函数均已覆盖。

## `lib/liveness-client.js` 三态核查

前端/服务端快速探活这层的三态表达本身比 Python 清楚：`checkLiveness()` 捕获网络/解析异常并返回 unknown（`235-243`），两个 API 只有 dead 才 expire、alive 才 touch，unknown 不写（`app/api/jobs/liveness-check/route.ts:86-116`；`app/api/jobs/[jobId]/liveness/route.ts:74-100`）。

| 函数 | dead | alive | unknown |
|---|---|---|---|
| wt 28-51 | 404/410；req_state=9501 | postInfo 或 req_state=9200 | URL/参数错、其它 HTTP/业务态 |
| hotjob 56-82 | 404/410；state=1017 | data truthy | 参数/其它状态/HTTP |
| workday 86-97 | 404/410 | 2xx + jobPostingInfo | URL/source 缺、其它 HTTP/形状 |
| amazon 104-108 | 404/410 | 任意其它 2xx | 其它 HTTP/异常 |
| apple 112-122 | 404/410 | 2xx + res | path/其它 HTTP/形状 |
| meituan 126-145 | 404/410；status=0 且无 data | status=1 且 data | 其它 |
| microsoft 149-162 | 404/410；positions 空 | 精确 ID 命中 | 非 2xx；非空但无精确命中 |
| sf_express 166-175 | 404/410；精确 404 title | 预期 title 前缀 | 其它 |
| tencent 179-190 | 404/410；Code500+E1005 | Code200+Data object | 其它/解析错 |
| vivo 194-213 | 404/410；105002 | code0+data | 其它 |

该层没有发现和 主报告 F3 相同的 unknown 盖戳问题。现有 19 个 Node golden tests 全绿；局限是只覆盖 10/35 个 HTTP registry key，展示时快速检查的覆盖面远小于后台 sweep，这是容量/产品取舍，不是误杀缺陷。
