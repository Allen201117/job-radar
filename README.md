# Job Radar Private Beta v0.1

3–5 人内测版官网岗位雷达看板。

**目标**：每天自动监控一批企业招聘官网，把公开岗位信息整理到共享岗位库，每个用户根据自己的偏好看到不同排序。

**技术栈**：Next.js 14 + Tailwind + Supabase（Auth / sources / runs / 用户数据）+ 独立 PostgreSQL 岗位库 + Python Crawler + GitHub Actions。

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

## 当前 Source 状态

adapter 实现覆盖以 `crawler/adapters/` 为准，允许录入的 adapter 与抓取方式以 `lib/source-adapters.ts` 为准；两者必须与 `crawler/run.py` 的 `ADAPTERS` 保持一致。当前主力源、质量门和维护优先级见 `CLAUDE.md`，不要从 README 中维护一份容易漂移的缩略源表。

## 当前可用能力

- 岗位链路分为四层：本地 `jobs` 搜索、`/api/refresh` 刷新公司库、保留的旧同步 `/api/search` 已知源刷新、`/api/discovery` 官方源发现；四层不可混为一谈。
- Jobs 页当前主刷新入口走 `/api/refresh`：按用户筛选与偏好选取相关公司源，异步触发 crawler 并轮询进度；`/api/search` 仅保留为窄范围旧同步 API。
- 动态官方源发现走 `/api/discovery`，主 provider 是百度千帆 Web Search；默认只调用 1 个 generated query，用户点击“继续发现更多”才调用第 2 个 query。
- 相同 user/query/city/job_type 的 discovery 结果 45 分钟内复用缓存，响应 diagnostics 会显示 `cache_hit`。
- `jobs` 写入质量门不变：只有 parser 验证过的官方岗位详情页，且 `company/title/jd_url` 非空、HTTP 200、页面包含标题或核心片段，才写入 `jobs`。
- 全局求职范围支持 `domestic` / `overseas` / `all`，默认国内；岗位库和今日机会列表按 `job_scope` + `target_regions` 过滤，首页岗位库计数保持国内+海外合并总数。
- 简历文本，以及 `.txt` / `.md` / PDF / Word(`.docx`) / 图片 上传，都可以生成 candidate profile；英文简历可选写入 `en_*` 档案，用户确认后可同步 `user_preferences`，用于 Jobs 排序和海外匹配。

## 百度千帆额度与限流

当前百度千帆“百度搜索”免费额度是每日 50 次。控制台显示剩余 0/50 或未开通付费时：

1. 不要运行 5-query dynamic discovery live 验证。
2. 不要手动反复点击“发现中国官方招聘源”。
3. 在本地或部署环境设置：

```bash
BAIDU_QIANFAN_SEARCH_DISABLED=true
```

开启后，系统不会调用真实 `baidu_qianfan_web_search`，会直接返回 `provider_rate_limited` / `rate_limited=true` 诊断，前端应展示限流状态且不崩溃。

额度恢复后再关闭：

```bash
BAIDU_QIANFAN_SEARCH_DISABLED=false
```

恢复验证时仍按低频串行方式执行：先跑 2 个 query，每个只调用 1 个 generated query；成功后再串行测试剩余 query，并保持间隔。

## 本地运行

### 前提条件

- Node.js 18+
- Python 3.11+
- Supabase 项目
- 独立 PostgreSQL 岗位库（生产环境通过 `JOBS_DATABASE_URL` 连接）

### 1. 数据库迁移

Supabase 迁移由 CI 自动 apply：push 到 `main` 且改动 `supabase/migrations/**` 时，`.github/workflows/migrate.yml` 会执行前缀校验并应用尚未执行的迁移，不要再按 README 逐条手动运行 SQL。

当前仓库共有 **174** 个 Supabase SQL 迁移；明细与顺序以 `supabase/migrations/` 为准。计数命令：

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

1. 在 GitHub 仓库 Settings → Secrets 中添加：
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_URL`（Supabase 迁移）
   - `JOBS_DATABASE_URL`（岗位库读写）
2. 手动触发：Actions → daily-job-crawl → Run workflow
3. 定时触发：每天 UTC 00:00（北京时间 08:00）自动运行

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
