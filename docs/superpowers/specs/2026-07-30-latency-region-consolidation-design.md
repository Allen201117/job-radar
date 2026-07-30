# 页面加载慢的根治：算力与数据同地收拢（第一阶段 ①+②）

- 日期：2026-07-30
- 状态：设计已批准，实施中
- 分支：`draft/latency-hkg1-0730`
- 背景诉求：创始人反馈「页面加载太卡、响应很慢」，初始假设是「Supabase 在海外」，提出「海外岗位切海外服务器、国内岗位走国内」的分流方案。

## 1. 诊断结论：不是「数据在海外」，是「算力放错地方」

### 1.1 实测数据（2026-07-30）

```
x-vercel-id: iad1::iad1              → 页面函数跑在【美东 华盛顿】
首页 TTFB:  1.7s / 2.4s / 4.2s       → x-vercel-cache 每次 MISS（全动态无缓存）
/api/jobs/stats TTFB: 6.6s           → 另有 2 次直接超时（code=000）
```

### 1.2 三地分居

| 组件 | 位置 | 来源 |
|---|---|---|
| 页面 / API 函数 | **美东 iad1** | 无 `vercel.json`，Vercel 新项目默认值 |
| Supabase（Auth + 小表） | **悉尼** `aws-1-ap-southeast-2` | `SUPABASE_DB_URL` host |
| jobs 热表（自建 PG） | **香港** | `JOBS_DATABASE_URL` host |

一次 `/jobs` 渲染的串行链：

```
[0] middleware.ts:30      getUser()        边缘节点 → 悉尼
[1] app/jobs/page.tsx:69  Promise.all × 3  美东 → 悉尼
[2] app/jobs/page.tsx:42  Promise.all × 3  美东 → 香港
    ↑ [1] 的结果是 [2] 的入参（page.tsx:79/82），强串行、无法并行
    ↑ 该页无 Suspense，全部完成才吐首字节
[3] 页面挂载后 8 个客户端 API，每个内部各自再 getUser() 一次（lib/apiAuth.ts:24）
```

### 1.3 单点最大元凶：数据库「拨号」比「说话」贵

`lib/jobs-store/client.ts:36` 设 `idleTimeoutMillis: 10_000`，闲置 10 秒断连；内测期流量低 ⇒ 几乎每请求都要重新握手。而 `client.ts:33` 用完整证书校验的 TLS，美东↔香港完整握手（TCP + TLS + PG 认证）需 4~6 个往返：

> **约 800~1200ms 只用于建立连接，一个字都还没查。**

这解释了 `/api/jobs/stats` 的 6.6 秒与两次超时。

### 1.4 为什么否决「国内外岗位分流」

1. jobs 库已在香港，距国内用户 ~48ms（实测），拆它无收益；
2. 看板里国内岗与海外岗混合参与筛选/计数/排序/去重，拆库会退化成跨洋拼接，一次查询变两次；
3. 真正的固定开销（美东算力、悉尼鉴权、冷连接握手）一个都不解决。

**方向修正：不按岗位地域分流，而是把算力搬到数据旁边，并消除每请求的跨洋鉴权。**

## 2. 本阶段范围

本阶段只做 ①②（+ 顺带清理）。第 ③ 步（Supabase 悉尼→新加坡迁移）**明确不做**，等 ①② 上线实测后再评估——它成本最高、风险最大（需新建项目 + 整库迁移 + 全部 key 轮换），而收益在 ② 落地后会显著缩小。

「国内可直连、免翻墙」属于**可达性**问题（需 ICP 备案 + 国内云），与本阶段的**速度**问题正交，单独立项。

## 3. 改动 1：函数区域迁至香港

新增 `vercel.json`：

```json
{ "regions": ["hkg1"] }
```

依据（Vercel 官方文档）：
- Hobby 计划**可以**选择函数区域，仅限单区域；`iad1` 只是新项目默认值。
- `hkg1`（AWS ap-east-1, Hong Kong）当前可选。
- ⚠️ **Routing Middleware 不跟随该设置**，官方明确说明其默认部署到所有区域。这正是改动 2 必须存在的理由：middleware 里那次跨洋鉴权无法靠迁移机房解决，只能靠不联网解决。

附带收益：`/api/enrich` 抓取国内企业官网 JD 正文时，出口从美东变香港。

回滚：删除 `vercel.json` 重新部署。

## 4. 改动 2：鉴权改本地验签（JWT）

### 4.1 可行性（读真实源码核实，非查文档）

- **会话刷新不受影响**：`getClaims()` 内部第一步是 `getSession()`（`GoTrueClient.js`），token 临期时照常用 refresh token 刷新并触发 `setAll` 写回 cookie。现有 `middleware.ts:7/51-54` 的 cookie 回写机制完全兼容，**不会造成用户被登出**。
- **claims 足够覆盖**：全仓库对 user 字段的使用为 `user.id` × 124、`user.email` × 2、`user.identities` × 1（后者是 `components/RegisterModal.tsx:158` 的注释，服务端零使用）。JWT 的 `sub` / `email` 完全覆盖。
- **自动回落**：项目若用对称密钥（HS256），`getClaims()` 会自动回落 `getUser(token)`——代码不会变坏，只是不变快。
- **✅ live 实测：本项目已经在用非对称密钥，无需任何控制台操作**（2026-07-30 实测）：
  - JWKS 端点 `…/auth/v1/.well-known/jwks.json` 返回 1 把 `kty=EC / alg=ES256`；
  - 用测试账号换取的真实 access token，头部 `alg=ES256`、`kid` 与 JWKS 中那把一致，claims 含 `sub` / `email`。
  - 即上线即生效，原计划的「控制台 Migrate JWT secret → Rotate」这一步**不需要做**。

### 4.2 必须避开的坑：JWKS 缓存

`fetchJwk` 把 JWKS 缓存在 **GoTrueClient 实例**上（`this.jwks` / `this.jwks_cached_at`）。而 serverless 每请求都 `createServerClient()` 新建实例 ⇒ 实例缓存永远为空 ⇒ 每请求改为去拉一次 JWKS，**等于用「取公钥」换掉「验 token」，一次往返都没省**。

对策：新建 `lib/auth-claims.ts`，把 JWKS 缓存提到**模块级**（同一 lambda 实例内跨请求共享），并通过 `getClaims(undefined, { jwks })` 显式喂入。命中即纯本地 WebCrypto 验签、零网络。

- TTL 取 **10 分钟**，对齐 Supabase 官方 Edge 缓存时长；官方要求调用方不得缓存更久，否则密钥轮换/吊销后会误拒仍然有效的 token。
- 密钥轮换后新 `kid` 不在本地缓存中时，auth-js 会自行回落去拉一次，作为安全网。
- 并发去重：同一实例内多请求同时未命中时只发一次网络请求（`inflight` 复用）。
- 类型不硬 import 传递依赖 `@supabase/auth-js`，改为从 SDK 方法签名推导（`Parameters<...>`），SDK 变更时由 build 报警。

### 4.3 落点

| 文件 | 改动 |
|---|---|
| `lib/auth-claims.ts`（新增） | 模块级 JWKS 缓存 + `verifyRequestClaims(supabase)` |
| `middleware.ts:30` | `getUser()` → 本地验签；注入头改用 `claims.sub` / `claims.email` |
| `lib/apiAuth.ts:24` | 同上。23 个 API 路由共用此函数，改一处全受益 |

`ApiAuthResult.user` 类型由 `User` 收窄为 `{ id, email }`（见 4.1 的字段审计）。

### 4.4 安全取舍

本地验签只证明「签名有效且未过期」，拿不到用户最新状态——封禁 / 改邮箱等要等 access token 过期（默认 1 小时）才生效。对本产品可接受。需要权威最新用户记录的场景仍应显式用 `getUser()`。

## 5. 改动 3：清理与地理无关的浪费

### 5.1 Navbar 浏览器直连悉尼（做）

`components/Navbar.tsx:66` 在浏览器里直接 `supabase.auth.getUser()` 打悉尼，且 `email` 决定大量 UI 显隐。改造：

- `components/Navbar.tsx` → **服务端组件**，用 `getRequestUser()`（零网络，读 middleware 注入的头）取 email，渲染 `<NavbarClient initialEmail={...} />`
- `components/NavbarClient.tsx`（新增）→ 现有客户端组件，去掉 `getUser()` effect，改收 `initialEmail` prop

20 个引用点**全部无需改动**（都是服务端组件，且组件名不变）。

### 5.2 /jobs 挂载重复搜索（**不做**，原判断有误）

原以为 `hooks/useJobFilters.ts:148` 挂载时那次 `/api/jobs/search` 是「把 SSR 已查的同一份数据再查一遍」。核实后**不成立**：

- SSR `listLatestActive` 排序是 `order by first_seen_at desc`（最新优先，`lib/jobs-store/read.ts:313`）；
- 客户端搜索默认 `sortBy: "match"`（`lib/job-filter.ts:56`，按匹配度）；
- 分桶计数（`精确 N / 同职能相关 N / 信息不全 N`，`app/jobs/jobs-client.tsx:196-198`）**只有搜索接口会返回**。

即两者是**不同的查询**：SSR 是「先给点东西看」的即时占位，客户端搜索才是真答案。跳过它会造成排序与 UI 声明不一致、并让分桶计数消失——那是功能回归，不是优化。要根治得让 SSR 直接执行与搜索同口径的查询，属于筛选器契约改动，本阶段不碰。

### 5.3 改为消除挂载时的空等（做）

`useJobFilters.ts:148-153` 的 effect 统一 `setTimeout(300)` 防抖。挂载那一次并没有用户输入需要防抖，300ms 纯属空等。改为**挂载即刻发起、后续变更仍防抖 300ms**。不改变任何查询结果。

## 6. 预期效果（`/jobs` 纯网络等待）

| 环节 | 现在（美东） | 改动1后 | 改动1+2后 |
|---|---|---|---|
| middleware 鉴权 | ~130–200ms | ~130–200ms | **~1ms** |
| 悉尼查偏好/收藏/简历 | ~200ms | ~130ms | ~130ms |
| 香港查岗位（含建连） | **800–1400ms** | **~25ms** | ~25ms |
| **服务端合计** | **1.3–1.8s** | **~0.3s** | **~0.16s** |
| 之后 23 个 API 各自鉴权 | 各 ~200ms | 各 ~130ms | **各 ~1ms** |
| /jobs 挂载空等 | 300ms | 300ms | **0** |

诚实标注：`iad1` 与 `/api/jobs/stats` 6.6s 为**实测**；悉尼/香港间 RTT 为**公开值估算**，上线后必须实测复核。

### 6.1 本地验签收益（live 实测，非估算）

用真实 access token + 真实 JWKS，同一进程内对比（本机经代理连悉尼）：

```
getClaims + 已缓存 JWKS（本方案）    0.7 ms/次   （20 次平均）
getUser（改造前每请求都走）        566.7 ms/次   （5 次平均）
→ 快 858 倍，每次鉴权省 566ms
```

线上 Vercel 边缘 → 悉尼的绝对值会低于本机代理链路，但量级一致。

## 7. 上线顺序

原计划「代码先上 → 跑稳一天 → 控制台 Rotate 密钥」中的第三步经实测**已无必要**（见 4.1：项目本就是 ES256）。修订为：

1. 代码（改动 1+2+3）合并上线 —— 改动 1 与改动 2 的收益**同时立即生效**。
2. 部署后实测复核：`x-vercel-id` 是否变为 `hkg1`、页面 TTFB、`/api/jobs/stats` TTFB。
3. 跑稳一天后，再评估第 ③ 步（Supabase 迁新加坡）是否还值得做——鉴权往返已消除，剩余 Supabase 查询只在页面 SSR 阶段（`/today` 6 次、`/jobs` 3 次、`/saved` 2 次），③ 的边际收益已明显缩小。

## 8. 验证

- `node --test tests/*.test.js`
- `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`
- `npm run build` **且** `npm run lint`（项目 CLAUDE.md：本地 build 跳过 lint，Vercel 会跑且 Error 级规则直接挂部署，已有连挂 7 次的先例）
- 部署后实测：`curl -w` 复核 `x-vercel-id` 是否变为 `hkg1`、TTFB 变化
- 登录态回归：登录 / 刷新 / 换页 / 登出 / token 临期刷新

## 9. 风险

| 风险 | 处置 |
|---|---|
| 改动 1 副作用 | 未发现。用户、jobs 库、被抓国内官网均更近香港；爬虫在 GitHub Actions 不受影响。删 `vercel.json` 即回滚 |
| 非对称密钥切换导致登出 | 已排除（4.1）。且 Supabase 为「新密钥待命 → 轮换 → 旧密钥仍可验签」，旧 token 继续有效 |
| JWKS 缓存过久致误拒 | TTL 10 分钟对齐官方；新 kid 未命中时 auth-js 自行回落拉取 |
| 封禁/改邮箱不即时生效 | 最长一个 token 周期（默认 1h），本产品可接受 |
| 类型收窄漏改 | build + lint 双跑 |
