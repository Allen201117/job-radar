# 求职雷达 / Job Radar

**公开企业官网岗位雷达看板**。自 2026-06-20 起为正式版（此前为内测）。

**目标**：每天自动监控一批企业招聘官网，把公开岗位整理进共享岗位库，每个用户按自己的偏好看到不同排序，点击直达官网原始岗位页。

**技术栈**：Next.js 15 App Router + React 18 + TypeScript + Tailwind；Supabase（Auth / sources / crawl_runs / 用户小表）；独立 PostgreSQL 岗位热表；Python crawler（httpx + selectolax，少量 Playwright）；GitHub Actions 定时任务；Vercel 部署。

**这个产品的第一原则**：`jd_url` 准确性 > 一切。拿不到稳定、可点开、内容对得上的逐岗链接，宁可不收录。
规模从来不是成功指标——详见 `CLAUDE.md` 的「核心产品原则」。

## 架构

```
公开企业招聘官网
        ↓
GitHub Actions 定时 / 手动触发
        ↓
Python Crawler（httpx + selectolax）
        ↓
sources / crawl_runs 等 → Supabase Postgres
jobs 岗位热表          → PostgreSQL（JOBS_DATABASE_URL）
        ↑
Next.js API（岗位搜索 + 公司库刷新 + 官方源发现）
        ↓
Next.js 看板（Vercel 部署）
        ↓
用户登录 → 查看岗位 / 收藏 / 忽略 / 标记已投递 / 跳转官网
```

## 项目结构

```
job-radar-private-beta/
  app/                    # Next.js App Router 页面与 API
  components/             # React 组件
  lib/
    jobs-store/           # 独立 PostgreSQL 岗位库读写边界
    source-adapters.ts    # adapter 白名单与录入校验
  crawler/
    adapters/             # Python 源适配器；以目录实际内容为准
    run.py                # crawler 主入口
    db.py                 # Supabase 元数据写入
    jobs_db.py            # jobs PostgreSQL 读写
  supabase/migrations/    # Supabase 迁移；明细以目录实际内容为准
  jobs-db/schema.sql      # 独立 jobs 库 schema
  .github/workflows/
    migrate.yml           # Supabase 迁移自动 apply
    jobs-db-migrate.yml   # jobs 库 schema apply
    daily-crawl.yml       # 每日抓取 + 手动触发
```

## 核心数据表（非完整清单）

Supabase 完整 schema 以 `supabase/migrations/` 为准，独立岗位库 schema 以 `jobs-db/schema.sql` 为准。

| 表 | 用途 | 权限 |
|---|---|---|
| profiles | 用户扩展信息 | 自己读写 |
| sources | 企业招聘源（含 `regions` 抓取地区，默认 `{CN}`） | 所有人读，crawler 写 |
| source_candidates | 官方源发现候选 | admin 读，service role 写 |
| jobs | 共享岗位库（独立 PostgreSQL，含 `country_code` / `job_scope`） | app / crawler 经 jobs-store 边界读写 |
| user_preferences | 用户偏好（含 `job_scope` / `target_regions` 求职范围） | 自己读写 |
| candidate_profiles | 简历档案（含英文侧 `en_*` 字段） | 自己读写 |
| job_actions | 用户操作（收藏/忽略/投递） | 自己读写 |
| crawl_runs | 抓取日志 | admin 读，crawler 写 |
| discovery_runs | 官方源发现日志 | admin 读，service role 写 |
| ops_runs | 后台任务每日台账（运营看板的每日战报来源） | service role 读写 |
| must_apply_gap_attempts | 必投清单缺口漏斗台账：每家走到哪一步、失败原因、复查日期 | service role 写，admin 读 |
| search_usage / llm_usage | 搜索与 LLM 的每日用量台账（额度硬闸依赖它） | service role 读写 |
| company_profiles / insight_* | 职业洞察层（公司画像、洞察条目、溯源、申诉） | 读有展示门，admin/service 写 |

## 当前 Source 状态

adapter 实现覆盖以 `crawler/adapters/` 为准，允许录入的 adapter 与抓取方式以 `lib/source-adapters.ts` 为准；两者必须与 `crawler/run.py` 的 `ADAPTERS` 保持一致。当前主力源、质量门和维护优先级见 `CLAUDE.md`，不要从 README 中维护一份容易漂移的缩略源表。

## 岗位链路与质量门（最容易混淆的几点）

- 岗位链路分为四层：本地 `jobs` 搜索、`/api/refresh` 刷新公司库、保留的旧同步 `/api/search` 已知源刷新、`/api/discovery` 官方源发现；四层不可混为一谈。
- Jobs 页当前主刷新入口走 `/api/refresh`：按用户筛选与偏好选取相关公司源，异步触发 crawler 并轮询进度；`/api/search` 仅保留为窄范围旧同步 API。
- 动态官方源发现走 `/api/discovery`，主 provider 是百度千帆 Web Search；默认只调用 1 个 generated query，用户点击“继续发现更多”才调用第 2 个 query。
- 相同 user/query/city/job_type 的 discovery 结果 45 分钟内复用缓存，响应 diagnostics 会显示 `cache_hit`。
- `jobs` 写入质量门不变：只有 parser 验证过的官方岗位详情页，且 `company/title/jd_url` 非空、HTTP 200、页面包含标题或核心片段，才写入 `jobs`。
- **计数必须诚实**：首页「岗位库」用的是「有效在招」口径（active **且** JD 正文足够长），
  不是裸的 `count(status='active')`——后者含大量无正文薄卡与未探活的假 active，会把数字虚高好几倍。
- **死岗治理只放在不挡用户的层**：点击直接跳官网（瞬开），失活校验走「看板加载后异步批量探活」
  与后台巡检两条离线链路。⚠️ 曾把实时探活放进点击路径，实测每次点击要等 5-8 秒，已废弃——
  质量校验是后台的事，不能卡在用户点击这一下。
- 全局求职范围支持 `domestic` / `overseas` / `all`，默认国内；岗位库和今日机会列表按 `job_scope` + `target_regions` 过滤，首页岗位库计数保持国内+海外合并总数。
- 简历文本，以及 `.txt` / `.md` / PDF / Word(`.docx`) / 图片 上传，都可以生成 candidate profile；英文简历可选写入 `en_*` 档案，用户确认后可同步 `user_preferences`，用于 Jobs 排序和海外匹配。

## 主要功能模块

除了「抓岗位 → 排序 → 看板」这条主链，下面几块也在线上跑；细节以代码与 `CLAUDE.md` 为准。

| 模块 | 做什么 | 入口 |
|---|---|---|
| 今日机会 | 按用户画像分层召回 + 打分，每天给一小撮值得看的岗 | `/`（Today） |
| 岗位库 | 服务端筛选 + 中文 bigram 全文检索；可按公司刷新 | `/jobs` |
| 校招专区 | 锁定用户行业的目标公司校招岗、届别标签与筛选；配套高频「开闸检测」车道，秋招一开就捞 | `/campus` |
| 职业洞察 | 公司维度的事实/经验洞察（三层供给：自有岗位库派生 / 官方源 / 多源检索经验），带分级、时效与去标识门 | 岗位卡片上的公司抽屉 |
| 值得投 / 已投递 | 收藏、忽略、投递进展跟踪，多岗并排对比 | `/saved`、`/applied` |
| 简历画像 | 文本 / `.txt` / `.md` / PDF / Word / 图片 → 结构化档案 → 用户确认后同步偏好 | `/preferences` |
| 管理员看板 | 北极星「必投清单健康覆盖」、每日战报、岗位库体检 | `/admin/health`（仅管理员） |

**供给侧**（用户看不到但决定产品价值）：
- **必投清单**是北极星口径——按行业维护一批「用户真正想投的公司」，覆盖率就是产品健康度。
- **缺口漏斗**专治清单里抓不到的公司：搜索/官网首页找入口 → 平台指纹 → 路由到已有 adapter → **真抓一遍、
  回读到健康岗才启用**，猜错的自动丢弃并按原因退避。
- **每日自动扩源**在保精度的前提下逐步扩量：只收「探活通过 + 真有在招岗 + 标题核验防张冠李戴」的源。

## 外部额度与成本护栏

这个系统会花两类外部额度：**搜索**（找洞察素材/官方入口）与 **LLM**（简历结构化、职业洞察）。
两边都有硬闸，改动前先读 `CLAUDE.md` 的「LLM 成本纪律」与「搜索额度是全局共享的」两节。

### 搜索：多源路由 + 每源日顶

检索走 `crawler/search_router.py`：博查 / Tavily / Serper / 百度千帆，**配了哪个 key 就用哪个，没配的自动跳过**，
各源日顶记在 `search_usage` 表（可用 repo Variables 的 `*_DAILY_CAP` 调整）。默认值按各家免费额度保守设，
**绝不一次性用完**（Serper 是一次性总额度，烧掉不再回来）。

⚠️ **额度是全局共用一个池子**。贪心的消费方必须给别的链留一份，否则会把排在后面的 cron 饿死——
这正是 2026-08 踩过的坑：洞察链一路吃到 0，校招时间线链连续 7 天一家都没处理，却因为不抛异常天天报 success。
现在由 `SEARCH_RESERVE_CAMPUS`（默认 25）预留，新增吃搜索额度的链请先想清楚自己是「贪心方」还是「被预留方」。

百度千帆免费「百度搜索」是每日 50 次。额度耗尽或未开通付费时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，
系统会直接返回 `provider_rate_limited` 诊断而不是崩掉；此时不要反复点「发现官方招聘源」，也不要跑多 query live 验证。

### LLM：日顶硬闸 + 用量记账

- 模型默认走性价比档，**模型名不要带 `Pro/` 前缀**（`Pro/` 只能扣充值余额，非 Pro 还能吃赠费余额）。
- ⚠️ **降级模型绝不能选「思考模式」模型**：它会先吐一大段推理再给 JSON，把 `max_tokens` 撑爆导致 JSON 截断。
  换模型前必须 live 验一次输出 token 数。
- 日顶在 `crawler/llm_budget.py`（env `LLM_DAILY_CAP`）。它是**成本闸不是安全闸**：记账读写失败一律放行，
  因为把整条链停摆的代价比多花一轮更大。
- 每次调用都会打一行可 grep 的 `[llm-usage] model=… tag=… in=… out=…`，cron 收尾写进 `ops_runs` 台账。
  **别再让花费不可观测**——账户欠费过一次都没人察觉，根因就是当时代码从不记录 API 返回的用量。

## 本地运行

### 前提条件

- Node.js `^18.18.0 || ^19.8.0 || >=20.0.0`
- Python 3.11+
- Supabase 项目
- 独立 PostgreSQL 岗位库（生产环境通过 `JOBS_DATABASE_URL` 连接）

### 1. 数据库迁移

Supabase 迁移由 CI 自动 apply：push 到 `main` 且改动 `supabase/migrations/**` 时，`.github/workflows/migrate.yml` 会执行前缀校验并应用尚未执行的迁移，不要再按 README 逐条手动运行 SQL。

迁移数量与明细一律以 `supabase/migrations/` 目录为准，**不在 README 里维护数字**（会漂）。计数命令：

```bash
ls supabase/migrations/*.sql | wc -l
```

独立岗位库 schema 位于 `jobs-db/schema.sql`，由 `.github/workflows/jobs-db-migrate.yml` 应用。

### 2. 配置环境变量

```bash
cp .env.example .env.local
```

编辑 `.env.local`，填入 Supabase 的 URL、anon key、service role key；连接当前独立岗位库时还需配置 `JOBS_DATABASE_URL`。

### 3. 启动前端

```bash
npm install
npm run dev
```

打开 http://localhost:3000

### 4. 运行 Crawler（本地测试）

```bash
cd crawler
pip install -r requirements.txt
python3 run.py

# 单源调试
python3 run.py --source apple
python3 run.py --source siemens
python3 run.py --source baidu
python3 run.py --source jd
```

### known sources 回归

不走百度千帆，只验证已知官方源：

```bash
set -a
source .env.local
set +a
python3 crawler/run.py --source baidu
python3 crawler/run.py --source jd
```

回归时检查：

- 重复运行同一 source 不重复插入；
- `duplicate_jd_urls = 0`；
- 抽样 `jd_url` 返回 HTTP 200；
- 页面包含岗位 title 或核心片段。

### 简历画像回归

回归项：

1. 粘贴简历文本；
2. `.txt` / `.md` / PDF / Word(`.docx`) / 图片 上传均可解析（服务端抽取文本后交 LLM 结构化，失败降级规则解析）；
3. 不支持的文件类型（如 `.doc` / `.pages`）返回 `415 unsupported_file_type`；
4. 空文本返回 `400 empty_resume_text`；
5. 无偏好信号文本不覆盖 preferences；
6. 写入 `resume_uploads`；
7. 写入 `candidate_profiles`；
8. 用户确认后同步 `user_preferences`；
9. Jobs 排序受到偏好变化影响；
10. 英文简历写入 `candidate_profiles.en_*`，不覆盖中文简历档案；
11. A/B 用户 profile 和 job_actions 隔离。

## 部署

生产岗位库上线前必须完成并留存 [`docs/runbooks/jobs-db-production-safety.md`](docs/runbooks/jobs-db-production-safety.md) 中的 TLS、备份、恢复与容量验收证据；未验证项不得视为已满足。

生产依赖安全门使用 high 阈值运行，保证 high/critical 为 0 时命令退出 0：

```bash
npm audit --omit=dev --audit-level=high --json
```

当前 raw audit 仍报告 2 个 moderate，来自 Next.js 内嵌 PostCSS 8.4.31。仓库检查未发现把不可信 CSS AST stringify 后注入 `<style>` 的运行时路径；该风险已评估但尚未完成正式接受，在责任人、接受日期、到期日、批准签字和证据位置登记前仍是发布阻塞。high gate 通过不等于完成 moderate 正式风险接受；每周和依赖升级时必须复查，且不得运行会错误降级依赖的 `npm audit fix --force`。

### 前端 — Vercel

1. 连接 GitHub 仓库到 Vercel
2. 添加环境变量：
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `JOBS_DATABASE_URL`
3. 部署

### Crawler — GitHub Actions

1. 在 GitHub 仓库 Settings → Secrets 中添加（以 `.github/workflows/` 实际引用为准）：
   - `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_URL`（Supabase 迁移用）
   - `JOBS_DATABASE_URL`（岗位库读写）；如启用严格 TLS 还需 `JOBS_DATABASE_SSL_CA` / `JOBS_DATABASE_TLS_SERVERNAME`
   - `SILICONFLOW_API_KEY`（简历结构化 / 职业洞察，见下「外部额度与成本护栏」）
   - 检索源按需配置，配哪个用哪个、缺的自动跳过：`BOCHA_API_KEY` / `TAVILY_API_KEY` / `SERPER_API_KEY` / `BAIDU_QIANFAN_API_KEY`
2. 手动触发：Actions → daily-job-crawl → Run workflow
3. 定时触发：每日 UTC 01/07/13/17（北京时间 09/15/21/次日 01 点）跑快档 httpx 抓取；
   浏览器源、逐岗富化、死链巡检、缺口漏斗、洞察富化等各有独立 workflow 与班次，
   以 `.github/workflows/` 目录为准

## 验收方法

### 系统验收

1. `npm run build` 无报错
2. Vercel 部署后可访问
3. Supabase Auth 登录可用
4. GitHub Actions 手动触发 crawler 成功
5. `jobs` 表有数据入库

### 数据验收

1. 从当前 enabled sources 中按 adapter 抽样，能抓取并写入真实官方岗位详情页
2. 重复运行同一 source 不会重复插入相同岗位
3. 抽样覆盖 `crawler/adapters/` 中的主力 adapter，并核对其生成的 `jd_url`
4. 低质量 source 不写入 active jobs，并在 `crawl_runs` 记录 `partial_success`

### 功能验收

1. 用户可设置 preferences 并保存
2. 用户看到按偏好排序的岗位
3. 用户可收藏、忽略、标记已投递
4. 不同用户操作互不影响
5. 岗位卡片可点击跳转官网
6. Jobs 页可区分本地 jobs 表搜索与官方源发现；官方源发现只把有准确岗位详情页的岗位 upsert 到 jobs
7. 简历文本，以及 `.txt/.md`/PDF/Word(`.docx`)/图片 上传，均可解析为 candidate profile，用户确认后同步 preferences

## 当前维护方向

1. MVP 阶段优先保证精准、可靠、稳定，不再以 source 或 adapter 数量作为成功指标。
2. 关注目标相关的有效产出：真实官方详情页、稳定 `jd_url`、足够的 JD 正文，并持续通过 liveness / quality gate。
3. 只在目标公司明显缺失时定向补源；新增源必须 live 探活并证明能持续产出真实岗位。
4. 任何发现候选或 parser 结果都不能绕过 `jd_url` 质量门写入 active jobs。

## 文档约定

- **`CLAUDE.md` 是权威工程规范**：产品原则、各 adapter 的坑、数据库边界、成本纪律、公开仓库红线都在那里，
  改代码前先读它。README 只做「这是什么、怎么跑起来、有哪些模块」的入口。
- **README 与代码同步更新**：改动如果影响到本文写过的事实（定位、架构、模块、外部依赖、部署方式、
  运行命令），**在同一个 commit 里把 README 一起改掉**，不要留到以后。
- **易漂的细节一律不写进 README**：源数量、岗位数量、迁移条数、adapter 清单这类数字会天天变，
  写下来就等于埋一个必然过期的谎。指向目录、指向命令、指向 `CLAUDE.md`。

⚠️ **本仓库是公开的**：提交内容、历史、提交者身份全世界可见且事后删不干净。
本机绝对路径、服务器 IP / 主机名、真人姓名与私人邮箱、任何密钥都不许写进任何被跟踪的文件（README 也一样）。
`.githooks/pre-commit` 会在提交前扫描拦截；误报请按 `scripts/scan-sensitive.sh` 里的说明加豁免，
**不要用 `--no-verify` 绕过**。

## 边界

当前 Phase 1 **不做**：
- 自动投递
- 登录企业招聘系统或绕验证码
- 第三方招聘平台抓取
- 邮件/飞书/微信推送
- Redis / Celery / K8s 等重型基础设施

LLM 已用于简历结构化和洞察辅助草稿，但不是岗位写入质量门的替代品。

## 成本

当前部署同时依赖 Vercel、Supabase、GitHub Actions 与独立 PostgreSQL 主机，已不是“全免费栈”；实际费用以各部署账户和用量为准。
