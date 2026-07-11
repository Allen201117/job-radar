# Jobs 数据库生产安全门

本文是独立 PostgreSQL 岗位库的发布门。每一项必须明确标记为“已确认”“未验证”或“验收证据”；没有证据的配置不得口头视为完成。任何命令都只能引用环境变量或 secret 名称，绝不在终端、CI 日志、工单或本文中打印连接串、私钥、证书内容、真实主机、账号或密码。

## 当前状态摘要

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| TLS 证书校验 | 代码与 secret 已配置，待生产回归 | Next、Python crawler、psql/pg_dump 工作流与校验脚本均已切到 CA + 完整身份校验；Vercel/GitHub 已配置对应 secret。本机握手正负测试通过，但生产 API/Actions 仍须在本次部署后回归。 |
| 每日加密快照 | 未验证；本次限时例外已批准 | 腾讯云控制台需要交互登录，当前发布会话无法取得证据；批准记录 [#3 comment](https://github.com/Allen201117/job-radar/issues/3#issuecomment-4944776071)，2026-07-18 到期。 |
| PITR / RPO / RTO | 未验证；本次限时例外已批准 | 同一批准记录；不得把本次应用发布写成基础设施验收完成，例外到期后恢复阻塞。 |
| 最新季度恢复演练 | 未验证；本次限时例外已批准 | 尚无可引用的演练记录，跟踪 [#3](https://github.com/Allen201117/job-radar/issues/3)。 |
| 连接容量 | 实时值未验证；本次限时例外已批准 | 仓库记录 `max_connections=100`、应用池 `max: 5`；实时占用/告警试触发跟踪 [#3](https://github.com/Allen201117/job-radar/issues/3)。 |
| 生产依赖 high/critical | 已确认 | `npm audit --omit=dev --audit-level=high --json` 退出 0；这不等于完成 moderate 正式风险接受。 |
| PostCSS moderate 风险 | 已限时接受 | 0 high/critical、2 moderate；接受记录、责任人与到期日在 [#2](https://github.com/Allen201117/job-radar/issues/2)，到期 2026-08-11。 |

## 1. TLS

### 已确认（2026-07-11）

- `lib/jobs-store/client.ts` 已读取 `JOBS_DATABASE_SSL_CA` 与 `JOBS_DATABASE_TLS_SERVERNAME`，并强制 `rejectUnauthorized: true`；缺少 CA 时拒绝连接，不再静默降级。
- `crawler/jobs_db.py` 强制 libpq `verify-full`；IP 端点通过 `hostaddr` 连接、通过逻辑 `host` 校验证书名。所有直接调用 psql/pg_dump 的 jobs 工作流先 source `scripts/enable-jobs-db-strict-tls.sh`，两个数据库校验脚本也已移除 `rejectUnauthorized:false`。
- Vercel Production/Preview 与 GitHub Actions 已配置上述两个敏感变量；GitHub secret 元数据更新时间为 2026-07-11，变量值不得进入仓库或发布日志。
- 当前自签证书只声明 `localhost.localdomain`，因此通过固定叶证书作为信任根，并显式校验该证书服务器名。OpenSSL 以固定证书 + 正确服务器名返回 0，以公网主机名校验返回 hostname mismatch，证明负向门生效。

### 待部署后验证

GitHub Actions 严格 libpq 路径已验证：[`jobs-db-migrate` 29148768528](https://github.com/Allen201117/job-radar/actions/runs/29148768528) 的 schema apply/verify 成功；[`db-report` 29148836335](https://github.com/Allen201117/job-radar/actions/runs/29148836335) 的只读质量审计成功。生产部署后仍必须调用 `/api/jobs/stats` 与关键只读 jobs API，并检查 Vercel 日志中没有证书、连接和 5xx 错误。

固定叶证书轮换必须使用双信任窗口：先把旧证书与新证书组成 CA bundle 更新到 secret 并重新部署；验证应用与工作流仍可连接后再轮换数据库服务端证书；再次完成正向/负向测试后，最后从 secret 移除旧证书并重新部署。禁止先替换为仅含新证书的 secret，否则旧服务端证书会被立即拒绝。

### 验收证据

- Secret 管理后台截图或变更记录：仅显示 secret 名称、版本、更新时间和责任人，必须遮蔽值。
- 使用生产同等网络与证书校验路径的连接测试，记录命令退出码和时间；禁止 `echo`、`env`、`set -x` 或异常栈输出密钥。
- 负向测试：使用不受信 CA 或错误主机名必须连接失败。
- 正向测试：可信 CA 与正确主机名连接成功，并以只读查询 `select 1` 留存退出码。
- 代码发布记录明确显示不再使用 `rejectUnauthorized: false`，并关联回滚版本。

## 2. 备份

### 未验证

以下四项当前全部未验证，不得填入推测值：

- 每日加密快照是否启用：未验证。
- 备份保留期：未验证。
- 备份责任人：未验证。
- 证据位置（控制台、工单或不可变审计存储）：未验证。

### 核验要求

平台负责人应在数据库供应商控制台核对最近 7 天快照时间、成功状态、静态加密状态与到期时间，并导出不含凭据的审计证据。若供应商提供 CLI，可运行只列备份元数据的命令，将实际 CLI 名称、账号/项目别名和区域由负责人填写；命令不得返回连接串或密钥。

验收记录必须填写：

```text
每日快照：未验证 / 已确认
加密状态：未验证 / 已确认
保留期：未验证 / ______ 天
责任人：未验证 / ______
证据位置：未验证 / ______
核验时间：______
核验人：______
```

## 3. PITR、RPO 与 RTO 接受门

### 未验证

- PITR 是否启用、可恢复时间窗口：未验证。
- RPO：未验证。
- RTO：未验证。
- 业务负责人对数据丢失和停机目标的接受：未签字。

### 必须填写并签字

```text
PITR：未验证 / 已确认
可恢复时间窗口：______
RPO 目标：______
RTO 目标：______
平台负责人：______  签字/日期：______
业务负责人：______  签字/日期：______
安全/发布负责人：______  签字/日期：______
验收证据位置：______
```

常规规则：任何空项、未签字或只有口头承诺的记录都不满足发布门。本次唯一例外由仓库发布负责人通过认证 GitHub 会话于 2026-07-11 批准，证据为 [#3 comment](https://github.com/Allen201117/job-radar/issues/3#issuecomment-4944776071)，仅允许本次应用发布，2026-07-18 到期；它不代表备份/PITR/RPO/RTO 已通过，到期后未关闭 #3 则所有后续发布恢复阻塞。

## 4. 季度恢复演练

最新演练状态：未验证。

每季度至少执行一次：

1. 选择已验证的快照或 PITR 时间点，记录恢复请求时间与目标恢复点。
2. 恢复到与生产隔离的临时实例；禁止覆盖生产、复用生产写入端点或向真实下游发送事件。
3. 使用只读账号核对 schema/migration 版本、关键表行数，并与源证据比较。
4. 对 `jobs` 等关键表做脱敏抽样，校验主键、时间范围、状态分布与引用完整性；不得复制或展示秘密字段。
5. 记录达到可查询状态与完成业务校验的时间，用于对照已签字 RTO；记录恢复点差异，用于对照 RPO。
6. 演练结束后撤销临时凭据、销毁隔离实例，并保留销毁审计证据。

记录模板：

```text
演练日期：未验证 / ______
演练负责人：______
快照/PITR 标识（不含凭据）：______
隔离环境：______
关键表行数校验：______
脱敏抽样结果：______
实际恢复点差异：______
实际恢复耗时：______
销毁时间及证据：______
异常与整改项：______
证据位置：______
复核人及日期：______
```

## 5. 容量与告警

### 已确认的仓库事实

- 仓库运维记录中的 PostgreSQL `max_connections=100`。
- `lib/jobs-store/client.ts` 的单个应用实例连接池上限为 `max: 5`。

这些事实不等于生产实时值或全局总占用已验证。发布前由数据库负责人使用受控只读会话执行下列查询；客户端不得开启命令回显：

```sql
show max_connections;
select count(*) as used_connections from pg_stat_activity;
select application_name, state, count(*)
from pg_stat_activity
group by application_name, state
order by count(*) desc;
```

### 建议阈值与升级路径

以下是建议，不是已启用配置：

- 连接占用持续 5 分钟达到 70%：warning，通知当班平台负责人，检查实例扩张、慢查询和空闲连接。
- 连接占用持续 5 分钟达到 85%：critical，暂停非必要 crawler/批任务，升级数据库负责人和发布负责人。
- 达到 95% 或出现连接拒绝：事故响应，冻结发布，按降载顺序停止非关键写入并评估回滚。

正式告警阈值、接收人、值班升级路径和监控证据位置均为未验证，必须在上线前填写并试触发一次。

## 6. 依赖安全门

发布验收运行：

```bash
npm audit --omit=dev --audit-level=high --json
```

该命令用于让 high/critical 为 0 时退出 0；通过该门不等于自动接受 moderate。另行读取 raw audit 可见 2 个 moderate，均由 Next.js 内嵌 PostCSS 8.4.31 引起。当前仓库检查未发现将不可信 CSS AST stringify 后注入 `<style>` 的运行时路径；本轮已按下列记录完成限时接受。每周及每次依赖升级必须复查公告、运行路径和修复版本。禁止执行 `npm audit fix --force`，其建议可能错误降级当前支持线。

```text
风险范围：Next.js 内嵌 PostCSS 的 GHSA-qx2v-qp2m-jg93
临时风险责任人：仓库发布负责人
接受日期：2026-07-11
复查日期：2026-07-18
风险到期日：2026-08-11
批准人及签字：仓库发布负责人通过认证 GitHub 会话创建接受记录
复查证据位置：https://github.com/Allen201117/job-radar/issues/2
```

正式接受记录：[#2](https://github.com/Allen201117/job-radar/issues/2)。接受日期 2026-07-11，责任人/批准人为仓库发布负责人，下次复查 2026-07-18，到期 2026-08-11。到期前必须升级到修复版本或重新评估并取得新签字；每周复查必须附 raw audit、公告状态和运行路径复核证据。任一条件不满足时恢复“发布阻塞”。

维护项：Next 15 的 `next lint` 已提示将在 Next 16 移除，后续应从 ESLint 8 / `next lint` 迁移到受支持的 ESLint CLI。该维护项不阻塞本轮 Next 15.5.18 上线，本任务不实施迁移。

## 7. 上线顺序与回滚

本轮由不安全连接原子切换为严格 TLS，必须按以下顺序执行：

1. 先在 Vercel/GitHub 配置可信 CA 与证书服务器名；证据只记录 secret 名称与更新时间。
2. 部署不含不安全 fallback 的严格 TLS 代码到 Preview，验证 `/api/jobs/stats`、关键只读 API 与错误证书负向路径。
3. 手动运行 `jobs-db-migrate`/`db-report`，证明 crawler/libpq/psql 路径使用同一 CA + `verify-full` 成功。
4. 合并 main 触发生产部署，观察错误率、连接占用和查询延迟；失败立即恢复 known-good deployment，并保持整改事件开启。
5. 本次依据 [限时发布例外](https://github.com/Allen201117/job-radar/issues/3#issuecomment-4944776071) 合并；备份、PITR/RPO/RTO、恢复演练和容量证据须在 2026-07-18 前按 #3 补齐，不得声称基础设施验收通过。例外不可复用于后续发布。

### 发布前登记门

以下字段必须在发布单中登记；只能记录 URL/ID 或 secret 版本编号，禁止记录 secret 值。任一项为空或未验证时禁止发布：

```text
Known-good deployment URL：https://job-radar-d5sguli7w-allens-projects-5408d95e.vercel.app
Known-good GitHub deployment ID：5397279031（main 8c7e1f3）
当前 CA secret reference：Vercel Production/Preview added 2026-07-11；GitHub Actions updated 2026-07-11T09:58:36Z
回滚 CA secret reference：上一 known-good 不读取 CA；仅在生产故障时按 #3 的限时例外回滚，严格 TLS 整改保持开启
Vercel 项目/环境标识：allens-projects-5408d95e/job-radar，Production + Preview
发布负责人：仓库发布负责人（GitHub authenticated account Allen201117）
登记证据位置：PR #4、GitHub deployment 5402830311、Actions runs 29148768528 / 29148836335、issue #3 comment 4944776071
```

### 建议回滚触发器

以下阈值均为建议，监控规则是否已配置和试触发仍为未验证：

- `/api/jobs/stats` 或核心 jobs API 的 5xx 错误率连续 5 分钟达到 5%。
- 数据库 TLS 证书/主机名校验错误连续出现 5 分钟，或数据库连接错误率在 5 分钟窗口达到 2%。
- 数据库连接占用连续 5 分钟达到 85%，或出现连接拒绝。
- jobs API p95 延迟连续 10 分钟超过发布前基线的 2 倍。

### 可执行回滚

1. 冻结继续发布和非必要批任务，记录触发指标、开始时间与负责人。
2. 在 Vercel Dashboard 将已登记的 known-good deployment Promote to Production，或使用：

   ```bash
   vercel promote "$KNOWN_GOOD_DEPLOYMENT_URL"
   ```

3. 在 secret provider 控制台把应用引用恢复到已登记的 CA secret version；只记录版本编号和审计事件，不复制或打印 secret 值。
4. 如果 known-good 版本会恢复 `rejectUnauthorized:false`，必须先取得限时安全例外：登记批准人、到期时间、整改工单，并限制流量与可用功能。缺少任一记录不得恢复该兼容路径。

回滚验证必须按实际模式拆分，不能把限时例外写成“全部通过”：

- **严格 TLS 版本**：以正确 CA 执行只读 `select 1` 并调用关键只读 jobs API；错误 CA 连接必须失败。确认 API 错误率、TLS/连接错误、连接占用和 p95 延迟恢复后，才可关闭回滚事件。
- **限时 `rejectUnauthorized:false` 安全例外**：由于客户端不校验证书，该模式明确无法通过“错误 CA 必须失败”的负向测试，不得把该项标为通过，也不得关闭事件或整改。必须限制到恢复服务所需的最小流量和最小功能；在例外到期前重新部署严格 TLS 版本，再完成正确 CA、错误 CA、关键只读 API 与监控恢复的全部验证，之后才可关闭事件。

```text
回滚触发证据：未验证 / ______
回滚模式（严格 TLS / 限时安全例外）：未验证 / ______
执行方式（Dashboard/CLI）：未验证 / ______
恢复 deployment ID：未验证 / ______
恢复 secret version reference：未验证 / ______
安全例外批准人（如适用）：未验证 / ______
安全例外到期时间（如适用）：未验证 / ______
流量限制（如适用）：未验证 / ______
正确 CA select 1：未验证 / ______
关键只读 API：未验证 / ______
错误 CA 必须失败（严格 TLS 必填）：未验证 / ______
例外期间流量/功能限制（如适用）：未验证 / ______
严格 TLS 重新部署截止时间（如适用）：未验证 / ______
事件/整改关闭状态：保持未关闭 / ______
监控恢复证据：未验证 / ______
```

回滚时禁止在日志中打印 secret，也禁止把 `rejectUnauthorized:false` 当作长期修复。若可信 CA 路径失败且无法安全恢复，应停止发布并恢复上一稳定版本。

## 8. 发布验收汇总

```text
TLS 可信 CA 与身份校验：代码/secret/Actions/Preview 已确认；生产 API 待部署后回归，证据见本节登记
每日加密快照与保留期：未验证；本次限时例外，证据 #3 comment 4944776071
PITR / RPO / RTO 签字：未验证；本次限时例外，证据同上
季度恢复演练：未验证；本次限时例外，证据同上
容量与告警试触发：未验证；本次限时例外，证据同上
发布决定：本次应用发布限时放行；基础设施验收未通过；例外 2026-07-18 到期且不可复用
发布负责人签字及日期：Allen201117 authenticated GitHub approval，2026-07-11
```
