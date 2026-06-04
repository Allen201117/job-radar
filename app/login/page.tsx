"use client";

import { useEffect, useRef, useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useRouter } from "next/navigation";
import { ArrowRight, Broadcast, EnvelopeSimple, LockKey } from "@phosphor-icons/react";

// 把 Supabase/GoTrue 的原始英文报错映射成面向用户的友好中文提示，绝不直接抛原始串。
function mapAuthError(error: { message?: string; status?: number }): string {
  const raw = (error?.message || "").toLowerCase();
  if (raw.includes("invalid login credentials")) return "邮箱或密码不正确";
  if (raw.includes("email not confirmed")) return "邮箱尚未验证，请先点击邮件里的验证链接";
  if (raw.includes("already registered") || raw.includes("already been registered"))
    return "该邮箱已注册，请直接登录";
  if (raw.includes("signups not allowed")) return "注册暂未开放，请联系管理员开通";
  if (raw.includes("password should be at least")) return "密码至少需要 6 位";
  if (raw.includes("unable to validate email") || raw.includes("invalid format"))
    return "邮箱格式不正确";
  if (raw.includes("rate limit") || raw.includes("for security purposes"))
    return "操作过于频繁，请稍后再试";
  if (raw.includes("failed to fetch") || raw.includes("network")) return "网络异常，请检查网络后重试";
  return "操作失败，请稍后重试";
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState<null | "in" | "up">(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const router = useRouter();
  const supabase = createBrowserClient();

  // 鼠标跟随的信号光：直接改 DOM transform（带 CSS 缓动），避免每帧 setState 重渲染。
  const lightRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const el = lightRef.current;
      if (el) el.style.transform = `translate(${e.clientX}px, ${e.clientY}px) translate(-50%, -50%)`;
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  // 提交前的本地校验，避免把明显无效的输入打到后端再拿英文报错。
  function validate(): string | null {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "请输入有效的邮箱地址";
    if (password.length < 6) return "密码至少需要 6 位";
    return null;
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    const invalid = validate();
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading("in");
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      router.push("/today");
      router.refresh();
    } catch {
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(null);
    }
  }

  async function handleSignUp() {
    setError("");
    setMessage("");
    const invalid = validate();
    if (invalid) {
      setError(invalid);
      return;
    }
    setLoading("up");
    try {
      const { data, error } = await supabase.auth.signUp({
        email: email.trim(),
        password,
      });
      if (error) {
        setError(mapAuthError(error));
        return;
      }
      if (data.session) {
        // 项目关闭了邮箱验证：注册即登录，直接进产品。
        router.push("/today");
        router.refresh();
      } else {
        // 项目仍开启邮箱验证：提示去邮箱激活。
        setMessage("注册成功，请到邮箱点击验证链接后再登录。");
      }
    } catch {
      setError("网络异常，请检查网络后重试");
    } finally {
      setLoading(null);
    }
  }

  const busy = loading !== null;

  return (
    <main className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden bg-background px-4 text-foreground">
      {/* 仪表底纹 + 鼠标跟随信号光，取代原来的霓虹径向渐变 */}
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-70" />
      <div
        ref={lightRef}
        aria-hidden="true"
        className="pointer-events-none fixed left-0 top-0 z-0 size-[620px] rounded-full opacity-70 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          background: "radial-gradient(closest-side, hsl(var(--signal) / 0.12), transparent)",
          transform: "translate(52vw, 38vh) translate(-50%, -50%)",
        }}
      />

      <div className="animate-rise relative z-10 w-full max-w-[400px] rounded-xl border border-border bg-surface/85 p-7 shadow-[0_1px_0_0_hsl(var(--foreground)/0.05)_inset] backdrop-blur-sm sm:p-8">
        <div className="flex items-center gap-3">
          <span className="relative grid size-11 shrink-0 place-items-center rounded-lg border border-border bg-background text-signal">
            <span className="absolute inset-0 animate-ping-slow rounded-lg border border-signal/40" aria-hidden="true" />
            <Broadcast size={22} weight="fill" aria-hidden="true" />
          </span>
          <div>
            <h1 className="font-mono text-xl font-semibold tracking-tight">Job Radar</h1>
            <p className="text-sm text-muted-foreground">使用邮箱登录或注册</p>
          </div>
        </div>

        <form className="mt-7 space-y-4" onSubmit={handleSignIn}>
          <div>
            <label htmlFor="email" className="mb-1.5 inline-flex items-center gap-1.5 text-sm font-medium text-foreground/80">
              <EnvelopeSimple size={15} weight="bold" aria-hidden="true" />
              邮箱
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="block w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition duration-200 placeholder:text-muted-foreground/70 focus:border-signal focus:bg-surface-2 focus:shadow-[0_0_0_3px_hsl(var(--signal)/0.15)]"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 inline-flex items-center gap-1.5 text-sm font-medium text-foreground/80">
              <LockKey size={15} weight="bold" aria-hidden="true" />
              密码
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="block w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition duration-200 placeholder:text-muted-foreground/70 focus:border-signal focus:bg-surface-2 focus:shadow-[0_0_0_3px_hsl(var(--signal)/0.15)]"
              placeholder="至少 6 位"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
          {message && (
            <p className="rounded-lg border border-signal/30 bg-signal/10 px-3 py-2 text-sm text-signal">
              {message}
            </p>
          )}

          <div className="flex gap-2.5 pt-1">
            <button
              type="submit"
              disabled={busy}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-signal px-4 py-2.5 text-sm font-semibold text-signal-foreground transition duration-200 hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-55"
            >
              {loading === "in" ? "登录中…" : "登录"}
              {loading !== "in" && <ArrowRight size={16} weight="bold" aria-hidden="true" />}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={handleSignUp}
              className="rounded-lg border border-border bg-surface px-4 py-2.5 text-sm font-medium text-foreground/85 transition duration-200 hover:border-foreground/25 hover:bg-surface-2 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-55"
            >
              {loading === "up" ? "注册中…" : "注册"}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
