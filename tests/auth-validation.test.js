const test = require("node:test");
const assert = require("node:assert/strict");
const {
  validateEmail,
  validatePassword,
  validateOtp,
  mapAuthError,
} = require("../lib/auth-validation");

// 登录/注册/验证码流程的纯函数：输入校验 + Supabase 报错→中文映射。
// 被测对象 lib/auth-validation.js 被 app/login/page.tsx 复用，逻辑改动须同步本测试。

test("validateEmail：合法邮箱返回 null", () => {
  assert.equal(validateEmail("you@example.com"), null);
  assert.equal(validateEmail("  a.b@sub.domain.co  "), null); // 前后空白先 trim
});

test("validateEmail：非法邮箱返回中文提示", () => {
  for (const bad of ["", "  ", "noat", "a@b", "a@b.", "@b.com", "a b@c.com"]) {
    assert.equal(validateEmail(bad), "请输入有效的邮箱地址", `应判非法: ${JSON.stringify(bad)}`);
  }
  assert.equal(validateEmail(null), "请输入有效的邮箱地址");
  assert.equal(validateEmail(undefined), "请输入有效的邮箱地址");
});

test("validatePassword：≥6 位通过，<6 位拦截", () => {
  assert.equal(validatePassword("123456"), null);
  assert.equal(validatePassword("a much longer passphrase"), null);
  assert.equal(validatePassword("12345"), "密码至少需要 6 位");
  assert.equal(validatePassword(""), "密码至少需要 6 位");
  assert.equal(validatePassword(null), "密码至少需要 6 位");
});

test("validateOtp：恰好 6 位数字通过，其余拦截", () => {
  assert.equal(validateOtp("123456"), null);
  assert.equal(validateOtp("  123456  "), null); // trim 后判断
  for (const bad of ["", "12345", "1234567", "12a456", "abcdef", "12 456"]) {
    assert.equal(validateOtp(bad), "请输入 6 位数字验证码", `应判非法: ${JSON.stringify(bad)}`);
  }
  assert.equal(validateOtp(null), "请输入 6 位数字验证码");
});

test("mapAuthError：覆盖各关键分支", () => {
  const cases = [
    ["Invalid login credentials", "邮箱或密码不正确"],
    ["Email not confirmed", "邮箱尚未验证，请先完成邮箱验证"],
    ["User already registered", "该邮箱已注册，请直接登录"],
    ["Email address already been registered", "该邮箱已注册，请直接登录"],
    ["Signups not allowed for this instance", "注册暂未开放，请联系管理员开通"],
    ["New password should be different from the old password.", "新密码不能与旧密码相同"],
    ["Password should be at least 6 characters", "密码至少需要 6 位"],
    ["Token has expired or is invalid", "验证码错误或已过期，请重新获取"],
    ["otp_expired", "验证码错误或已过期，请重新获取"],
    ["Invalid token", "验证码错误或已过期，请重新获取"],
    ["Token is invalid", "验证码错误或已过期，请重新获取"],
    ["Unable to validate email address: invalid format", "邮箱格式不正确"],
    // GoTrue v2 新版非法邮箱文案（无 code 时靠 message 兜底）
    ['Email address "x@y.z" is invalid', "邮箱格式不正确"],
    ["Email rate limit exceeded", "操作过于频繁，请稍后再试"],
    ["Rate limit exceeded", "操作过于频繁，请稍后再试"],
    ["For security purposes, you can only request this after 60 seconds", "操作过于频繁，请稍后再试"],
    ["Failed to fetch", "网络异常，请检查网络后重试"],
    ["NetworkError when attempting to fetch resource", "网络异常，请检查网络后重试"],
  ];
  for (const [raw, expected] of cases) {
    assert.equal(mapAuthError({ message: raw }), expected, `输入: ${raw}`);
  }
});

test("mapAuthError：error.code 优先命中（不随文案/语言漂移）", () => {
  // message 故意给个不可映射的串，验证 code 分支先生效
  const codeCases = [
    ["invalid_credentials", "邮箱或密码不正确"],
    ["email_not_confirmed", "邮箱尚未验证，请先完成邮箱验证"],
    ["user_already_exists", "该邮箱已注册，请直接登录"],
    ["email_exists", "该邮箱已注册，请直接登录"],
    ["signup_disabled", "注册暂未开放，请联系管理员开通"],
    ["same_password", "新密码不能与旧密码相同"],
    ["weak_password", "密码至少需要 6 位"],
    ["otp_expired", "验证码错误或已过期，请重新获取"],
    ["email_address_invalid", "邮箱格式不正确"],
    ["over_email_send_rate_limit", "操作过于频繁，请稍后再试"],
    ["over_request_rate_limit", "操作过于频繁，请稍后再试"],
  ];
  for (const [code, expected] of codeCases) {
    assert.equal(
      mapAuthError({ code, message: "完全无法从文案映射的串" }),
      expected,
      `code: ${code}`,
    );
  }
});

test("mapAuthError：未知/空报错回落到通用提示", () => {
  assert.equal(mapAuthError({ message: "some unmapped server error" }), "操作失败，请稍后重试");
  assert.equal(mapAuthError({}), "操作失败，请稍后重试");
  assert.equal(mapAuthError(null), "操作失败，请稍后重试");
  assert.equal(mapAuthError(undefined), "操作失败，请稍后重试");
});

// 「密码至少 6 位」在 password-too-short 与 mapAuthError 两处都出现，
// 确认顺序：mapAuthError 命中 "already registered" 时不会被其他分支抢先。
test("mapAuthError：分支顺序不串", () => {
  // 该串同时含 "registered"，不含其他更靠前关键词 → 命中已注册
  assert.equal(mapAuthError({ message: "User already registered" }), "该邮箱已注册，请直接登录");
});
