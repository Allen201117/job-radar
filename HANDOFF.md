# 交接文档 — 数据库空间危机 + 三个连带故障

> 写给接手的 agent（Codex）。你**没有**之前的对话上下文，本文件自包含。
> 日期：2026-06-14。项目：求职雷达 / Job Radar（Next.js 14 + Supabase + Python crawler）。
> 先读根目录 `CLAUDE.md` 建立认知，但**凡涉及运行行为以代码为准，不要盲信文档/注释**。

---

## 0. TL;DR（最高优先级）

**根问题：Supabase 免费版数据库满了**（668MB > 500MB 上限，`EXCEEDING USAGE LIMITS`，多项资源耗尽、性能受影响）。它连带触发了三个故障：① 数据库迁移卡住没 apply；② 线上代码与 schema 不一致；③ Workday 岗位链接系统性拼错（两万条伪 404）。

**关键判断（已和用户确认）**：免费清理在"满死"状态下走不通（论证见 §5）。**推荐路径 = 升 Supabase Pro 一个月做一次性大扫除，扫到 500MB 以下后降级回 Free**（详见 §6）。用户仍在考虑是否付费——**在用户明确同意付费/或给出新指令前，不要擅自做不可逆的生产数据操作**（删行、VACUUM FULL、批量 UPDATE）。

**你能先做、不依赖数据库空间的事**：修 `crawler/adapters/workday.py` 的链接构造 bug（§4.2，纯代码改动，让以后新抓的 workday 链接正确）+ 准备好所有待执行 SQL（§6/§7）。

---

## 1. 产品与技术栈（背景）

- 求职雷达：聚合**企业官方招聘源**的岗位雷达，核心承诺"点开就是真实可投的官方岗位详情页"。
- 前端 Next.js 14（Vercel 部署，push main 自动部署）；Supabase（Postgres + Auth + RLS + PostgREST + RPC）；Python crawler（httpx + Playwright，GitHub Actions 定时跑）。
- 数据库迁移**自动化**：push 到 main 且改动 `supabase/migrations/**` → `.github/workflows/migrate.yml` 用 `scripts/db-migrate.sh` 自动 apply（`schema_migrations` 表记录版本，单事务 `-1` 应用，失败整体回滚且**不记录版本**）。

---

## 2. 核心危机：数据库空间满

诊断结果（Supabase SQL Editor 实测）：

- 总用量 **668MB > 500MB** 免费上限。Project ref: `gkrfwhrppqztpxrtovhf`（FREE 计划）。
- **大头是 `jobs` 单表 651MB（占 98%）** = 表数据 245MB + 索引 91MB + TOAST ≈ 315MB（**主要是 `summary` 字段**，JD 正文长文本，外存 TOAST）。
- 其他表全部 < 2MB（`crawl_runs` 1.1MB、`discovery_runs` 0.6MB…）→ **删日志表毫无意义，腾不出空间**。
- `jobs` 行数：`status='active'` **19933** 行，`status='expired'` 仅 **45** 行（见 §3.3，这个反差暴露了死链检测失效）。
- `jobs` 索引清单（按大小，**全是高频在用的，DROP 不掉**）：
  | 索引 | 大小 | 被查询次数 |
  |---|---|---|
  | `jobs_company_title_location_jd_url_key` | 36MB | 311254 |
  | `jobs_search_doc_gin`（当前搜索核心） | 25MB | 33 |
  | `jobs_pkey` | 8MB | 533138 |
  | `jobs_status_first_seen_idx` | 6.7MB | 371 |
  | `idx_jobs_first_seen` | 4.5MB | 492 |
  - 旧 trigram 索引（v1 遗留）已被 migration 139 清理或极小，**DROP 索引腾不出可用空间**。

---

## 3. 三个连带故障

### 3.1 迁移 144/145 卡住没 apply（线上 schema 落后于代码）

- 已 push 的迁移（在 origin/main，HEAD `2bc0f7c`）：
  - `supabase/migrations/144_jobs_canonical_jd_url.sql` — 加 `canonical_jd_url` 列 + 回填 + 触发器 + **dedup 存量重复（降级 removed）** + active partial unique index。
  - `supabase/migrations/145_active_job_counts_by_company.sql` — `active_job_counts_by_company()` RPC（career-path 用）。
- **`db-migrate` workflow 失败两次**：
  1. 第一次：`144:79` 全表回填 `update jobs set canonical_jd_url = canonicalize_jd_url(jd_url)` 撞 **statement timeout**（Supabase 默认 ~2min）。→ **已修复**：144 顶部加了 `set local statement_timeout = '1800s';`（已 commit & push）。
  2. 第二次：超时修好了（回填跑过了），但卡在 `144:118` 建索引 → **`ERROR: could not extend file: No space left on device`（磁盘满）**。← **当前卡在这里**。
- 后果：144 单事务回滚 → **144 和 145 都没 apply，schema 停在 143**。但**代码已部署 Vercel**，于是：
  - `app/api/career-path/route.ts` 调用不存在的 `active_job_counts_by_company()` RPC → 报错。
  - crawler `crawler/db.py` upsert 用不存在的 `canonical_jd_url` 列 → 每日 `daily-crawl` 写入会失败。
- **重跑方式**：144 失败未记入 `schema_migrations`，**空间解决后**手动 `gh run rerun <db-migrate run id>`（或再 push 一次 migrations 改动）即可自动重试 144→145。

### 3.2 （= 3.1 的后果）线上代码 ↔ schema 不一致

空间一解决、迁移 144/145 跑成功，这条自动消失。**不要为此回滚代码**——正解是把迁移跑通。

### 3.3 Workday 岗位链接系统性拼错（两万条伪 404）

- 现象：用户反馈"大部分 workday 公司岗位点进去都是 The page you are looking for doesn't exist"。
- **根因已确认**（用真实在招 URL 对比）：

  | | 路径格式 |
  |---|---|
  | ✅ 真实在招 | `https://workday.wd5.myworkdayjobs.com/en-US/Workday/`**`details`**`/{标题}_{编号}` |
  | ❌ 我们生成 | `https://workday.wd5.myworkdayjobs.com/Workday/`**`job/{城市}`**`/{标题}_{编号}` |

  两处系统性错误：① **缺 `/en-US/` 语言段**；② 用了 `job/{城市}/`，但对外正确格式是 **`details/`（无城市段）**。
- 代码位置：[crawler/adapters/workday.py:206](crawler/adapters/workday.py) — `jd_url = f"{host}/{site}{ep}"`，其中 `ep` = CXS API 返回的 `externalPath`（= `/job/{城市}/{标题}_{编号}`，这是 **API 内部路径，不是对外可访问路径**）。
- **重要：这些岗位大多是真实在招的，是链接拼错，要"修链接"，绝对不要当死岗删除！**
- 样本（可用于验证）：
  - ✅ 能开：`https://workday.wd5.myworkdayjobs.com/en-US/Workday/details/Senior-Cybersecurity-Data-Engineer---AI-ML-SME_JR-0107814`
  - ❌ 404：`https://workday.wd5.myworkdayjobs.com/Workday/job/Hong-Kong/Senior-Director--Asia-Product-Risk-Management_JR26031579-1`
- **待验证假设**：上面真实 URL 用 `en-US`。但有租户用别的语言段（如 `otis` 那条历史 URL 是 `zh-CN`）。改 adapter 前，**让用户在浏览器验证一个"修复后格式"的 URL 能打开**，确认 `en-US` 是否对各租户通用（Workday 多数租户 `en-US` 通用，但需确认）。

### 3.4 死链检测失效（盲区，导致伪岗藏在 active）

- `active 19933` vs `expired 45` 的反差说明：死链检测几乎没在工作，下架岗大量伪装成 active。
- 已有 `crawler/audit_dead_links.py`（无头渲染识别 SPA 软 404）+ `.github/workflows/dead-link-audit.yml`，但显然没覆盖到/没全量跑 workday。
- 修完 §3.3 的链接 bug 后，对 workday 岗**重跑死链审计**：修了链接仍 404 的，才是真死岗，才 expire/删。

---

## 4. 待办（按依赖顺序）

### 4.1 【阻塞】先解决数据库空间（见 §5/§6）—— 其余 DB 操作都依赖它

### 4.2 修 Workday 链接构造 bug（可立即做，纯代码）

- **adapter 修复**：`crawler/adapters/workday.py:206`
  - 现：`jd_url = f"{host}/{site}{ep}"`
  - 改为（取 `externalPath` 最后一段 `{标题}_{编号}`，重组为对外 details 格式）：
    ```python
    # externalPath = /job/{城市}/{标题}_{编号}（CXS API 内部路径）；
    # 对外可访问页 = {host}/{locale}/{site}/details/{标题}_{编号}
    slug = ep.rsplit("/", 1)[-1]          # {标题}_{编号}
    jd_url = f"{host}/en-US/{site}/details/{slug}"
    ```
  - ⚠️ **不要动** detail 抓取那段（`workday.py:118` 附近 `GET {host}{externalPath}`）——那个用的是 CXS API 端点，是对的。只改对外展示的 `jd_url`（206 行）。
  - ⚠️ `en-US` 通用性见 §3.3 待验证假设；可能需要从 source 配置/CXS 响应推导 locale，或对个别 `zh-CN` 租户特判。改完更新注释（第 10 行的"已 live 验证"那句已不准）。
- **存量批量修复 SQL（草案，空间解决后执行）**：把现有 `myworkdayjobs.com` 的 `jd_url` 从旧格式转新格式。
  ```sql
  -- 草案，执行前先 SELECT 验证 regex 命中正确、抽样比对几条
  update jobs
  set jd_url = regexp_replace(
        jd_url,
        '^(https://[^/]+)/([^/]+)/job/[^/]+/(.+)$',  -- {host}/{site}/job/{城市}/{slug}
        '\1/en-US/\2/details/\3'                      -- {host}/en-US/{site}/details/{slug}
      )
  where jd_url ~ 'myworkdayjobs\.com/[^/]+/job/';
  ```
  - ⚠️ 这是大表 UPDATE，受 §5 满死限制；且会触发 `canonical_jd_url` 触发器重算（144 apply 后）。先小范围 `SELECT ... LIMIT` 验证再全量。
  - ⚠️ 改完务必让用户 live 验证若干条修复后的链接能打开。

### 4.3 修完 workday 链接后，重跑死链审计揪真死岗（见 §3.4）

---

## 5. 关键约束与陷阱（务必遵守）

1. **canonical_jd_url 三处实现必须字节一致**：`lib/canonical-url.js` / `crawler/normalizer.py` / `supabase/migrations/144_*.sql` 的 SQL 函数。改一处必三处同改，并同步两套测试 `tests/canonical-url.test.js` + `crawler/test_canonical.py`。（已写进 CLAUDE.md。）
2. **迁移自动 apply 的爆炸半径**：push 改 `migrations/**` 会自动上生产。加唯一约束**前必先 dedup**（144 已做）；大表全表回填/建索引**必须 `set local statement_timeout`**（144 已加 1800s）。否则失败会回滚并阻塞后续迁移。
3. **满死死结**（为什么免费清理走不通，已逐一验证）：
   - `DELETE`/`UPDATE` 都先产生 dead tuple（**占空间**），满死状态可能直接失败。
   - `VACUUM FULL` 缩表需要 ≈ 表大小的额外空间，满死跑不动。
   - `DROP INDEX` 是满死下唯一不需额外空间的腾挪手段，但 `jobs` 大索引全有用（§2），删不掉的没用索引太小。
   - 换平台（自托管 Supabase / 微信小程序云开发 / Cloudflare D1）均已评估否决：要么免费额度更小（D1 单库 500MB < 现有 651MB），要么需重写 Auth/数据访问/搜索（SQLite 无 pg_trgm/RLS/PLpgSQL），工作量远超收益。
4. **瘦 summary 是安全的**：当前搜索（migration 142 的 `search_doc`）只索引 title/company/location/job_type，**不含 summary**（142 注释明确）。所以截断/清空 `summary` 不影响搜索召回。（但仍受满死限制，UPDATE 要先有空间。）
5. **改匹配/搜索代码必保 4 套匹配测试全绿**：`keyword-match-tier` / `cross-language-recall` / `china-radar-filter` / `classify-job-function`。
6. **Workday 是修链接不删岗**（§3.3）。
7. **不读/不打印** `.env*`、service_role key 等密钥。

---

## 6. 推荐解决方案：升 Pro 一个月做大扫除 → 降级

用户在考虑是否付费。**若用户同意**，按此一条龙执行（每步做完核对再下一步）：

1. 用户升 Supabase Pro（8GB，随时可降级）。
2. `gh run rerun <失败的 db-migrate run id>`（或 push 触发）→ 让 144/145 apply（空间够了，建索引不再 No space）。验证 workflow 绿。
3. 修 Workday 链接：合入 §4.2 的 adapter 改动 + 跑存量 UPDATE SQL（先抽样验证）。
4. **瘦 summary**（§5.4 安全）：`update jobs set summary = left(summary, 300) where length(summary) > 300;`（或按产品决定清空/短摘要）→ 释放 TOAST 大头。
5. 重跑死链审计（§3.4），删/expire 真死岗。
6. `VACUUM FULL jobs;`（此时有空间）→ 真正回收，把 651MB 压下来。
7. 确认总用量 < 500MB → **降级回 Free**。
- 净成本：一次性约 $25，做完降回免费。

**若用户坚持免费**：如实告知 §5.3 死结——当前状态免费基本无解；唯一可尝试是 DROP 掉确认没用过（`idx_scan=0`）的小索引腾几 MB + 极限分批操作，但大概率仍降不到 500MB 以下。不要给用户"免费一定能搞定"的错觉。

---

## 7. 当前 git / 迁移状态

- 分支 `main`，HEAD = `2bc0f7c`，**本地与 origin/main 已同步**（0 领先）。
- 近期相关 commit：
  - `2bc0f7c` fix(db): 迁移144回填抬高 statement_timeout
  - `2053a6a` docs(CLAUDE): 固化 canonical_jd_url 三处同步约束
  - `1869967` feat(db): jobs 唯一性下沉到 DB（144 原始版）
  - `a0ec076` perf(career-path): 在招计数下沉到 DB 聚合（145）
- 生产库 schema 实际停在 **143**（144/145 未 apply，等空间）。
- 仓库根另有 `CODEX_REVIEW.md`（更早一轮全局审阅，可选读）。

---

## 8. 环境与验证

- 运行前提：`.env.local` 含 Supabase 凭证（**勿读勿打印**）。
- **沙箱可能连不上 Supabase / GitHub / 外网** → live SQL、live 链接验证、`git push` 这类需用户本机执行，别用本地单测冒充 live 验证。
- 回归四件套 + lint：
  ```bash
  node --test tests/*.test.js
  python3 -m unittest discover -s crawler -t crawler -p "test_*.py"
  npm run build
  npm run lint
  git diff --check
  ```
- 审计脚本：`node scripts/audit-job-duplicates.js`（只读，看 144 dedup 会降级多少行）。

---

## 9. 给接手 agent 的第一步建议

1. 读本文件 + `CLAUDE.md` + `crawler/adapters/workday.py`（确认 §3.3/§4.2）。
2. **不依赖空间、可立即做**：实现 §4.2 的 adapter 链接修复（先和用户确认 `en-US` 通用性），跑 crawler 单测。
3. 其余（迁移重跑、瘦 summary、删死岗、VACUUM）**全部阻塞在数据库空间**——等用户对 §6 的付费决策给出明确指示后再动；在此之前不要执行任何不可逆的生产 DB 操作。
