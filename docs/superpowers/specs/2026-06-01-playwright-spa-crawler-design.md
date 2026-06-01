# 设计 spec — Playwright SPA 抓取层（大厂官方岗位）

- 日期：2026-06-01
- 状态：待用户评审
- 关联：`PRD.md`（权威功能需求）、`CLAUDE.md`、`crawler/`
- 起因 spike：`/tmp/jr_spike/bytedance_spike.js` 已实证字节可行（拦到 10 条真实岗位）

## 1. 背景与目标

PRD §5 要求覆盖字节/阿里/美团/华为等大厂，但它们是客户端渲染 SPA：岗位接口要 `__ac_signature` 反爬签名、详情页服务端 HTML 无具体 title。现有 `httpx + selectolax` 静态路线**结构性拿不到**这些岗位（这是项目长期卡点的根因）。

**目标**：新增一个**浏览器渲染抓取层**，用真实无头浏览器加载官方招聘页 → 让站点自有 JS 自己签名调用其官方岗位接口 → **拦截该接口响应**拿到真实岗位 → 拼官方详情 URL 入 `jobs`。全程不破解签名、低频、只访问官网公开页。

## 2. 范围

**MVP（本 spec）**：
- 通用浏览器抓取引擎（config 驱动）。
- 字节跳动作为第一个已验证 SPA 源接入并真实入库。
- SPA 源质量门适配（见 §6）。
- `run.py` 按 `crawl_method` 分派；`crawl_runs` 记录可解释 failure_reason。
- 单元测试（用录制的接口响应 fixture，不打真实网络）+ 一次 live 冒烟。
- GitHub Actions 每日跑（CI 安装 chromium）。

**不在本期**：多用户 / 每用户实时发现（二期）；除字节外的 SPA 源仅作"框架可扩展"验证（飞书系/美团等以 config 追加，能拦就接、被反爬标 blocked）；LLM；自动投递；前端大改。

## 3. 架构（双层抓取，下游零改动）

```
sources(enabled)
  ├─ crawl_method='http'        → 现有 httpx adapters（百度/京东/腾讯/Apple/Siemens）  ← 不动
  └─ crawl_method='playwright'  → 新增浏览器引擎（SPA 大厂）
                                       │
                  两层都产出 RawJob ──┘
                                       ↓
              normalizer → 质量门(按源类型) → upsert(去重 source_id+jd_url) → jobs
```

`http` 层与下游 normalizer/质量门/去重/`jobs` 表保持不变。新增的只有 Tier-2。

## 4. 组件

- **BrowserEngine**（`crawler/browser_engine.py`）：启动无头 chromium，创建 context（真实 UA / viewport / locale=zh-CN），一次 run 内复用浏览器、串行处理各源、源间随机延时（礼貌低频）。提供 `crawl_source(config) -> list[RawJob]`。
- **PlaywrightSource 配置**（代码侧注册表 `PLAYWRIGHT_SOURCES`，键=adapter_name，仿现有 `ADAPTERS` 模式；**不动 schema**）。每个源配 4 项 + 元信息：
  - `list_urls`：列表页 URL（社招/校招，可带广度参数；MVP 用广度抓取而非单关键词）；
  - `intercept_match`：要拦截的接口特征（如 `/api/v1/search/job/posts`）；
  - `posts_path` + 字段映射：从响应 JSON 取岗位数组及 `id/title/city/job_type`；
  - `detail_url_template`：用 id 拼可点击详情页（jd_url）；
  - `official_hosts`：合法官方域名白名单（质量门用）。
- **Interceptor**：`page.on("response")` 收集匹配 `intercept_match` 且 content-type=json 的响应。
- **Mapper**：岗位 JSON → `RawJob(company,title,location,job_type,jd_url,apply_url,posted_at)`。
- **run.py 分派**：读 `sources.crawl_method`；`'http'`→现有 adapters；`'playwright'`→BrowserEngine。其余流程（质量门/upsert/crawl_runs）复用。

## 5. 数据流（每个 playwright 源）

启动/复用浏览器 → `goto(list_url)`（域已就绪后等待其岗位接口 XHR）→ 拦截响应 → 取岗位数组 → Mapper→RawJob → SPA 质量门 → `upsert_job`（按 source_id+jd_url 去重）→ 写 `crawl_runs`。分页：按 `posts_path` 的总数/翻页参数，MAX_PAGES 限制（低频）。

## 6. 质量门（按源类型，复用现有去重与禁源过滤）

| 源类型 | 质量门 |
|---|---|
| **开放源** `http` | 维持 PRD §4 原样：company/title/jd_url 非空、jd_url 非首页/列表/搜索/JSON、HTTP 200 且**服务端页面含 title 或核心片段**、不重复。 |
| **SPA 源** `playwright` | (a) 岗位来自被拦截的**官方域接口响应**（来源背书）；(b) company/title/jd_url 非空；(c) jd_url host ∈ `official_hosts`；(d) jd_url 路径匹配 `detail_url_template`（含唯一 id，**非**首页/列表/搜索）；(e) jd_url ≠ 列表/搜索 URL；(f) 抽样 jd_url HTTP 200。**不要求**服务端 HTML 含 title（SPA 本就没有；以官方接口+浏览器渲染做真实性背书）。 |

两类都先过**禁源过滤**（复用 `official-discovery` 的 BOSS/猎聘/智联/前程/LinkedIn/Indeed/知乎/公众号/SEO/高校转载 拒绝规则）。去重键 `(source_id, jd_url)` 不变。

## 7. 错误处理与 failure_reason（PRD §8 口径）

`crawl_runs.status` + `error_message` 必须可解释，区分：
- `browser_launch_failed` / `navigation_timeout`；
- `anti_bot_blocked`：未拦到任何官方岗位接口响应，或检测到验证码/403/429 → 记 `partial_success`，标记该源 blocked，**不硬刚**；
- `no_jobs_found`（拦到接口但空）；
- `parser_missing`（无对应 config）；
- `quality_gate_failed`（拦到岗位但全部未过质量门）；
- `provider_rate_limited` / cooldown（适用于 discovery 路径）。

礼貌策略：源间串行 + 随机延时、低日频、遇 403/429/验证码即停并记录，绝不伪装成功、绝不破解签名。

## 8. 运行环境

- GitHub Actions 每日定时（CI 步骤 `playwright install chromium`）；本地可调试（已验证缓存 chromium-1169 + playwright@1.52 可跑）。
- 单用户 MVP：每日**广度**抓取灌入**共享 jobs 库**，用户本地按画像 `lib/scoring` 筛选/排序（不动）。
- 多用户 + 每用户实时发现 = 二期。

## 9. 数据模型

- 复用 `sources.crawl_method='playwright'`（schema 已预留），**不改表**。
- 源配置放代码侧注册表（版本化、可测），`sources` 行只设 `crawl_method='playwright'` + `adapter_name`。
- 字节源行：`company=字节跳动, adapter_name='bytedance', crawl_method='playwright', source_url='https://jobs.bytedance.com/experienced/position'`。
  - 拦截：`/api/v1/search/job/posts`；岗位数组：`data.job_post_list`（兜底 `posts`/`list`）；字段：`id`、`title`、`city_info.name`/`city_list[0].name`、分类→job_type；
  - detail：`https://jobs.bytedance.com/experienced/position/{id}`（社招）/ `…/campus/position/{id}`（校招）。

## 10. 测试

- **单元（不打网络）**：Mapper（录制的字节接口响应 fixture → RawJob）；SPA 质量门（接受官方详情、拒首页/列表/搜索/禁源）；config 校验。
- **live 冒烟（CI / 用户本机）**：跑字节源，断言 ≥N 岗位、jd_url 格式正确、重跑去重、anti-bot 处理正确。
- 保持现有 node/crawler 测试全绿。

## 11. 实施顺序（交 writing-plans 细化）

1. 加 `playwright` 依赖 + CI 安装 chromium。
2. BrowserEngine + Interceptor + Mapper（config 驱动）。
3. SPA 质量门变体 + 复用禁源过滤。
4. 字节 config + sources 行 + 首次 live 入库。
5. `run.py` 按 crawl_method 分派 + crawl_runs failure_reason 口径。
6. 测试（单元 fixture + live 冒烟）。
7. 追加 2-3 个 SPA 源 config（飞书系/美团/小红书）——验证框架可扩展，能拦就接、否则标 blocked。
8. GitHub Actions 每日接线。

## 12. 风险与对策

- headless 被识别 → 字节未拦（好兆头）；逐源验证，被拦标 blocked 不硬刚。
- 站点接口漂移 → config 驱动，坏了改 config。
- CI 浏览器重 → `playwright install chromium` 标准做法。
- 合规 → 浏览器执行站点自有 JS（不破签名）、只访问官网公开页、低频串行、禁源过滤、遇反爬即停。
