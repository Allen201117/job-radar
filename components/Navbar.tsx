"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
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

const LINKS = [
  { href: "/today", key: "today", icon: Broadcast },
  { href: "/jobs", key: "jobs", icon: Briefcase },
  { href: "/path", key: "path", icon: Compass },
  { href: "/preferences", key: "preferences", icon: SlidersHorizontal },
  { href: "/me", key: "me", icon: UserCircle },
  { href: "/saved", key: "saved", icon: BookmarkSimple },
  { href: "/applied", key: "applied", icon: CheckCircle },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createBrowserClient();
  const [email, setEmail] = useState<string | null>(null);
  // i18n 暂收口：lib/i18n 字典目前只覆盖导航，正文全中文，切到 EN 多数内容不变 = 误导。
  // 先隐藏语言切换入口、导航固定中文，待关键页 i18n 补齐再放开（i18n 基础设施保留在 lib/i18n.ts）。
  const lang = "zh" as const;
  // 移动端汉堡菜单展开态（桌面端 lg+ 不使用）
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
    });
  }, []);

  // 路由切换或视口拉宽到桌面时收起菜单；展开时锁滚动 + 支持 Esc 关闭
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

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

  // 洞察管理 / 源管理为管理员内部工具，不在导航中暴露给用户（仍可经 /admin/insights、/sources 直达）
  const links = LINKS;

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-black/[0.06] bg-[#f4efe6]/80 text-[#1a1714] backdrop-blur-xl supports-[backdrop-filter]:bg-[#f4efe6]/70">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:gap-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-7">
          <Link href="/" className="inline-flex shrink-0 items-center gap-2 text-[#1a1714] transition-opacity hover:opacity-70">
            <span className="grid size-7 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6]">
              <Broadcast size={16} weight="fill" aria-hidden="true" />
            </span>
            <span className="display-tight text-[15px] font-semibold">Job Radar</span>
          </Link>
          {/* 桌面端：内联导航胶囊（lg 以下交给汉堡菜单） */}
          <nav className="hidden gap-1 lg:flex">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition duration-200",
                  pathname === link.href
                    ? "bento-selected bg-[#1a1714] text-[#f7f1e6]"
                    : "text-[#5f594e] hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.98]",
                )}
              >
                <link.icon size={16} weight={pathname === link.href ? "fill" : "regular"} aria-hidden="true" />
                {t(link.key, lang)}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          {email && <span className="hidden max-w-48 truncate text-xs text-[#9a9184] md:block">{email}</span>}
          {/* 桌面端退出（移动端移入汉堡菜单） */}
          <button
            onClick={handleLogout}
            className="hidden rounded-full px-3 py-1.5 text-xs font-medium text-[#5f594e] transition duration-200 hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.98] lg:inline-flex"
          >
            {t("logout", lang)}
          </button>
          {/* 移动端：汉堡按钮 */}
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? "关闭菜单" : "打开菜单"}
            aria-expanded={menuOpen}
            className="grid size-9 place-items-center rounded-full border border-black/[0.08] text-[#3f3a33] transition duration-200 hover:bg-black/[0.05] active:scale-[0.96] lg:hidden"
          >
            {menuOpen ? <X size={18} weight="bold" aria-hidden="true" /> : <List size={18} weight="bold" aria-hidden="true" />}
          </button>
        </div>
      </div>

      {/* 移动端下拉菜单（lg 以下） */}
      {menuOpen && (
        <>
          <button
            type="button"
            aria-label="关闭菜单"
            onClick={() => setMenuOpen(false)}
            className="fixed inset-0 top-14 z-30 bg-[#1a1714]/20 backdrop-blur-sm lg:hidden"
          />
          <nav className="relative z-40 border-t border-black/[0.06] bg-[#f4efe6]/95 px-4 pb-4 pt-2 backdrop-blur-xl lg:hidden">
            {links.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl px-3.5 py-3 text-[15px] font-medium transition duration-200",
                    active
                      ? "bento-selected bg-[#1a1714] text-[#f7f1e6]"
                      : "text-[#3f3a33] hover:bg-black/[0.05] active:scale-[0.99]",
                  )}
                >
                  <link.icon size={20} weight={active ? "fill" : "regular"} aria-hidden="true" />
                  {t(link.key, lang)}
                </Link>
              );
            })}
            <div className="mt-2 flex items-center justify-between gap-3 border-t border-black/[0.06] pt-3">
              {email && <span className="min-w-0 flex-1 truncate text-xs text-[#9a9184]">{email}</span>}
              <button
                onClick={handleLogout}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-black/[0.08] bg-white/70 px-4 py-2 text-[13px] font-medium text-[#3f3a33] transition duration-200 hover:bg-white active:scale-[0.98]"
              >
                <SignOut size={16} weight="bold" aria-hidden="true" />
                {t("logout", lang)}
              </button>
            </div>
          </nav>
        </>
      )}
    </header>
  );
}
