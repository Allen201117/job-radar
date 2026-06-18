/**
 * 登录 / 注册 / 验证码流程的纯函数：输入校验 + Supabase(GoTrue) 原始英文报错 → 面向用户的中文提示。
 *
 * 抽成独立 CommonJS 模块（不是写死在 app/login/page.tsx 里）的原因：
 *   - 这层是纯逻辑，无副作用，最适合 node --test 单测（仿 lib/canonical-url.js 约定）。
 *   - 登录页的多个 mode（signin/signup/verify/forgot）共用同一套校验与报错映射，避免重复。
 *
 * 约定：每个 validate* 校验通过返回 null，失败返回中文错误串（可直接展示给用户）。
 */

// 与 app/login/page.tsx 旧有正则保持一致：够用的「有 @、有点、各段非空」邮箱形状校验。
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validateEmail(email) {
  if (!EMAIL_RE.test(String(email || "").trim())) return "请输入有效的邮箱地址";
  return null;
}

function validatePassword(password) {
  // Supabase 默认最小 6 位；本地先拦一道，避免把明显无效输入打到后端再拿英文报错。
  if (String(password || "").length < 6) return "密码至少需要 6 位";
  return null;
}

function validateOtp(code) {
  // Supabase 邮箱 OTP 固定 6 位数字。
  if (!/^\d{6}$/.test(String(code || "").trim())) return "请输入 6 位数字验证码";
  return null;
}

// 把 Supabase/GoTrue 的原始英文报错映射成中文，绝不直接抛原始串给用户。
// 优先按 GoTrue 稳定的 error.code 命中（不随 SDK 版本 / 错误语言漂移）；message 子串作兜底，
// 兼容旧版本或 code 缺失的情况。
function mapAuthError(error) {
  const code = error && error.code ? String(error.code).toLowerCase() : "";
  const raw = (error && error.message ? String(error.message) : "").toLowerCase();

  switch (code) {
    case "invalid_credentials":
      return "邮箱或密码不正确";
    case "email_not_confirmed":
      return "邮箱尚未验证，请先完成邮箱验证";
    case "user_already_exists":
    case "email_exists":
      return "该邮箱已注册，请直接登录";
    case "signup_disabled":
    case "signups_not_allowed":
      return "注册暂未开放，请联系管理员开通";
    case "same_password":
      return "新密码不能与旧密码相同";
    case "weak_password":
      return "密码至少需要 6 位";
    case "otp_expired":
      return "验证码错误或已过期，请重新获取";
    case "email_address_invalid":
      return "邮箱格式不正确";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "操作过于频繁，请稍后再试";
    default:
      break;
  }

  if (raw.includes("invalid login credentials")) return "邮箱或密码不正确";
  if (raw.includes("email not confirmed")) return "邮箱尚未验证，请先完成邮箱验证";
  if (raw.includes("already registered") || raw.includes("already been registered"))
    return "该邮箱已注册，请直接登录";
  if (raw.includes("signups not allowed")) return "注册暂未开放，请联系管理员开通";
  if (raw.includes("new password should be different"))
    return "新密码不能与旧密码相同";
  if (raw.includes("password should be at least")) return "密码至少需要 6 位";
  // verifyOtp 验证码错误 / 过期：GoTrue 文案多为 "Token has expired or is invalid" / otp_expired。
  if (
    raw.includes("token has expired") ||
    raw.includes("otp_expired") ||
    raw.includes("expired or is invalid") ||
    raw.includes("invalid token") ||
    raw.includes("token is invalid")
  )
    return "验证码错误或已过期，请重新获取";
  // 邮箱非法：旧版 "Unable to validate email address: invalid format" /
  // 新版 GoTrue v2 'Email address "x" is invalid'（code=email_address_invalid，已在上面优先命中）。
  if (
    raw.includes("unable to validate email") ||
    raw.includes("invalid format") ||
    (raw.includes("email address") && raw.includes("is invalid"))
  )
    return "邮箱格式不正确";
  // 限流：发信过频 / GoTrue 安全冷却。
  if (
    raw.includes("rate limit") ||
    raw.includes("email rate limit") ||
    raw.includes("for security purposes")
  )
    return "操作过于频繁，请稍后再试";
  if (raw.includes("failed to fetch") || raw.includes("network"))
    return "网络异常，请检查网络后重试";
  return "操作失败，请稍后重试";
}

module.exports = {
  EMAIL_RE,
  validateEmail,
  validatePassword,
  validateOtp,
  mapAuthError,
};
