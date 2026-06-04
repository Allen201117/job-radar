"use client";

import { useState } from "react";
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const router = useRouter();
  const supabase = createBrowserClient();

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
    setLoading(true);
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
      setLoading(false);
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
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#08090c] px-4 text-white">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(56,189,248,0.18),transparent_32%),radial-gradient(circle_at_5%_75%,rgba(163,230,53,0.10),transparent_28%)]" />
      <div className="relative w-full max-w-sm space-y-6 rounded-[1.5rem] border border-white/10 bg-white/[0.065] p-8 shadow-2xl shadow-black/30">
        <div>
          <div className="mb-4 grid size-11 place-items-center rounded-2xl bg-white text-[#08090c]">
            <Broadcast size={22} weight="fill" aria-hidden="true" />
          </div>
          <h1 className="text-3xl font-semibold leading-tight">Job Radar</h1>
          <p className="mt-1 text-sm text-white/52">
            使用邮箱登录或注册
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSignIn}>
          <div>
            <label htmlFor="email" className="inline-flex items-center gap-1.5 text-sm font-medium text-white/76">
              <EnvelopeSimple size={16} weight="bold" aria-hidden="true" />
              邮箱
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label htmlFor="password" className="inline-flex items-center gap-1.5 text-sm font-medium text-white/76">
              <LockKey size={16} weight="bold" aria-hidden="true" />
              密码
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-full bg-red-400/10 px-3 py-2 text-sm text-red-200">{error}</p>
          )}
          {message && (
            <p className="rounded-full bg-sky-300/10 px-3 py-2 text-sm text-sky-200">{message}</p>
          )}

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={loading}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-full bg-sky-300 px-4 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:opacity-50"
            >
              {loading ? "登录中..." : "登录"}
              <ArrowRight size={16} weight="bold" aria-hidden="true" />
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={handleSignUp}
              className="rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white/78 transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98] disabled:opacity-50"
            >
              注册
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
