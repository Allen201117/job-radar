# 求职雷达 / Job Radar — 项目级 Claude Code 指南

> 本文件指导 Claude Code 在本仓库工作。规则优先级：当前明确指令 > 本文件 > 全局 `~/.claude/CLAUDE.md` > 默认行为。

## 项目概览

- 项目名称：求职雷达 / Job Radar Private Beta v0.1
- 项目类型：3–5 人内测版「公开企业官网岗位雷达看板」Web 应用
- 主要技术栈：Next.js 14 App Router + React 18 + TypeScript + Tailwind；Supabase（Auth / Postgres / RLS）；Python crawler（httpx + selectolax）；GitHub Actions 定时抓取
- 包管理器：npm（前端）/ pip（crawler，见 `crawler/requirements.txt`）
- 运行环境：Node.js 18+，Python 3.11+
- 部署：前端 Vercel，crawler GitHub Actions

## 核心闭环（产品第一目标）

```
公开企业官网岗位
  → crawler 抓取 / 已知源刷新 / 官方源发现候选
  → jd_url 质量门校验
  → 标准化入库 jobs
  → 用户偏好规则打分排序（lib/scoring.ts）
  → Today / Jobs 看板
  → 点击跳转官网详情
  → saved / ignored / applied 反馈
```

先跑通这个最小闭环，再加 LLM / 邮件 / 推送 / 商业化。

## 常用命令

```bash
# 前端
npm install
npm run dev        # localhost:3000
npm run build
npm run lint

# 测试
node --test tests/*.test.js
python3 -m unittest discover -s crawler -t crawler -p "test_*.py"

# crawler 单源（需先有 .env.local）
cd crawler
set -a; source ../.env.local; set +a
python3 run.py --source apple   # 或 siemens / baidu / jd

# 提交前回归四件套
node --test tests/*.test.js && \
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
  npm run build && git diff --check
```

## 目录结构

```
app/                     # Next.js App Router 页面
  page.tsx / today-client.tsx     # Today 今日看板
  jobs/                  # Jobs 岗位库（jobs-client.tsx）
  preferences/ saved/ applied/    # 偏好 / 收藏 / 已投递
  sources/               # Sources 源管理（仅管理员）
  login/ auth/callback/  # 登录与 OAuth 回调
  api/search|discovery|resume/route.ts   # 三个后端入口
components/              # JobCard / JobFilters / PreferenceForm / SourceTable / Navbar / ResumeProfilePanel
lib/                     # 工具层：supabaseClient、auth、scoring、types、utils
                         # live-search（已知源刷新格式化/校验）、official-discovery、
                         # baidu-qianfan-search、china-keyword-expansion、china-official-sources、client-job-mapping
crawler/                 # adapters/{base,apple,siemens,baidu,jd,haier}.py + run.py / db.py / normalizer.py / robots.py
supabase/migrations/     # 001_init → 002_rls → 003_seed_sources → 004_update_source_urls
                         # → 005_source_candidates → 006_resume_profiles → 007_candidate_profile_summaries
.github/workflows/daily-crawl.yml   # 每日 + 手动抓取
tests/                   # node --test 单测
```

## 数据库表（8 张，权限见 002_rls.sql）

| 表 | 用途 | 权限 |
|---|---|---|
| profiles | 用户扩展信息 | 自己读写 |
| sources | 企业招聘源 | 所有人读，crawler 写 |
| source_candidates | 官方源发现候选 | admin 读，service role 写 |
| jobs | 共享岗位库 | 所有人读，crawler 写 |
| user_preferences | 用户偏好 | 自己读写 |
| job_actions | 收藏/忽略/投递 | 自己读写 |
| crawl_runs | 抓取日志 | admin 读，crawler 写 |
| discovery_runs | 官方源发现日志 | admin 读，service role 写 |

共享 `jobs`，偏好与操作按 `user_id` 隔离（同一岗位可被 A 标投递、B 标收藏）。

## 三层「搜索」必须区分（高频踩坑点）

不可混为一谈，更不可把有限候选源池叫「实时网搜」：

1. **本地 jobs 搜索** — 只查 `jobs` 表，无外部请求。
2. **已知源刷新** `/api/search` — 只访问已验证的百度 / 京东官方公开源，**不消耗百度千帆额度**，命中后服务端 upsert 到 `jobs`（让前端有稳定 DB id 支持用户操作）。
3. **官方源发现** `/api/discovery` — 百度千帆为主 provider，**低频、串行、可缓存**（相同 user/query/city/job_type 45 分钟复用缓存）；默认只调 1 个 generated query，「继续发现更多」才调第 2 个。

## 数据质量优先级（最高）

`jd_url` 准确性高于一切。**禁止写入 active jobs**：招聘首页 / 搜索页 / 导航页 / 帮助页·FAQ / 登录页 / 语言切换页 / 专题入口页 / 空链接或猜测链接。拿不到稳定岗位详情链接的 source 只能记 `partial_success`，不得标记完整成功。质量门：`company/title/jd_url` 非空 + HTTP 200 + 页面含标题或核心片段。

## 当前 source 状态

| Source | 状态 | 详情链接格式 |
|---|---|---|
| Apple | 可用（crawler + 已知源刷新） | `jobs.apple.com/en-us/details/...` |
| Siemens | 可用（crawler） | `jobs.siemens.com/en_US/externaljobs/JobDetail/...` |
| 百度 | 可用 | `talent.baidu.com/jobs/detail/{recruitType}/{postId}` |
| 京东 | 可用 | `zhaopin.jd.com/web/job-info-detail?requementId=...` |
| 海尔 | **暂不可用** | 只解析到入口页，保持 `partial_success` |

## 百度千帆额度

免费「百度搜索」每日 50 次。控制台 0/50 或未付费时设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，`/api/discovery` 直接返回 `provider_rate_limited` / `rate_limited=true`，前端稳定展示不崩。额度耗尽时不要反复点「发现」或跑 5-query live 验证。

## 认证

Supabase Auth（邮箱登录）+ cookie session。`middleware.ts` 排除 `/api/*`，API 未登录返回 `401 application/json`，不被页面重定向拦截。Sources 页仅管理员。

## 简历画像

粘贴文本 / `.txt` / `.md` → candidate profile → 用户确认后同步 `user_preferences`（只服务排序，不替代检索）。PDF/DOCX 返回 `415 unsupported_file_type`，空文本返回 `400 empty_resume_text`。

## 开发规范

- 按现有风格改，最小化改动，不做无关格式化/重构。
- 复用已有 lib / components / 类型，不引入重型依赖。
- 不吞错（catch 至少记录）。
- 外部请求只走 lib 层封装与 crawler adapters；遵守合规边界。

## 测试规范

- 纯函数优先（scoring、live-search 格式化/校验、normalizer、quality gate、discovery budget）。
- crawler 用 unittest，单测不打真实网络。
- 改 schema 必须同步更新 migrations + 测试（schema 以 migrations 为准，需求文档以 `PRD.md` 为准）。

## 边界（Phase 1 不做）

自动投递 / 登录企业招聘系统 / 绕验证码 / 第三方招聘平台 / LLM 匹配·摘要 / PDF·DOCX 复杂解析 / 邮件·飞书·微信推送 / Redis·Celery·K8s·监控大套件 / 无关 UI 大改。

## 禁止事项

未经允许不 `git push` / `reset --hard` / `clean`；不读取或输出 `.env*`、service_role key 等密钥；不 force push main；不跳过 hooks。

## 项目特殊注意事项

1. **⚠️ 仓库零提交**：真实代码大量未 `git add`（`app/api/`、`lib/live-search.js`、`lib/china-*.js`、`components/ResumeProfilePanel.tsx`、`crawler/test_*.py` 等仍是 untracked）。需要一个干净 baseline commit（征得用户同意后再做）。
2. **⚠️ 运行前提 = .env.local**：必须有 `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`，并在 Supabase 依次跑 `001→007`。无凭证时闭环无法真正运行。绝不提交 / 读取 / 打印这些值。
3. **⚠️ 父级 CLAUDE.md 混淆**：家目录 `/Users/bytedance/CLAUDE.md` 描述的是另一个项目（余声/YuSheng），会被当作父级上下文加载。本项目是求职雷达，与 YuSheng 无关，冲突时以本文件为准。
4. **build 与 dev 不要同时**：dev server 运行期间跑 `npm run build` 会改写 `.next`，导致旧 dev server 静态资源 404；build 后要重启 `npm run dev` 再做浏览器验证。
5. **沙箱限制**：环境可能禁止监听端口 / 阻断网络（Supabase / 百度 / 京东 live）。这类 live 验证需用户本机执行，不能用本地单测冒充 live 验证。
6. **Vercel 实时 upsert**：必须把 `SUPABASE_SERVICE_ROLE_KEY` 配为服务端环境变量，绝不暴露给浏览器。

## 测试账号（需先在 Supabase 建好）

`test@jobradar.local` / `test123456`
