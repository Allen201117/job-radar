"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { createBrowserClient } from "@/lib/supabaseClient";
import {
  mapAuthError,
  validateEmail,
  validateOtp,
  validatePassword,
} from "@/lib/auth-validation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  EnvelopeSimple,
  Eye,
  EyeSlash,
  Lock,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";

// 分步引导式注册弹窗：① 填邮箱 → ② 收 6 位验证码 → ③ 设密码 → ✓ 成功进站。
// 实现顺序「先验证邮箱、最后设密码」：signUp(临时随机密码) 触发发码（复用已配好的
// Confirm signup 模板）→ verifyOtp 激活并建立 session → updateUser 写入用户真正设置的密码。
// 这样无需再在 Supabase 配「Magic Link」模板，沿用现成的注册验证模板即可。
type Step = "email" | "code" | "password" | "success";

const STEPS: { key: Step; label: string }[] = [
  { key: "email", label: "邮箱" },
  { key: "code", label: "验证码" },
  { key: "password", label: "设密码" },
];

function stepIndex(step: Step): number {
  if (step === "success") return STEPS.length; // 全部完成
  return STEPS.findIndex((s) => s.key === step);
}

export default function RegisterModal({
  open,
  onClose,
  initialEmail = "",
  startAtCode = false,
}: {
  open: boolean;
  onClose: () => void;
  initialEmail?: string;
  startAtCode?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const router = useRouter();
  const supabase = createBrowserClient();

  useEffect(() => setMounted(true), []);

  // 打开时重置；锁定背景滚动。startAtCode（登录遇未验证账号时）直达验证码步骤、邮箱预填。
  useEffect(() => {
    if (!open) return;
    setStep(startAtCode ? "code" : "email");
    setEmail(initialEmail);
    setCode("");
    setPassword("");
    setShowPassword(false);
    setError("");
    setMessage(startAtCode ? "该邮箱尚未验证，请输入邮箱里的验证码，没收到就点「重新发送」。" : "");
    setCooldown(0);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open, startAtCode, initialEmail]);

  // ESC 关闭。
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, loading, onClose]);

  // 重发验证码冷却倒计时。
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((c) => (c <= 1 ? 0 : c - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  // ① 邮箱 → 发码。用一个临时随机密码 signUp，触发 Confirm signup 验证码邮件；真正的密码第 ③ 步再设。
  async function handleEmail(e: React.FormEvent) {
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
      const tempPassword = `${crypto.randomUUID()}Aa1!`;
      const { data, error } = await supabase.auth.signUp({
        email: email.trim(),
        password: tempPassword,
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      if (data.session) {
        // Confirm email 被关（注册即登录）→ 跳过验证码，直接去设密码。
        setStep("password");
        return;
      }
      // 无 session 时区分「真发了验证码」与「邮箱已注册被反枚举混淆」：
      //   新用户 / 未验证老用户 → data.user.identities 至少含一个身份（已发/重发验证码）。
      //   已注册（已验证）→ GoTrue 反枚举：data.user 可能为 null，或 identities 为空，且不发码。
      // 只认「拿到有效身份」为真正发了码；否则一律按已注册处理，避免用户傻等收不到的码。
      const codeSent = !!(data.user?.identities && data.user.identities.length > 0);
      if (!codeSent) {
        setError("该邮箱已注册，请直接登录（忘了密码可在登录页用「忘记密码？」找回）。");
        return;
      }
      setCooldown(60);
      setMessage("验证码已发送到邮箱，请查收（也看看垃圾箱）。");
      setStep("code");
    } catch (err) {
      console.error("[register] email", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  // ② 验证码 → 激活。
  async function handleCode(e: React.FormEvent) {
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
        type: "email",
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      setStep("password");
    } catch (err) {
      console.error("[register] code", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  // ③ 设密码 → 写入用户真正的密码，完成。
  async function handlePassword(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validatePassword(password);
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      setStep("success");
      // 成功态停留约 1.2s 让用户看到反馈，再进站。
      setTimeout(() => {
        router.push("/today");
        router.refresh();
      }, 1200);
    } catch (err) {
      console.error("[register] password", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    if (cooldown > 0 || loading) return;
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const { error } = await supabase.auth.resend({ type: "signup", email: email.trim() });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      setCooldown(60);
      setMessage("验证码已重新发送。");
    } catch (err) {
      console.error("[register] resend", err);
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  }

  if (!mounted || !open) return null;

  const activeIndex = stepIndex(step);

  return createPortal(
    <div
      className="fixed inset-0 z-[100] grid place-items-center bg-[#1a1714]/45 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        // 点遮罩关闭（加载中不关，避免打断请求）。
        if (e.target === e.currentTarget && !loading) onClose();
      }}
    >
      <div className="rise relative w-full max-w-[440px] overflow-hidden rounded-[1.6rem] border border-black/[0.06] dark:border-white/[0.1] bg-[#faf7f1] dark:bg-[#1c1813] shadow-[0_40px_90px_-30px_rgba(40,34,28,0.55)]">
        {/* 关闭 */}
        <button
          type="button"
          onClick={() => !loading && onClose()}
          aria-label="关闭"
          className="absolute right-4 top-4 grid size-8 place-items-center rounded-full text-[#8a8275] dark:text-[#9a9184] transition-colors hover:bg-black/[0.05] dark:hover:bg-white/[0.05] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]"
        >
          <X size={18} weight="bold" aria-hidden="true" />
        </button>

        <div className="p-7 sm:p-8">
          {/* 头部 */}
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-xl bg-[#1a1714] dark:bg-[#f3ecdf] text-[#f7f1e6] dark:text-[#16130f]">
              <ShieldCheck size={19} weight="fill" aria-hidden="true" />
            </span>
            <span className="display-tight text-lg font-medium tracking-tight text-[#1a1714] dark:text-[#f3ecdf]">
              注册职达
            </span>
          </div>

          {/* 进度条 */}
          <ol className="mt-6 flex items-center">
            {STEPS.map((s, i) => {
              const done = i < activeIndex;
              const active = i === activeIndex;
              return (
                <li key={s.key} className="flex flex-1 items-center last:flex-none">
                  <div className="flex flex-col items-center gap-1.5">
                    <span
                      className={[
                        "grid size-7 place-items-center rounded-full text-[12px] font-semibold transition-colors",
                        done
                          ? "bg-[#1a1714] dark:bg-[#f3ecdf] text-[#f7f1e6] dark:text-[#16130f]"
                          : active
                            ? "bg-[#1a1714] dark:bg-[#f3ecdf] text-[#f7f1e6] dark:text-[#16130f] ring-4 ring-[#1a1714]/10 dark:ring-[#f3ecdf]/20"
                            : "bg-black/[0.06] dark:bg-white/[0.06] text-[#9a9184] dark:text-[#837c70]",
                      ].join(" ")}
                    >
                      {done ? <Check size={13} weight="bold" aria-hidden="true" /> : i + 1}
                    </span>
                    <span
                      className={[
                        "text-[11px] font-medium",
                        done || active ? "text-[#1a1714] dark:text-[#f3ecdf]" : "text-[#9a9184] dark:text-[#837c70]",
                      ].join(" ")}
                    >
                      {s.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <span className="mx-2 mb-5 h-[2px] flex-1 overflow-hidden rounded-full bg-black/[0.07] dark:bg-white/[0.07]">
                      <span
                        className="block h-full rounded-full bg-[#1a1714] dark:bg-[#f3ecdf] transition-all duration-300"
                        style={{ width: i < activeIndex ? "100%" : "0%" }}
                      />
                    </span>
                  )}
                </li>
              );
            })}
          </ol>

          {/* 各步表单（key 触发淡入） */}
          <div key={step} className="rise mt-7">
            {step === "email" && (
              <form className="space-y-4" onSubmit={handleEmail}>
                <div>
                  <h3 className="text-[1.15rem] font-semibold text-[#1a1714] dark:text-[#f3ecdf]">填写你的邮箱</h3>
                  <p className="mt-1 text-[13px] text-[#8a8275] dark:text-[#9a9184]">我们会发一个 6 位验证码到这个邮箱</p>
                </div>
                <div>
                  <label htmlFor="reg-email" className="mb-1.5 block text-[13px] font-medium text-[#5f594e] dark:text-[#b6ad9d]">
                    邮箱
                  </label>
                  <div className="relative">
                    <EnvelopeSimple
                      size={17}
                      className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#a8a195] dark:text-[#837c70]"
                      aria-hidden="true"
                    />
                    <input
                      id="reg-email"
                      type="email"
                      required
                      autoFocus
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="field-editorial pl-10"
                      placeholder="you@example.com"
                    />
                  </div>
                </div>
                {error && <Banner kind="error">{error}</Banner>}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "发送中…" : "发送验证码"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
              </form>
            )}

            {step === "code" && (
              <form className="space-y-4" onSubmit={handleCode}>
                <div>
                  <h3 className="text-[1.15rem] font-semibold text-[#1a1714] dark:text-[#f3ecdf]">输入验证码</h3>
                  <p className="mt-1 text-[13px] text-[#8a8275] dark:text-[#9a9184]">
                    已发送至 <span className="font-medium text-[#5f594e] dark:text-[#b6ad9d]">{email}</span>
                  </p>
                </div>
                <input
                  id="reg-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  required
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className="field-editorial text-center text-xl font-semibold tracking-[0.4em]"
                  placeholder="········"
                />
                {error && <Banner kind="error">{error}</Banner>}
                {message && !error && <Banner kind="ok">{message}</Banner>}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "验证中…" : "验证并继续"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                <div className="flex items-center justify-between text-[12px]">
                  <button
                    type="button"
                    onClick={() => {
                      setError("");
                      setMessage("");
                      setStep("email");
                    }}
                    className="flex items-center gap-1 text-[#8a8275] dark:text-[#9a9184] hover:text-[#1a1714] dark:hover:text-[#f3ecdf]"
                  >
                    <ArrowLeft size={13} weight="bold" aria-hidden="true" />
                    改邮箱
                  </button>
                  <button
                    type="button"
                    onClick={handleResend}
                    disabled={cooldown > 0 || loading}
                    className="font-medium text-[#1a1714] dark:text-[#f3ecdf] underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-[#b8b1a4] dark:disabled:text-[#6b655a] disabled:no-underline"
                  >
                    {cooldown > 0 ? `重新发送 (${cooldown}s)` : "重新发送"}
                  </button>
                </div>
              </form>
            )}

            {step === "password" && (
              <form className="space-y-4" onSubmit={handlePassword}>
                <div>
                  <h3 className="text-[1.15rem] font-semibold text-[#1a1714] dark:text-[#f3ecdf]">设置登录密码</h3>
                  <p className="mt-1 text-[13px] text-[#8a8275] dark:text-[#9a9184]">下次用这个邮箱 + 密码就能登录</p>
                </div>
                <div>
                  <label htmlFor="reg-password" className="mb-1.5 block text-[13px] font-medium text-[#5f594e] dark:text-[#b6ad9d]">
                    密码
                  </label>
                  <div className="relative">
                    <Lock
                      size={17}
                      className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#a8a195] dark:text-[#837c70]"
                      aria-hidden="true"
                    />
                    <input
                      id="reg-password"
                      type={showPassword ? "text" : "password"}
                      required
                      autoFocus
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="field-editorial px-10"
                      placeholder="至少 6 位"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "隐藏密码" : "显示密码"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#a8a195] dark:text-[#837c70] hover:text-[#5f594e] dark:hover:text-[#b6ad9d]"
                    >
                      {showPassword ? (
                        <EyeSlash size={17} aria-hidden="true" />
                      ) : (
                        <Eye size={17} aria-hidden="true" />
                      )}
                    </button>
                  </div>
                </div>
                {error && <Banner kind="error">{error}</Banner>}
                <button type="submit" disabled={loading} className="btn-ink w-full">
                  {loading ? "创建中…" : "完成注册"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
              </form>
            )}

            {step === "success" && (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <span className="grid size-16 place-items-center rounded-full bg-[#eef4e8] dark:bg-[#1e2a17] text-[#4a6b3c] dark:text-[#a3d06a]">
                  <CheckCircle size={40} weight="fill" aria-hidden="true" />
                </span>
                <h3 className="text-[1.25rem] font-semibold text-[#1a1714] dark:text-[#f3ecdf]">注册成功</h3>
                <p className="text-[13px] text-[#8a8275] dark:text-[#9a9184]">正在进入今日看板…</p>
              </div>
            )}
          </div>

          {step !== "success" && (
            <p className="mt-6 text-center text-[12px] text-[#9a9184] dark:text-[#837c70]">
              已有账号？{" "}
              <button
                type="button"
                onClick={() => !loading && onClose()}
                className="font-medium text-[#1a1714] dark:text-[#f3ecdf] hover:underline"
              >
                去登录
              </button>
            </p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// 内联提示条，沿用登录页同款配色。
function Banner({ kind, children }: { kind: "error" | "ok"; children: React.ReactNode }) {
  const cls =
    kind === "error"
      ? "border-[#e0b4ac] dark:border-[#7a392e]/60 bg-[#f7e6e1] dark:bg-[#3a201a] text-[#9c4a3c] dark:text-[#e6a99f]"
      : "border-[#b9cfb0] dark:border-[#3f5a2e]/60 bg-[#eef4e8] dark:bg-[#1e2a17] text-[#4a6b3c] dark:text-[#a3d06a]";
  return (
    <p className={`rounded-2xl border px-4 py-2.5 text-[13px] ${cls}`}>{children}</p>
  );
}
