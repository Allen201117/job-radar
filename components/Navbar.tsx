"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";
import {
  BookmarkSimple,
  Briefcase,
  Broadcast,
  CheckCircle,
  Compass,
  List,
  SignOut,
  SlidersHorizontal,
  UserCircle,
  X,
} from "@phosphor-icons/react";

// 一级导航（§3.1）：今日机会 / 搜索岗位 / 职业路径 / 关注与偏好 / 值得投 / 已投递。
// /me 移入账号菜单。/sources、/admin/* 仅管理员直达。
const LINKS = [
  { href: "/today", key: "today", icon: Broadcast },
  { href: "/jobs", key: "jobs", icon: Briefcase },
  { href: "/path", key: "path", icon: Compass },
  { href: "/preferences", key: "preferences", icon: SlidersHorizontal },
  { href: "/saved", key: "saved", icon: BookmarkSimple },
  { href: "/applied", key: "applied", icon: CheckCircle },
];

type JobScope = "domestic" | "overseas" | "all";

const JOB_SCOPE_OPTIONS: { value: JobScope; label: string }[] = [
  { value: "domestic", label: "国内" },
  { value: "overseas", label: "海外" },
  { value: "all", label: "全都要" },
];

const JOB_SCOPE_TOAST: Record<JobScope, string> = {
  domestic: "已切换到国内岗位",
  overseas: "已切换到海外岗位",
  all: "已切换到全部岗位",
};

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createBrowserClient();
  const [email, setEmail] = useState<string | null>(null);
  // i18n 暂收口：导航固定中文，不放开语言切换（基础设施保留在 lib/i18n.ts）。
  const lang = "zh" as const;
  const [menuOpen, setMenuOpen] = useState(false);
  const [acctOpen, setAcctOpen] = useState(false);
  const [jobScope, setJobScope] = useState<JobScope>("domestic");
  const [scopeSaving, setScopeSaving] = useState(false);
  const [scopeToast, setScopeToast] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
    });
  }, []);

  useEffect(() => {
    if (!email) return;
    let cancelled = false;
    fetch("/api/preferences")
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (cancelled) return;
        setJobScope(normalizeJobScope(data?.preferences?.job_scope));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [email]);

  useEffect(() => {
    setMenuOpen(false);
    setAcctOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!scopeToast) return;
    const timer = window.setTimeout(() => setScopeToast(null), 2000);
    return () => window.clearTimeout(timer);
  }, [scopeToast]);

  useEffect(() => {
    if (!menuOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  async function handleScopeChange(next: JobScope) {
    if (next === jobScope || scopeSaving) return;
    const previous = jobScope;
    setJobScope(next);
    setScopeSaving(true);
    try {
      const resp = await fetch("/api/preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_scope: next }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
      const savedScope = normalizeJobScope(data.preferences?.job_scope);
      setJobScope(savedScope);
      setScopeToast(JOB_SCOPE_TOAST[savedScope]);
      window.dispatchEvent(new Event("preferences-scope-updated"));
      router.refresh();
    } catch (e) {
      console.error("[navbar] failed to update job scope:", (e as Error).message);
      setJobScope(previous);
    } finally {
      setScopeSaving(false);
    }
  }

  // 账号头像：邮箱 @ 前作为用户名，取首字符作圆形头像标识（悬停/展开可看完整用户名）。
  const username = email ? email.split("@")[0] : "";
  const initial = username ? username.charAt(0).toUpperCase() : "?";

  return (
    <header className="sticky top-0 z-40 w-full border-b border-black/[0.06] bg-[#f4efe6]/80 text-[#1a1714] backdrop-blur-xl supports-[backdrop-filter]:bg-[#f4efe6]/70 dark:border-white/[0.08] dark:bg-[#16130f]/[0.85] dark:text-[#f3ecdf] dark:supports-[backdrop-filter]:bg-[#16130f]/[0.70]">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:gap-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-7">
          {/* 登录后 Logo 跳今日机会；未登录跳公开 Landing */}
          <Link
            href={email ? "/today" : "/"}
            className="inline-flex shrink-0 items-center transition-opacity hover:opacity-70"
          >
            <BrandMark tile={28} icon={18} wordSize={15} />
          </Link>
          {/* 桌面端：图标导航栏（lg 以上内联）。图标化后占位更小，不再与右侧控件抢空间，
              因此恢复 lg 断点、无需退化为汉堡菜单；hover / 键盘聚焦升起气泡标签说明去处。 */}
          <nav className="hidden items-center gap-1 lg:flex">
            {LINKS.map((link) => {
              const active = pathname === link.href;
              const label = t(link.key, lang);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-label={label}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative grid size-9 shrink-0 place-items-center rounded-full outline-none transition duration-200 focus-visible:ring-2 focus-visible:ring-[#1a1714]/25 dark:focus-visible:ring-[#f3ecdf]/30",
                    active
                      ? "bento-selected bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                      : "text-[#5f594e] hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.95] dark:text-[#b6ad9d] dark:hover:bg-white/[0.06] dark:hover:text-[#f3ecdf]",
                  )}
                >
                  <link.icon size={19} weight={active ? "fill" : "regular"} aria-hidden="true" />
                  {/* 气泡标签：纯视觉，真实无障碍名走 aria-label；默认隐藏，hover / 聚焦时升起 */}
                  <span
                    role="tooltip"
                    className="pointer-events-none absolute left-1/2 top-full z-50 mt-2.5 -translate-x-1/2 translate-y-1 whitespace-nowrap rounded-lg bg-[#1a1714] px-2.5 py-1 text-xs font-medium text-[#f7f1e6] opacity-0 shadow-[0_12px_30px_-14px_rgba(26,23,20,0.7)] transition duration-200 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  >
                    <span
                      aria-hidden="true"
                      className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rotate-45 rounded-[2px] bg-[#1a1714] dark:bg-[#f3ecdf]"
                    />
                    {label}
                  </span>
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          {email && (
            <JobScopeSwitch
              value={jobScope}
              saving={scopeSaving}
              onChange={handleScopeChange}
              className="hidden lg:flex"
            />
          )}
          <ThemeToggle />
          {/* 桌面端账号菜单：个人主页 + 退出（/me 不再占一级导航） */}
          {email && (
            <div className="relative hidden lg:block">
              <button
                type="button"
                onClick={() => setAcctOpen((v) => !v)}
                aria-expanded={acctOpen}
                aria-label={`账号 ${username}`}
                className={cn(
                  "group relative grid size-9 place-items-center rounded-full border text-xs font-semibold uppercase outline-none transition duration-200 ease-out active:scale-[0.96] focus-visible:ring-2 focus-visible:ring-[#1a1714]/25 dark:focus-visible:ring-[#f3ecdf]/30",
                  acctOpen
                    ? "border-transparent bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "border-black/[0.08] text-[#5f594e] hover:bg-black/[0.05] hover:text-[#1a1714] dark:border-white/[0.12] dark:text-[#b6ad9d] dark:hover:bg-white/[0.06] dark:hover:text-[#f3ecdf]",
                )}
              >
                {initial}
                {!acctOpen && (
                  <span
                    role="tooltip"
                    className="pointer-events-none absolute right-0 top-full z-50 mt-2.5 translate-y-1 whitespace-nowrap rounded-lg bg-[#1a1714] px-2.5 py-1 text-xs font-medium normal-case text-[#f7f1e6] opacity-0 shadow-[0_12px_30px_-14px_rgba(26,23,20,0.7)] transition duration-200 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  >
                    <span
                      aria-hidden="true"
                      className="absolute -top-1 right-3.5 size-2 rotate-45 rounded-[2px] bg-[#1a1714] dark:bg-[#f3ecdf]"
                    />
                    {username}
                  </span>
                )}
              </button>
              {acctOpen && (
                <>
                  <button
                    type="button"
                    aria-label="关闭账号菜单"
                    onClick={() => setAcctOpen(false)}
                    className="fixed inset-0 z-30 cursor-default"
                  />
                  <div className="absolute right-0 z-40 mt-2 w-52 rounded-2xl border border-black/[0.08] bg-[#f4efe6]/98 p-1 shadow-lg backdrop-blur-xl dark:border-white/[0.12] dark:bg-[#16130f]/[0.98]">
                    <div className="mb-1 border-b border-black/[0.06] px-3 pb-2 pt-1.5 dark:border-white/[0.08]">
                      <p className="truncate text-sm font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{username}</p>
                      <p className="truncate text-xs text-[#9a9184] dark:text-[#837c70]">{email}</p>
                    </div>
                    <Link
                      href="/me"
                      onClick={() => setAcctOpen(false)}
                      className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-black/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]"
                    >
                      <UserCircle size={16} aria-hidden="true" />
                      个人主页
                    </Link>
                    <button
                      type="button"
                      onClick={handleLogout}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-medium text-[#3f3a33] transition hover:bg-black/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]"
                    >
                      <SignOut size={16} aria-hidden="true" />
                      {t("logout", lang)}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
          {/* 移动端：汉堡按钮 */}
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? "关闭菜单" : "打开菜单"}
            aria-expanded={menuOpen}
            className="grid size-9 place-items-center rounded-full border border-black/[0.08] text-[#3f3a33] transition duration-200 hover:bg-black/[0.05] active:scale-[0.96] lg:hidden dark:border-white/[0.12] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]"
          >
            {menuOpen ? <X size={18} weight="bold" aria-hidden="true" /> : <List size={18} weight="bold" aria-hidden="true" />}
          </button>
        </div>
      </div>

      {/* 移动端下拉菜单（lg 以下） */}
      {menuOpen && (
        <>
          <div
            aria-hidden="true"
            onClick={() => setMenuOpen(false)}
            className="fixed inset-0 top-14 z-30 bg-[#1a1714]/20 backdrop-blur-sm lg:hidden dark:bg-black/50"
          />
          <nav className="relative z-40 border-t border-black/[0.06] bg-[#f4efe6]/95 px-4 pb-4 pt-2 backdrop-blur-xl lg:hidden dark:border-white/[0.08] dark:bg-[#16130f]/[0.95]">
            {LINKS.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl px-3.5 py-3 text-[15px] font-medium transition duration-200",
                    active
                      ? "bento-selected bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                      : "text-[#3f3a33] hover:bg-black/[0.05] active:scale-[0.99] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]",
                  )}
                >
                  <link.icon size={20} weight={active ? "fill" : "regular"} aria-hidden="true" />
                  {t(link.key, lang)}
                </Link>
              );
            })}
            {email && (
              <div className="mb-2 border-b border-black/[0.06] pb-3 dark:border-white/[0.08]">
                <JobScopeSwitch
                  value={jobScope}
                  saving={scopeSaving}
                  onChange={handleScopeChange}
                  className="flex"
                  mobile
                />
              </div>
            )}
            {email && (
              <Link
                href="/me"
                onClick={() => setMenuOpen(false)}
                className={cn(
                  "flex items-center gap-3 rounded-2xl px-3.5 py-3 text-[15px] font-medium transition duration-200",
                  pathname === "/me"
                    ? "bento-selected bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "text-[#3f3a33] hover:bg-black/[0.05] active:scale-[0.99] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]",
                )}
              >
                <UserCircle size={20} weight={pathname === "/me" ? "fill" : "regular"} aria-hidden="true" />
                {t("me", lang)}
              </Link>
            )}
            <div className="mt-2 flex items-center justify-between gap-3 border-t border-black/[0.06] pt-3 dark:border-white/[0.08]">
              {email && <span className="min-w-0 flex-1 truncate text-xs text-[#9a9184] dark:text-[#837c70]">{email}</span>}
              <button
                onClick={handleLogout}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-4 py-2 text-[13px] font-medium text-[#3f3a33] transition duration-200 hover:bg-white active:scale-[0.98] dark:border-white/[0.12] dark:bg-white/[0.06] dark:text-[#d9d0c2] dark:hover:bg-white/[0.12]"
              >
                <SignOut size={16} weight="bold" aria-hidden="true" />
                {t("logout", lang)}
              </button>
            </div>
          </nav>
        </>
      )}
      {scopeToast && (
        <div className="pointer-events-none fixed inset-x-0 top-16 z-[120] flex justify-center px-4">
          <div
            role="status"
            aria-live="polite"
            className="save-pop rounded-full border border-black/[0.08] bg-white/95 px-4 py-2 text-sm font-semibold text-[#1a1714] shadow-[0_18px_40px_-24px_rgba(40,34,28,0.6)] backdrop-blur-xl dark:border-white/[0.12] dark:bg-[#1e1a15]/95 dark:text-[#f3ecdf] dark:shadow-[0_18px_40px_-24px_rgba(0,0,0,0.75)]"
          >
            {scopeToast}
          </div>
        </div>
      )}
    </header>
  );
}

function normalizeJobScope(value: unknown): JobScope {
  return value === "overseas" || value === "all" ? value : "domestic";
}

function JobScopeSwitch({
  value,
  saving,
  onChange,
  className,
  mobile = false,
}: {
  value: JobScope;
  saving: boolean;
  onChange: (value: JobScope) => void;
  className?: string;
  mobile?: boolean;
}) {
  return (
    <div className={cn("items-center gap-2", className)}>
      <span className={cn("shrink-0 text-xs font-medium text-[#8a8275] dark:text-[#9a9184]", mobile ? "w-16" : "")}>
        求职范围
      </span>
      <div className="grid grid-cols-3 rounded-full border border-black/[0.08] bg-white/55 p-0.5 dark:border-white/[0.12] dark:bg-white/[0.05]">
        {JOB_SCOPE_OPTIONS.map((opt) => {
          const selected = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              disabled={saving}
              aria-pressed={selected}
              onClick={() => onChange(opt.value)}
              className={cn(
                "h-7 min-w-14 rounded-full px-2 text-xs font-semibold transition duration-200 disabled:cursor-wait disabled:opacity-70",
                selected
                  ? "bg-[#1a1714] text-[#f7f1e6] shadow-sm dark:bg-[#f3ecdf] dark:text-[#16130f]"
                  : "text-[#5f594e] hover:bg-black/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.06]",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
