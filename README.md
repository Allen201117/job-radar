# Job Radar Private Beta v0.1

3–5 人内测版官网岗位雷达看板。

**目标**：每天自动监控一批企业招聘官网，把公开岗位信息整理到共享岗位库，每个用户根据自己的偏好看到不同排序。

**技术栈**：Next.js 14 + Tailwind + Supabase Auth/Postgres + Python Crawler + GitHub Actions。

## 架构

```
公开企业招聘官网
        ↓
GitHub Actions 定时 / 手动触发
        ↓
Python Crawler（httpx + selectolax）
        ↓
Supabase Postgres
        ↑
Next.js API（已知源刷新 + 官方源发现候选）
        ↓
Next.js 看板（Vercel 部署）
        ↓
用户登录 → 查看岗位 / 收藏 / 忽略 / 标记已投递 / 跳转官网
```

## 项目结构

```
job-radar-private-beta/
  app/                    # Next.js App Router 页面
    page.tsx              # Today — 今日看板
    jobs/page.tsx         # Jobs — 岗位库
    preferences/page.tsx  # Preferences — 偏好设置
    saved/page.tsx        # Saved — 已收藏
    applied/page.tsx      # Applied — 已投递
    sources/page.tsx      # Sources — 源管理（管理员）
  components/             # React 组件
    Navbar.tsx
    JobCard.tsx
    JobFilters.tsx
    PreferenceForm.tsx
    SourceTable.tsx
  lib/                    # 工具
    supabaseClient.ts     # 浏览器端 Supabase client
    auth.ts               # 服务端 Supabase client + 认证
    live-search.js        # 已知源刷新格式化与链接校验
    official-discovery.js # 官方招聘源发现 URL 分类与搜索 query 构造
    scoring.ts            # 规则打分算法
    types.ts              # TypeScript 类型
    utils.ts              # 工具函数
  crawler/                # Python 抓取器
    adapters/             # 源适配器
      base.py             # BaseAdapter 基类
      apple.py            # Apple public careers search page
      baidu.py            # 百度
      jd.py               # 京东
      haier.py            # 海尔
      siemens.py          # Siemens
    run.py                # 主入口
    db.py                 # Supabase 写入
    normalizer.py         # 字段标准化
    robots.py             # robots.txt 检查
    requirements.txt
  supabase/migrations/
    001_init.sql          # 建表
    002_rls.sql           # RLS 策略
    003_seed_sources.sql   # 首批源数据
    004_update_source_urls.sql # 已验证源 URL 修正
    005_source_candidates.sql # 官方源发现候选隔离与日志
    006_resume_profiles.sql # 简历上传与用户画像
    007_candidate_profile_summaries.sql # 画像摘要字段
  .github/workflows/
    daily-crawl.yml       # 每日抓取 + 手动触发
```

## 数据库表

| 表 | 用途 | 权限 |
|---|---|---|
| profiles | 用户扩展信息 | 自己读写 |
| sources | 企业招聘源 | 所有人读，crawler 写 |
| source_candidates | 官方源发现候选 | admin 读，service role 写 |
| jobs | 共享岗位库 | 所有人读，crawler 写 |
| user_preferences | 用户偏好 | 自己读写 |
| job_actions | 用户操作（收藏/忽略/投递） | 自己读写 |
| crawl_runs | 抓取日志 | admin 读，crawler 写 |
| discovery_runs | 官方源发现日志 | admin 读，service role 写 |

## 当前 Source 状态

| Source | 状态 | 说明 |
|---|---|---|
| Apple | 可用 | crawler + 已知源刷新，详情页为 `jobs.apple.com/en-us/details/...` |
| Siemens | 可用 | crawler 已验证，详情页为 `jobs.siemens.com/en_US/externaljobs/JobDetail/...` |
| 百度 | 可用 | 解析官方列表，详情页为 `talent.baidu.com/jobs/detail/{recruitType}/{postId}`；重复运行更新不重复插入 |
| 京东 | 可用 | 使用公开岗位列表接口，详情页为 `zhaopin.jd.com/web/job-info-detail?requementId=...`；重复运行更新不重复插入 |
| 百度千帆 Web Search | 低频动态发现 | 只用于用户触发的“发现中国官方招聘源”；免费百度搜索额度为每日 50 次，额度耗尽时设置 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，不要频繁跑 dynamic discovery 验证 |
| 海尔 | 暂不可用 | 当前只能解析到专题/入口页，记录为 `partial_success` |

## 当前可用能力

- Jobs 页分为三层：搜索已有岗位、刷新已知中国官网源、发现中国官方招聘源。
- 已知中国官网源刷新走 `/api/search`，只访问已验证的百度 / 京东官方公开源，不消耗百度千帆额度。
- 动态官方源发现走 `/api/discovery`，主 provider 是百度千帆 Web Search；默认只调用 1 个 generated query，用户点击“继续发现更多”才调用第 2 个 query。
- 相同 user/query/city/job_type 的 discovery 结果 45 分钟内复用缓存，响应 diagnostics 会显示 `cache_hit`。
- `jobs` 写入质量门不变：只有 parser 验证过的官方岗位详情页，且 `company/title/jd_url` 非空、HTTP 200、页面包含标题或核心片段，才写入 `jobs`。
- 简历文本、`.txt`、`.md` 可以生成 candidate profile；用户确认后可同步 `user_preferences`，用于 Jobs 排序。

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
- Supabase 项目（免费档即可）

### 1. 初始化 Supabase

在 Supabase 项目中依次执行 `supabase/migrations/` 下的 SQL 文件：

```
001_init.sql → 002_rls.sql → 003_seed_sources.sql → 004_update_source_urls.sql → 005_source_candidates.sql → 006_resume_profiles.sql → 007_candidate_profile_summaries.sql
```

### 2. 配置环境变量

```bash
cp .env.example .env.local
```

编辑 `.env.local`，填入 Supabase 项目的 URL、anon key 和 service role key。

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
2. `.txt` / `.md` 上传；
3. PDF/DOCX 返回 `415 unsupported_file_type`；
4. 空文本返回 `400 empty_resume_text`；
5. 无偏好信号文本不覆盖 preferences；
6. 写入 `resume_uploads`；
7. 写入 `candidate_profiles`；
8. 用户确认后同步 `user_preferences`；
9. Jobs 排序受到偏好变化影响；
10. A/B 用户 profile 和 job_actions 隔离。

## 部署

### 前端 — Vercel

1. 连接 GitHub 仓库到 Vercel
2. 添加环境变量：
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
3. 部署

### Crawler — GitHub Actions

1. 在 GitHub 仓库 Settings → Secrets 中添加：
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
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

1. Apple / Siemens 能抓取成功并写入真实岗位详情页
2. 重复运行同一 source 不会重复插入相同岗位
3. 百度 / 京东 adapter 能生成真实官方详情页，重复运行不重复插入
4. 低质量 source 不写入 active jobs，并在 `crawl_runs` 记录 `partial_success`

### 功能验收

1. 用户可设置 preferences 并保存
2. 用户看到按偏好排序的岗位
3. 用户可收藏、忽略、标记已投递
4. 不同用户操作互不影响
5. 岗位卡片可点击跳转官网
6. Jobs 页可区分本地 jobs 表搜索与官方源发现；官方源发现只把有准确岗位详情页的岗位 upsert 到 jobs
7. 简历文本或 `.txt/.md` 可解析为 candidate profile，用户确认后同步 preferences；PDF/DOCX 暂不支持

## 下一步路线

1. 额度恢复后，用 2 个 query 低频串行验证百度千帆 raw results、`source_candidates` 和 failure_reason。
2. 基于已有 `source_candidates` 优先补 parser：非高校转载、非第三方平台、非 SPA hash-only 且可 HTTP 200 验证标题的官方详情页优先。
3. Moka 继续保持候选隔离；只有能拿到用户可打开、服务端可验证标题的详情 URL 后，才允许写入 `jobs`。
4. 继续扩展已知官方源时，先证明真实详情 URL，再写 parser，不降低 `jd_url` 质量门。

## 边界

当前 Phase 1 **不做**：
- 自动投递
- 第三方招聘平台抓取
- LLM 摘要或匹配
- PDF/DOCX 简历复杂解析
- 邮件/飞书/微信推送
- 商业化付费

## 成本

Phase 1 目标 0–100 元/月：
- Vercel 免费档：0 元
- Supabase 免费档：0 元
- GitHub Actions 免费额度：0 元
