"use client";

import { useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useRouter } from "next/navigation";
import { ArrowRight, Broadcast, EnvelopeSimple, LockKey } from "@phosphor-icons/react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const router = useRouter();
  const supabase = createBrowserClient();

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) {
      setError(error.message);
    } else {
      router.push("/today");
      router.refresh();
    }
    setLoading(false);
  }

  async function handleSignUp(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    const { error } = await supabase.auth.signUp({
      email,
      password,
    });
    if (error) {
      setError(error.message);
    } else {
      setMessage("注册链接已发送到邮箱，请查收。");
    }
    setLoading(false);
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
