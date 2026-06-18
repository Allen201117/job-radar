# 邮箱验证码注册 + 忘记密码 设计 / 落地清单

> 2026-06-19。在现有「邮箱+密码」登录之上，新增 **6 位验证码注册激活** 与 **验证码重置密码** 两条流程。
> 决策（已与用户确认）：验证方式 = **6 位验证码（OTP）**；邮件渠道 = **Resend 免费 SMTP**。

## 目标与非目标

**做：**
- 注册 → 邮箱收 6 位码 → 网页输码激活 → 登录。
- 忘记密码 → 邮箱收 6 位码 → 输码 → 设新密码 → 登录。
- 全流程在 `/login` 一页内的状态机走完，**不点邮件链接、不需要单独落地页**。

**不做（YAGNI）：** 第三方 OAuth、magic link、手机短信、图形验证码、6 格炫酷输入框、改邮箱、注销账号。

## 流程

```
注册激活：
  signup(email,password) → Supabase 发 6 位码（Confirm signup 模板用 {{ .Token }}）
    → verifyOtp({email, token, type:'signup'}) → 建立 session → /today

忘记密码：
  resetPasswordForEmail(email) → 发 6 位码（Reset Password 模板用 {{ .Token }}）
    → verifyOtp({email, token, type:'recovery'}) → recovery session
    → updateUser({password}) → /today
```

## 代码改动（仅前端 + 一个纯函数模块）

| 文件 | 改动 |
|---|---|
| `lib/auth-validation.js`（新建，CJS 纯函数） | `validateEmail` / `validatePassword` / `validateOtp` / `mapAuthError`（补验证码过期、token 无效、限流、新旧密码相同等映射）。仿 `lib/canonical-url.js` 约定，`module.exports`。 |
| `tests/auth-validation.test.js`（新建） | `node --test`，覆盖校验正常/边界 + 报错映射全分支。 |
| `app/login/page.tsx` | 右侧表单卡改 `mode` 状态机：`signin` / `signup` / `verify-signup` / `forgot-email` / `forgot-code` / `forgot-password`。左侧品牌栏不动；复用现有 `.field-editorial` / `.btn-ink` / `.btn-ghost` 样式。重发按钮 60s 冷却。 |

**不新建路由**：`/auth/callback` 保留（以后接 OAuth 仍用）。`middleware.ts` 已对 `/login` 放行，无需改。

### 关键边界
- **登录不变**：`signInWithPassword` 纯 API。若登录报 `email not confirmed` → 自动切到 `verify-signup` 并补发码。
- **已注册邮箱（Confirm email 开启时）**：`signUp` 对已存在邮箱返回 `data.user.identities.length === 0` 且无报错、不发信 → 代码检测此情况，提示「该邮箱已注册，请直接登录」并切回 `signin`，避免用户死等收不到的码。
- **不暴露邮箱是否存在**：`resetPasswordForEmail` 对不存在的邮箱也返回成功 → 一律进入输码步骤（防枚举）。
- **重发冷却**：客户端 60s 倒计时，避免撞 Supabase 发信限流。
- **兼容**：打开 Confirm email 只影响**新注册**；老用户 + 测试号 `test@jobradar.local` 已是验证态，登录照常。

## 你要在后台做的事（外部/私有，代码改不了，照下面点）

### 1. Resend（发信渠道）
1. 注册 https://resend.com （免费 3000 封/月、100/天）。
2. Domains → Add Domain → 填 `myjobradar.top`。
3. Resend 给出几条 DNS 记录（一条 MX、若干 TXT：SPF + DKIM）→ 到 **DNSPod**（`console.cloud.tencent.com/cns/detail/myjobradar.top/records`）逐条「添加记录」，主机记录/类型/值照抄。
4. 回 Resend 点 Verify，全绿后到 API Keys 建一个 Key（`re_...`，只显示一次，复制好）。

### 2. Supabase → Authentication → Providers → Email
- 打开 **Confirm email** 开关。

### 3. Supabase → Authentication → Emails → Templates
把两个模板正文换成验证码版（保留 `{{ .Token }}` 占位符，Supabase 会替换成 6 位码）：

**Confirm signup：**
```html
<h2>欢迎使用求职雷达</h2>
<p>你的注册验证码是：</p>
<p style="font-size:28px;font-weight:bold;letter-spacing:4px">{{ .Token }}</p>
<p>验证码 1 小时内有效。如非本人操作请忽略本邮件。</p>
```

**Reset Password：**
```html
<h2>重置求职雷达密码</h2>
<p>你的重置验证码是：</p>
<p style="font-size:28px;font-weight:bold;letter-spacing:4px">{{ .Token }}</p>
<p>验证码 1 小时内有效。如非本人操作请忽略本邮件。</p>
```

### 4. Supabase → Project Settings → Authentication → SMTP Settings
打开 Custom SMTP，填：
- Host：`smtp.resend.com`
- Port：`465`（或 587）
- Username：`resend`
- Password：上面的 Resend API Key（`re_...`）
- Sender email：`noreply@myjobradar.top`（须是已验证域名下的地址）
- Sender name：`求职雷达`

### 5. OTP 有效期 + 限流（建议必做）
- Authentication → Email OTP Expiration：从默认 3600s（1 小时）**缩短到 600s**，收窄 6 位码（10^6 空间）的暴力窗口。
- Authentication → Rate Limits：确认 email 发送频率与 OTP 校验失败次数上限**未被调高**（GoTrue 默认每邮箱发信间隔 + per-token 校验失败上限即是本功能的真正安全边界）。

## 安全说明（评审结论，2026-06-19 adversarial review）

- **前端 60s 冷却只是体验优化，不是安全措施**：它是纯客户端倒计时，直连 GoTrue REST 即可绕过。防刷码 / 防 OTP 暴力 / 防复用**全部依赖 Supabase 服务端限流**（见上 §5）。代码注释与文案已去掉「冷却=防限流」这类暗示。
- **邮箱枚举：内测期不追求严格防枚举**。`resetPasswordForEmail` 路径已防枚举，但 `signUp`（GoTrue 对已注册邮箱返回 `identities=[]`）与登录的「邮箱未验证」分支天然会暴露邮箱是否存在——这是 GoTrue 行为，纯前端无法根除（攻击者读原始网络响应即可）。3–5 人内测可接受；面向公网前若要硬化，需弱化「该邮箱已注册」等确定性文案并去掉登录自动跳转。
- **登录触发的自动补发码已加冷却守卫**：`handleSignIn` 命中「邮箱未验证」时，仅在冷却结束才自动 resend，且接住其 error，避免被「反复登录」当成绕过冷却的刷信入口。

## 测试与验证
- `node --test tests/auth-validation.test.js`（纯函数全绿）。
- `npm run build`（类型 + 构建通过）。
- 后台配好后，真机注册一个新邮箱走完整链路 + 忘记密码链路（live，需用户本机，墙外环境）。

## 回滚
- 关掉 Supabase 的 Confirm email 开关 → 立即回到「注册即登录」旧行为，前端代码已兼容 `data.session` 存在的情况，无需回退代码。
