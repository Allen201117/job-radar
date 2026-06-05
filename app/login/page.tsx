"use client";

import { useState } from "react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useRouter } from "next/navigation";
import { ArrowRight, Broadcast, CheckCircle, MapPin } from "@phosphor-icons/react";

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
              登录 / 注册
            </h2>
            <p className="mt-1.5 text-[14px] text-[#8a8275]">使用邮箱进入今日看板</p>

            <form className="mt-6 space-y-4" onSubmit={handleSignIn}>
              <div>
                <label
                  htmlFor="email"
                  className="mb-1.5 block text-[13px] font-medium text-[#5f594e]"
                >
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
                <label
                  htmlFor="password"
                  className="mb-1.5 block text-[13px] font-medium text-[#5f594e]"
                >
                  密码
                </label>
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

              <div className="flex gap-2.5 pt-1">
                <button type="submit" disabled={loading} className="btn-ink flex-1">
                  {loading ? "登录中…" : "登录"}
                  <ArrowRight size={16} weight="bold" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  disabled={loading}
                  onClick={handleSignUp}
                  className="btn-ghost"
                >
                  注册
                </button>
              </div>
            </form>
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
