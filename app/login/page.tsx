"use client";

import { useEffect, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Broadcast, CheckCircle, MapPin } from "@phosphor-icons/react";
import {
  mapAuthError,
  validateEmail,
  validateOtp,
  validatePassword,
} from "@/lib/auth-validation";

// 登录页是一个状态机：邮箱+密码登录之外，新增「验证码注册激活」与「验证码重置密码」两条流程，
// 全部在本页内走完（不点邮件链接、不跳单独落地页）。校验与报错映射复用 lib/auth-validation.js。
type Mode =
  | "signin" // 邮箱+密码登录（默认）
  | "signup" // 邮箱+密码注册 → 触发发码
  | "verify-signup" // 输入注册验证码激活
  | "forgot-email" // 输入邮箱，请求重置验证码
  | "forgot-code" // 输入重置验证码
  | "forgot-password"; // 设置新密码

const COPY: Record<Mode, { title: string; subtitle: string }> = {
  signin: { title: "登录 / 注册", subtitle: "使用邮箱进入今日看板" },
  signup: { title: "注册账号", subtitle: "用邮箱注册，下一步收取验证码" },
  "verify-signup": { title: "输入验证码", subtitle: "查收邮箱里的 6 位验证码" },
  "forgot-email": { title: "找回密码", subtitle: "输入注册邮箱，我们发验证码给你" },
  "forgot-code": { title: "输入验证码", subtitle: "查收邮箱里的 6 位验证码" },
  "forgot-password": { title: "设置新密码", subtitle: "为账号设置一个新密码" },
};

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [cooldown, setCooldown] = useState(0); // 重发验证码冷却（秒）
  const router = useRouter();
  const supabase = createBrowserClient();

  // 重发冷却倒计时：避免狂点重发撞 Supabase 发信限流。
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((c) => (c <= 1 ? 0 : c - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  // UI 按钮导航切 mode 时清掉残留的提示 + 跨流程瞬态字段（验证码 / 新密码），避免串场：
  // code 被 verify-signup 与 forgot-code 共用，newPassword/confirmPassword 是敏感字段，
  // 不清会预填到下一条流程的输入框里。注意「重发」不走 goMode，不受影响。
  function goMode(next: Mode) {
    setMode(next);
    setError("");
    setMessage("");
    setCode("");
    setNewPassword("");
    setConfirmPassword("");
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validateEmail(email) || validatePassword(password);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (error) {
        // 邮箱未验证 → 转入验证码激活步骤。仅在冷却结束时自动补发一次码（受同一 60s 冷却约束，
        // 避免「登录失败反复重试」被用来绕过冷却刷信）；真正的发信频率上限靠 Supabase 服务端兜底。
        if ((error.message || "").toLowerCase().includes("email not confirmed")) {
          setCode("");
          if (cooldown > 0) {
            setMessage("邮箱尚未验证，请输入此前收到的验证码，或用下方「重新发送」。");
          } else {
            const { error: resendErr } = await supabase.auth.resend({
              type: "signup",
              email: email.trim(),
            });
            if (resendErr) {
              console.error("[auth] signin auto-resend", resendErr);
              setMessage("邮箱尚未验证。上次验证码可能仍有效，请查收邮箱或稍后用「重新发送」。");
            } else {
              setCooldown(60);
              setMessage("邮箱尚未验证，已重新发送验证码，请查收邮箱。");
            }
          }
          setMode("verify-signup");
          return;
        }
        setError(mapAuthError(error));
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (err) {
      console.error("[auth] signin", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignUp(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validateEmail(email) || validatePassword(password);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      const { data, error } = await supabase.auth.signUp({
        email: email.trim(),
        password,
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      // Confirm email 开启时，对「已注册邮箱」GoTrue 返回混淆用户（identities 为空）且不发码 →
      // 主动识别，提示去登录，避免用户死等一封永远不会到的验证码。
      if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        setError("该邮箱已注册，请直接登录");
        setMode("signin");
        return;
      }
      if (data.session) {
        // Confirm email 关闭：注册即登录（向后兼容旧行为）。
        router.push("/today");
        router.refresh();
        return;
      }
      // Confirm email 开启：signUp 已自动发码 → 进输码步骤。
      setCooldown(60);
      setMessage("验证码已发送到你的邮箱，请查收（也看看垃圾箱）。");
      setMode("verify-signup");
    } catch (err) {
      console.error("[auth] signup", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifySignup(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validateOtp(code);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      // type:'email' 是 SDK 当前推荐、且对 signUp 未确认邮箱 OTP 与 'signup' 等价的校验类型
      //（'signup' 已被 auth-js 标 deprecated）。重发仍用 resend({type:'signup'})，职责不同。
      const { error } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: code.trim(),
        type: "email",
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (err) {
      console.error("[auth] verify-signup", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleForgotEmail(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validateEmail(email);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      // 防枚举：对不存在的邮箱 resetPasswordForEmail 也返回成功 → 一律进入输码步骤。
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim());
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      setCooldown(60);
      setMessage("如果该邮箱已注册，验证码已发送，请查收。");
      setMode("forgot-code");
    } catch (err) {
      console.error("[auth] forgot-email", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleForgotCode(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validateOtp(code);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      const { error } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: code.trim(),
        type: "recovery",
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      // verifyOtp(recovery) 成功即建立 recovery session，可直接改密码。
      setMode("forgot-password");
    } catch (err) {
      console.error("[auth] forgot-code", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validatePassword(newPassword);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    setLoading(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      router.push("/today");
      router.refresh();
    } catch (err) {
      console.error("[auth] reset-password", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  // 重发验证码：注册流用 resend(signup)，重置流用 resetPasswordForEmail。
  async function handleResend() {
    if (cooldown > 0 || loading) return;
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const { error } =
        mode === "verify-signup"
          ? await supabase.auth.resend({ type: "signup", email: email.trim() })
          : await supabase.auth.resetPasswordForEmail(email.trim());
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      setCooldown(60);
      setMessage("验证码已重新发送。");
    } catch (err) {
      console.error("[auth] resend", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  const copy = COPY[mode];
  const alerts = (
    <>
      {error && (
        <p className="rounded-2xl border border-[#e0b4ac] bg-[#f7e6e1] px-4 py-2.5 text-[13px] text-[#9c4a3c]">
          {error}
        </p>
      )}
      {message && (
        <p className="rounded-2xl border border-[#b9cfb0] bg-[#eef4e8] px-4 py-2.5 text-[13px] text-[#4a6b3c]">
          {message}
        </p>
      )}
    </>
  );

  // 验证码步骤共用的「发往哪个邮箱 + 重发」尾部。
  const codeFooter = (
    <p className="text-center text-[12px] text-[#9a9184]">
      验证码已发至 <span className="font-medium text-[#5f594e]">{email || "你的邮箱"}</span>
      {" · "}
      <button
        type="button"
        onClick={handleResend}
        disabled={cooldown > 0 || loading}
        className="font-medium text-[#1a1714] underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-[#b8b1a4] disabled:no-underline"
      >
        {cooldown > 0 ? `重新发送 (${cooldown}s)` : "重新发送"}
      </button>
    </p>
  );

  return (
    <main className="bg-editorial grain relative min-h-screen overflow-hidden text-[#1a1714]">
      <div className="relative z-10 mx-auto grid min-h-screen max-w-6xl items-center gap-12 px-5 py-10 lg:grid-cols-[1.05fr_0.95fr] lg:px-8">
        {/* ——— 左：品牌叙事 + 产品「拍立得」碎片 ——— */}
        <section className="rise relative hidden lg:block">
          <p className="text-[13px] font-medium tracking-[0.16em] text-[#8a8275]">
            求职雷达 · PRIVATE BETA
          </p>
          <h1 className="display-tight mt-5 text-balance text-[3.4rem] font-medium leading-[1.08] text-[#1a1714]">
            每天打开一次，
            <br />
            只看官方在招的
            <br />
            好岗位。
          </h1>
          <p className="mt-6 max-w-md text-pretty text-[15px] leading-7 text-[#5f594e]">
            聚合企业官方招聘源、过滤第三方水货岗位；再把公开的招聘节奏、薪酬与路径，聚合成分级、标时间的职业洞察。
          </p>

          {/* 漂浮的真实产品碎片：外层只做位移漂浮，内层卡片旋转 + 悬停回正 */}
          <div className="relative mt-12 h-[260px] max-w-lg">
            {/* 今日看板 */}
            <figure className="float-soft absolute left-0 top-2" style={{ animationDelay: "0s" }}>
              <div className="polaroid w-[208px] -rotate-[5deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
                <div className="rounded-[0.8rem] bg-[#f6f3ec] p-4">
                  <p className="text-[11px] font-medium text-[#8a8275]">今日官方岗位</p>
                  <p className="mt-1 text-3xl font-semibold tabular-nums text-[#1a1714]">24</p>
                  <p className="mt-1 text-[12px] text-[#8a8275]">11 个高匹配待处理</p>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/[0.06]">
                    <div className="h-full w-[46%] rounded-full bg-[#7fb2e8]" />
                  </div>
                </div>
              </div>
              <figcaption className="mt-2 pl-1 text-[12px] text-[#9a9184]">今日看板</figcaption>
            </figure>

            {/* 官方岗位卡（沿用真实示例数据） */}
            <figure
              className="float-soft absolute right-0 top-0"
              style={{ animationDelay: "1.4s" }}
            >
              <div className="polaroid w-[244px] rotate-[4deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
                <div className="rounded-[0.8rem] bg-white p-4">
                  <div className="flex items-center gap-1.5 text-[12px] text-[#8a8275]">
                    <span className="font-medium text-[#1a1714]">Apple</span>
                    <span>·</span>
                    <MapPin size={12} weight="fill" aria-hidden="true" />
                    <span>上海</span>
                  </div>
                  <p className="mt-1.5 text-[15px] font-semibold leading-snug text-[#1a1714]">
                    Machine Learning Engineer
                  </p>
                  <div className="mt-3 flex items-center justify-between">
                    <div className="flex gap-1.5">
                      <span className="rounded-full bg-[#eef0f5] px-2 py-0.5 text-[11px] font-medium text-[#4a4d57]">
                        外企
                      </span>
                      <span className="rounded-full bg-[#eef0f5] px-2 py-0.5 text-[11px] font-medium text-[#4a4d57]">
                        AI
                      </span>
                    </div>
                    <div className="rounded-xl bg-[#1a1714] px-2.5 py-1 text-center text-white">
                      <span className="text-[15px] font-semibold tabular-nums">82</span>
                    </div>
                  </div>
                </div>
              </div>
              <figcaption className="mt-2 pr-1 text-right text-[12px] text-[#9a9184]">
                官方岗位卡
              </figcaption>
            </figure>

            {/* 职业洞察四维 */}
            <figure
              className="float-soft absolute bottom-0 left-16"
              style={{ animationDelay: "0.7s" }}
            >
              <div className="polaroid w-[230px] rotate-[2.5deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
                <div className="rounded-[0.8rem] bg-white p-4">
                  <p className="text-[11px] font-medium text-[#8a8275]">职业洞察 · 分级标时间</p>
                  <ul className="mt-2.5 grid grid-cols-2 gap-2 text-[12px] text-[#3f3a33]">
                    <li className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-[#7fb2e8]" />时机
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-[#b6da7e]" />薪酬强度
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-[#e7b27e]" />路径
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-[#cfc6b6]" />文化
                    </li>
                  </ul>
                </div>
              </div>
              <figcaption className="mt-2 pl-1 text-[12px] text-[#9a9184]">职业洞察</figcaption>
            </figure>
          </div>
        </section>

        {/* ——— 右：登录表单卡 ——— */}
        <section className="rise mx-auto w-full max-w-[420px]" style={{ animationDelay: "0.12s" }}>
          {/* 移动端的极简品牌头（桌面端隐藏，避免与左栏重复） */}
          <div className="mb-7 lg:hidden">
            <p className="text-[12px] font-medium tracking-[0.16em] text-[#8a8275]">
              求职雷达 · PRIVATE BETA
            </p>
            <h1 className="display-tight mt-3 text-balance text-[2.3rem] font-medium leading-[1.12] text-[#1a1714]">
              只看官方在招的好岗位。
            </h1>
          </div>

          <div className="rounded-[1.6rem] border border-black/[0.06] bg-white/72 p-7 shadow-[0_30px_70px_-30px_rgba(40,34,28,0.4)] backdrop-blur-sm sm:p-8">
            <div className="flex items-center gap-2.5">
              <span className="grid size-9 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6]">
                <Broadcast size={19} weight="fill" aria-hidden="true" />
              </span>
              <span className="display-tight text-xl font-medium tracking-tight text-[#1a1714]">
                Job Radar
              </span>
            </div>
            <h2 className="mt-6 text-[1.45rem] font-semibold leading-tight text-[#1a1714]">
              {copy.title}
            </h2>
            <p className="mt-1.5 text-[14px] text-[#8a8275]">{copy.subtitle}</p>

            {/* —— 登录 —— */}
            {mode === "signin" && (
              <form className="mt-6 space-y-4" onSubmit={handleSignIn}>
                <div>
                  <label htmlFor="email" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    邮箱
                  </label>
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="field-editorial"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label htmlFor="password" className="block text-[13px] font-medium text-[#5f594e]">
                      密码
                    </label>
                    <button
                      type="button"
                      onClick={() => goMode("forgot-email")}
                      className="text-[12px] font-medium text-[#8a8275] hover:text-[#1a1714]"
                    >
                      忘记密码？
                    </button>
                  </div>
                  <input
                    id="password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="field-editorial"
                    placeholder="至少 6 位"
                  />
                </div>
                {alerts}
                <div className="flex gap-2.5 pt-1">
                  <button type="submit" disabled={loading} className="btn-ink flex-1">
                    {loading ? "登录中…" : "登录"}
                    <ArrowRight size={16} weight="bold" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => goMode("signup")}
                    className="btn-ghost"
                  >
                    注册
                  </button>
                </div>
              </form>
            )}

            {/* —— 注册 —— */}
            {mode === "signup" && (
              <form className="mt-6 space-y-4" onSubmit={handleSignUp}>
                <div>
                  <label htmlFor="signup-email" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    邮箱
                  </label>
                  <input
                    id="signup-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="field-editorial"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label htmlFor="signup-password" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    设置密码
                  </label>
                  <input
                    id="signup-password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="field-editorial"
                    placeholder="至少 6 位"
                  />
                </div>
                {alerts}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "发送中…" : "注册并获取验证码"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => goMode("signin")}
                  className="flex w-full items-center justify-center gap-1 text-[13px] text-[#8a8275] hover:text-[#1a1714]"
                >
                  <ArrowLeft size={14} weight="bold" aria-hidden="true" />
                  返回登录
                </button>
              </form>
            )}

            {/* —— 注册验证码 —— */}
            {mode === "verify-signup" && (
              <form className="mt-6 space-y-4" onSubmit={handleVerifySignup}>
                <div>
                  <label htmlFor="signup-code" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    6 位验证码
                  </label>
                  <input
                    id="signup-code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    className="field-editorial text-center text-lg tracking-[0.5em]"
                    placeholder="______"
                  />
                </div>
                {alerts}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "验证中…" : "验证并登录"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                {codeFooter}
                <button
                  type="button"
                  onClick={() => goMode("signin")}
                  className="flex w-full items-center justify-center gap-1 text-[13px] text-[#8a8275] hover:text-[#1a1714]"
                >
                  <ArrowLeft size={14} weight="bold" aria-hidden="true" />
                  返回登录
                </button>
              </form>
            )}

            {/* —— 忘记密码：输邮箱 —— */}
            {mode === "forgot-email" && (
              <form className="mt-6 space-y-4" onSubmit={handleForgotEmail}>
                <div>
                  <label htmlFor="forgot-email" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    注册邮箱
                  </label>
                  <input
                    id="forgot-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="field-editorial"
                    placeholder="you@example.com"
                  />
                </div>
                {alerts}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "发送中…" : "发送验证码"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => goMode("signin")}
                  className="flex w-full items-center justify-center gap-1 text-[13px] text-[#8a8275] hover:text-[#1a1714]"
                >
                  <ArrowLeft size={14} weight="bold" aria-hidden="true" />
                  返回登录
                </button>
              </form>
            )}

            {/* —— 忘记密码：输验证码 —— */}
            {mode === "forgot-code" && (
              <form className="mt-6 space-y-4" onSubmit={handleForgotCode}>
                <div>
                  <label htmlFor="forgot-code" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    6 位验证码
                  </label>
                  <input
                    id="forgot-code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    className="field-editorial text-center text-lg tracking-[0.5em]"
                    placeholder="______"
                  />
                </div>
                {alerts}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "验证中…" : "下一步"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                {codeFooter}
                <button
                  type="button"
                  onClick={() => goMode("signin")}
                  className="flex w-full items-center justify-center gap-1 text-[13px] text-[#8a8275] hover:text-[#1a1714]"
                >
                  <ArrowLeft size={14} weight="bold" aria-hidden="true" />
                  返回登录
                </button>
              </form>
            )}

            {/* —— 忘记密码：设新密码 —— */}
            {mode === "forgot-password" && (
              <form className="mt-6 space-y-4" onSubmit={handleResetPassword}>
                <div>
                  <label htmlFor="new-password" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    新密码
                  </label>
                  <input
                    id="new-password"
                    type="password"
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="field-editorial"
                    placeholder="至少 6 位"
                  />
                </div>
                <div>
                  <label htmlFor="confirm-password" className="mb-1.5 block text-[13px] font-medium text-[#5f594e]">
                    确认新密码
                  </label>
                  <input
                    id="confirm-password"
                    type="password"
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="field-editorial"
                    placeholder="再输一次"
                  />
                </div>
                {alerts}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "保存中…" : "设置新密码并登录"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => goMode("signin")}
                  className="flex w-full items-center justify-center gap-1 text-[13px] text-[#8a8275] hover:text-[#1a1714]"
                >
                  <ArrowLeft size={14} weight="bold" aria-hidden="true" />
                  返回登录
                </button>
              </form>
            )}
          </div>

          <p className="mt-5 flex items-center justify-center gap-1.5 text-center text-[12px] leading-5 text-[#9a9184]">
            <CheckCircle size={14} weight="fill" aria-hidden="true" />
            岗位仅来自企业官方公开渠道 · 职业洞察聚合去标识
          </p>
        </section>
      </div>
    </main>
  );
}
