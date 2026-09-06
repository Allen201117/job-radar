# 匹配与登录 GET 取证账本

对应 [主报告](../2026-09-06-first-principles-review.md)。以下命令是已执行步骤的记录，不是建议再次使用未校验身份的连接。生产重核应使用现有 verify-full 通道。

本文件只整理 2026-09-06 已完成的证据，不重新执行生产查询、HTTP 请求或测试。无 DSN、主机、用户标识、邮箱、cookie、token、画像正文或岗位正文。

## 1. TLS 证据层

对当时本机 `.env.local` 只检查配置形态、不输出值：jobs DSN 存在，query 中 `sslmode=require`；没有 `PGSSLMODE`、`PGSSLROOTCERT`、`JOBS_DATABASE_SSL_CA`。因此：

- `临时取证目录/job-radar-live-core-replay.js` 与 `临时取证目录/job-radar-stage-gap-count.js` 的 `psql` 通道有传输加密，但**没有 CA 链与主机名校验，不是 verify-full**。
- `临时取证目录/job-radar-live-feed-replay.js` 调用仓库严格 Node jobs helper 时，17 个可召回输入均分类为 `tls_error`；它没有降级。另 11 个输入在发 jobs 查询前即因部分输入 not-ready 返回。
- 本轮不再执行或降低严格校验。两份 psql 结果只作为辅助诊断，不能称为严格生产直连证据。
- `临时取证目录/job-radar-auth-read-smoke.js` 的生产读链走自定义域 HTTPS，使用 Node fetch 的标准证书校验；这是实际应用层证据。

## 2. 28 份匿名输入与 17 份核心回放

输入：

- `临时取证目录/job-radar-review-20260906-data-matching-replay-28.json`
- `临时取证目录/job-radar-review-20260906-data-matching-replay-28-summary.json`
- 两者 mtime：`2026-09-06T15:40:51+0800`

输入完整性复核：28 份均无 user_id、邮箱、简历原文；收集器没有跨用户表做身份关联，因此 28 份的 `targetCompanies`、`targetKeywords` 全为空。11 份 targetRoles 为空，其中 9 份有 skills、2 份有 location；生产 readiness 只认 roles/keywords/companies（`lib/opportunities/profile.ts:102-124`），所以“11 not-ready”只是部分输入的结果，**不能解释成 11 个真实用户的 Today 为空**。

执行命令：

```text
node 临时取证目录/job-radar-live-core-replay.js
```

脚本 mtime `2026-09-06T21:51:09+0800`，创建后立即前台执行，运行窗口约 21:51–21:54 CST；原脚本没有逐行时间戳。机器可读汇总：

- `临时取证目录/job-radar-review-20260906-matching-replay-summary.log`

17 份带角色输入执行生产 `buildRecallSql(7d, 1800) → stripTierColumns → computeMatchFacts → checkEligibility → scoreOpportunity`：候选合计 14,281，eligible 1,341；2/17 capped。拒绝合计：role 8,411、location 2,262、stage 1,554、industry 684、stale 29。query 本机中位 5,632ms / P90 32,481ms；compute 中位 28ms。query 时间包含审查机网络、libpq 握手和结果传输，不是 Vercel 延迟。回放没有 sourceMeta、critical、group、hydrate。

## 3. Today 招聘类型前置谓词差异

执行命令：

```text
node 临时取证目录/job-radar-stage-gap-count.js
```

脚本 mtime `2026-09-06T21:55:14+0800`，创建后立即执行。机器可读结果：

- `临时取证目录/job-radar-review-20260906-stage-gap-summary.log`

实际脚本使用等值字面量；为便于复核且避免连接信息，下面给出相同统计口径的参数化 SQL：

```sql
with base as (
  select recruitment_category, title, job_type, jd_url
  from jobs
  where status = 'active'
    and last_seen_at >= now() - ($1::int * interval '1 day')
    and summary is not null
    and char_length(btrim(summary)) >= 60
    and coalesce(job_scope, 'domestic') = 'domestic'
    and recruitment_explicit is true
    and recruitment_category in ('校招', '实习')
    and not (
      recruitment_category in ('校招', '实习')
      and grad_class is not null
      and grad_class < $2::int
    )
), evaluated as (
  select *,
    case when recruitment_category = '校招' then
      lower(title) like any($3::text[])
      or lower(coalesce(job_type, '')) like any($3::text[])
      or lower(coalesce(jd_url, '')) like any($4::text[])
    else
      lower(title) like any($5::text[])
      or lower(coalesce(job_type, '')) like any($5::text[])
      or lower(coalesce(jd_url, '')) like any($6::text[])
    end as today_prefilter
  from base
)
select recruitment_category,
       count(*) as total,
       count(*) filter (where not today_prefilter) as not_matching_prefilter,
       round(100.0 * count(*) filter (where not today_prefilter) / nullif(count(*), 0), 1) as gap_pct
from evaluated
group by recruitment_category
order by recruitment_category;
```

本次实际参数：`$1=7`，`$2=2026`，`$3={%校招%,%校园%,%应届%,%campus%,%graduate%,%届%}`，`$4={%campus%}`，`$5={%实习%,%intern%}`，`$6={%shixi%,%intern%}`。

结果：实习 21,583 / gap 0；校招 42,921 / gap 1,328（3.1%）。**复核发现当季参数错误：`lib/grad-class.js:73` 在九月返回 2027，本次使用了 2026。因此该比例不能代表当前生产当季的漏召回率。**它仅是较宽岗位集合的谓词差异；某个用户是否实际少看到岗位，还取决于角色/公司/城市召回及后置硬门。后续严格 TLS 重核必须直接复用生产的当季参数，不能继续手抄常量。本轮没有重跑此查询。

## 4. 登录态生产 GET

执行命令：

```text
node 临时取证目录/job-radar-auth-read-smoke.js
```

脚本 mtime `2026-09-06T21:57:16+0800`，创建后立即运行约 32.5 秒，取数窗口约 21:57–21:58 CST；原脚本没有逐请求时间戳。会话 cookie 只存在进程内。机器可读结果：

- `临时取证目录/job-radar-review-20260906-auth-read-smoke-summary.log`

| GET | status | wall time | response bytes | 关键读回 |
|---|---:|---:|---:|---|
| `/today?__timing=1` | 200 | 6,960ms | 378,482 | SSR HTML |
| `/jobs` | 200 | 823ms | 207,207 | SSR HTML |
| `/api/opportunities` | 200 | 4,039ms | 54,289 | capped=true；screened=1,290；mismatch=799；main=20；内部 total=1,944ms |
| `/api/jobs/search?limit=10&sortBy=match` | 200 | 25,175ms | 16,337 | capped=true；returned=10 |

单次结果只能证明路径可触发，不能代表冷/热分布、P50 或 P95。完成测试账号的常规认证后，业务测量仅做 GET，没有调用业务 POST、liveness、radar/open 或写接口；认证所需会话不属于本次业务数据修改。

## 5. 相关测试

执行命令与 8 个文件：

```text
node --test \
  tests/opportunity-recall-two-phase.test.js \
  tests/opportunity-recall-function-prune.test.js \
  tests/opportunity-recall-payload.test.js \
  tests/opportunity-eligibility.test.js \
  tests/jobs-store-candidate-window.test.js \
  tests/search-retrieval.test.js \
  tests/opportunity-api-security.test.js \
  tests/jobs-database-tls-contract.test.js
```

结果：110 tests / 110 pass / 0 fail，runner duration 995.18675ms。机器可读转录：

- `临时取证目录/job-radar-review-20260906-matching-tests-summary.log`

匹配角色的原始测试输出在前台工具中，没有重定向到磁盘；上述 log 明确标为转录汇总，避免把后补文件冒充原始执行日志。主线程于 2026-09-07 又执行同一组 8 文件，实际 reporter 为 ℹ 格式，110 通过、0 失败/取消/跳过；输出只保留在本地临时日志。

## 6. 最小规则反例

- 脚本：`matching-repro.js`（已改为仓库相对路径版本）
- mtime：`2026-09-06T21:58:28+0800`
- 命令：`node docs/reviews/2026-09-06-evidence/matching-repro.js`

它直接调用生产纯函数，验证两件事：校招“管培生”后置 `stage=match + eligible`，但 Today 前置字段模式不命中；正文含“产品经理”的“战略项目岗”被后置判 related + eligible，但物化 search_doc 不含该方向。两者是合成岗位反例，用来证明规则关系，不冒充生产岗位抽样。
