# Job Radar Private Beta v0.1 — 当前交接

日期：2026-05-26

## 当前结论

项目已从旧 Node/SQLite PoC 清理到当前 Phase 1 架构：

- Next.js 14 App Router
- Supabase Auth / Postgres / RLS
- Python crawler
- GitHub Actions 定时抓取

当前可测试闭环：

1. 邮箱登录
2. Jobs / Today 读取 active jobs
3. Preferences 保存用户偏好
4. Saved / Applied / ignored 写入 `job_actions`
5. 管理员访问 Sources
6. Apple / Siemens crawler 入库
7. 已知中国官网源刷新：百度 / 京东官方公开源，实时命中会服务端 upsert 到 `jobs`
8. 岗位卡片跳转企业官方详情页
9. 简历文本 / .txt / .md 解析 candidate profile，用户确认后同步 `user_preferences`
10. 官方源动态发现：百度千帆为主 provider，但必须低频、串行、可缓存；额度耗尽时禁用真实调用

## 已清理

旧 PoC 文件已删除：

- `server.js`
- `app.js`
- `db.js`
- `fetcher.js`
- `matcher.js`
- `scheduler.js`
- `auth.js`
- `index.html`
- `styles.css`
- 旧 `tests/realtime-search.test.js`
- `job_radar.db*`
- `components/AutoLogin.tsx`
- `middleware.ts.bak`

## 当前关键文件

```text
app/
  page.tsx
  jobs/page.tsx
  jobs/jobs-client.tsx
  preferences/page.tsx
  saved/page.tsx
  applied/page.tsx
  sources/page.tsx
  api/search/route.ts
components/
  JobCard.tsx
  JobFilters.tsx
  PreferenceForm.tsx
  SourceTable.tsx
lib/
  auth.ts
  live-search.js
  scoring.ts
  supabaseClient.ts
crawler/
  run.py
  db.py
  normalizer.py
  adapters/apple.py
  adapters/baidu.py
  adapters/siemens.py
  test_normalizer.py
  test_apple_adapter.py
  test_baidu_adapter.py
  test_siemens_adapter.py
tests/
  live-search.test.js
```

## 2026-05-26 当前边界

- 百度千帆“百度搜索”免费额度为每日 50 次；当前控制台显示剩余 0/50 且未开通付费时，不要跑 dynamic discovery live query。
- 设置 `BAIDU_QIANFAN_SEARCH_DISABLED=true` 后，`/api/discovery` 不会调用真实千帆，会直接返回 rate-limited diagnostics，前端显示 `provider_rate_limited` / `rate_limited=true`。
- `/api/search` 是 known sources refresh，只访问已验证的百度 / 京东官方源，不消耗千帆额度。
- `/api/discovery` 仍是用户触发的实时官方源发现入口，默认最多 1 个 generated query；“继续发现更多”才调用第 2 个 query。
- `jobs` 写入质量门不变：只有官方岗位详情页通过 HTTP 200 和标题/核心片段验证后才能写入。
- PDF/DOCX 简历仍不支持，必须返回 `415 unsupported_file_type`；空文本返回 `400 empty_resume_text`。

## Source 状态

### 可用

- Apple
  - crawler 可用
  - 实时搜索可用
  - `jd_url` 为 `https://jobs.apple.com/en-us/details/...`
  - 重复运行不重复插入
- Siemens
  - crawler 可用
  - `jd_url` 为 `https://jobs.siemens.com/en_US/externaljobs/JobDetail/...`
  - 重复运行不重复插入
- 百度
  - 官方社招 SSR 列表可解析
  - `jd_url` 为 `https://talent.baidu.com/jobs/detail/{recruitType}/{postId}`
  - 官方详情页抽样可 200 打开并显示对应标题
  - 写 Supabase 复测通过，重复运行会按 `(source_id, jd_url)` 更新或新增
- 京东
  - 官方公开列表接口可解析
  - `jd_url` 为 `https://zhaopin.jd.com/web/job-info-detail?requementId=<requirementId>`
  - 官方详情页抽样可 200 打开并显示对应标题
  - 写 Supabase 复测通过，重复运行会更新不重复插入

### 暂不可用

以下 source 当前只解析到导航页、搜索页、语言切换页或专题入口页，不再写入 active jobs：

- 海尔

这些 source 会记录 `partial_success`，只有修到能拿真实岗位详情链接后才能恢复 active 入库。

## 本地运行

```bash
npm install
npm run dev
```

登录测试账号：

- `test@jobradar.local`
- `test123456`

## Crawler

```bash
cd crawler
set -a
source ../.env.local
set +a
python3 run.py --source apple
python3 run.py --source siemens
python3 run.py --source baidu
python3 run.py --source jd
```

known sources 回归建议：

```bash
set -a
source .env.local
set +a
python3 crawler/run.py --source baidu
python3 crawler/run.py --source jd
```

检查项：`jobs_seen` / `jobs_created` / `jobs_updated`、重复运行不重复插入、`duplicate_jd_urls = 0`、抽样 `jd_url` HTTP 200 且页面包含 title 或核心片段。

## 验证命令

```bash
node --test tests/*.test.js
python3 -m unittest discover crawler -p "test_*.py"
npm run build
git diff --check
```

## 简历画像回归

验证链路：

1. 粘贴富文本简历；
2. 上传 `.txt` / `.md`；
3. PDF/DOCX 返回 415；
4. 空文本返回 400；
5. 无偏好信号文本不覆盖 preferences；
6. 写入 `resume_uploads`；
7. 写入 `candidate_profiles`；
8. 用户确认后同步 `user_preferences`；
9. Jobs 排序随 preferences 改变；
10. A/B 用户 profile 和 job_actions 隔离。

## 下一步开发路线

1. 等百度千帆额度恢复后，先测试 2 个 query，每个只调用 1 个 generated query；若没有 429，再串行测试剩余 query。
2. 审查已有 `source_candidates`，优先处理非第三方、非高校转载、非 SPA hash-only 且可服务端验证标题的官方详情页。
3. Moka 只有在能得到稳定、用户可打开且服务端可验证 title 的详情 URL 后，才允许从候选进入 `jobs`。
4. 新 source 仍按“真实官方详情页 -> parser -> 质量门 -> jobs”的顺序推进，不用样例数据伪装成功。

## 2026-05-21 续跑结果

- `node --test tests/*.test.js`：8 passed
- `python3 -m unittest test_baidu_adapter.py test_siemens_adapter.py test_db_env.py test_apple_adapter.py test_normalizer.py`：9 passed
- `npm run build`：通过，生成 12 个页面 / route
- `npm run dev`：沙箱内端口监听会 `EPERM`；用户授权非沙箱后已启动在 `http://localhost:3001`
- `curl -I http://localhost:3001/login`：200 OK
- `curl -i "http://localhost:3001/api/search?query=algorithm&limit=3"`：未登录时返回 `401 application/json`
- `python3 run.py --source apple`：parsed 60, created 2, updated 58
- `python3 run.py --source siemens`：parsed 6, created 6, updated 0
- `python3 run.py --source baidu`：parsed 10, created 10, updated 0
- 浏览器登录验证：`test@jobradar.local` 可登录，进入 Today / Jobs 页面正常读取岗位
- Jobs 页实时搜索验证：关键词“算法”命中 30 条可操作岗位，官网源 2 个，约 20s 返回
- 岗位动作验证：实时搜索结果点击“收藏”后会稳定显示“★ 已收藏”，Saved 页可读到新增收藏
- 实时搜索扩源验证：新增 Greenhouse / Lever 通用 ATS 层；关键词 `machine learning`、`limit=12` 返回 12 条，覆盖 8 个实时源（Apple、百度、Anthropic、Figma、Reddit、Discord、Airtable、Cloudflare），约 13s 返回

### 本轮修复

- `middleware.ts`：排除 `/api/*`，避免 API 未登录时被页面重定向拦截；现在 `/api/search` 未登录返回 `401 application/json`
- `components/JobCard.tsx`、`app/jobs/jobs-client.tsx`、`app/today-client.tsx`、`app/saved/saved-client.tsx`：修复实时搜索结果写入收藏/投递/忽略后被强制 remount 抹掉视觉状态的问题
- `lib/live-search.js`、`app/api/search/route.ts`：新增 Greenhouse / Lever 通用实时搜索，默认候选源 22 个；支持中文关键词扩展到英文 ATS 关键词，并按来源交错展示，避免结果被单一公司刷屏
- 注意：不要在 dev server 运行期间跑 `npm run build` 后直接做浏览器验证；build 会改写 `.next`，旧 dev server 会出现 `_next/static/chunks/...` 404，导致页面没有 hydration。build 后要重启 `npm run dev`

## 2026-05-22 续跑结果

- 额度恢复后已重启 dev server；当前本地服务在 `http://localhost:3000`
- 未登录访问 `/jobs`：307 跳转 `/login`
- 浏览器登录态访问 Jobs：岗位库已增至 186 个，筛选公司里已出现 Apple、Anthropic、百度、Twilio、Figma、Cloudflare、Reddit、Discord、Airtable、Siemens
- UI 实时搜索 `machine learning`：命中 30 条可操作岗位，官网源 9 个，约 28s 返回
- 已补 Greenhouse HTML entity 清洗，避免摘要露出 `<div>` / `&quot;` 一类标签残留
- 最新验证：`node --test tests/*.test.js` 13 passed；crawler unittest 9 passed；`npm run build` passed；`git diff --check` passed

## 当前已知限制

- Apple / Siemens 已完成端到端高质量 source 验证。
- 百度已完成解析、详情链接验证和写 Supabase 复测。
- 海尔需要重新找真实公开 API/DOM 后再启用；京东已恢复并通过真实岗位写入复测。
- 本地环境如果 sandbox 禁止监听端口，需要用户本机直接执行 `npm run dev` 验证页面。
- Vercel 部署如需实时搜索 upsert，必须配置 `SUPABASE_SERVICE_ROLE_KEY` 作为服务端环境变量，不能暴露到浏览器。
