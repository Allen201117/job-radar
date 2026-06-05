"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useLang, t } from "@/lib/i18n";
import {
  BookmarkSimple,
  Briefcase,
  Broadcast,
  CheckCircle,
  Compass,
  SlidersHorizontal,
  UserCircle,
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
  const [lang, setLang] = useLang();

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
    });
  }, []);

  // 洞察管理 / 源管理为管理员内部工具，不在导航中暴露给用户（仍可经 /admin/insights、/sources 直达）
  const links = LINKS;

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-black/[0.06] bg-[#f4efe6]/80 text-[#1a1714] backdrop-blur-xl supports-[backdrop-filter]:bg-[#f4efe6]/70">
      <div className="mx-auto flex min-h-14 max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 lg:h-14 lg:flex-row lg:items-center lg:justify-between lg:gap-6 lg:py-0 lg:px-8">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:gap-7">
          <Link href="/" className="inline-flex items-center gap-2 text-[#1a1714] transition-opacity hover:opacity-70">
            <span className="grid size-7 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6]">
              <Broadcast size={16} weight="fill" aria-hidden="true" />
            </span>
            <span className="display-tight text-[15px] font-semibold">Job Radar</span>
          </Link>
          <nav className="scrollbar-hide flex max-w-full gap-1 overflow-x-auto">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition duration-200",
                  pathname === link.href
                    ? "bg-[#1a1714] text-[#f7f1e6]"
                    : "text-[#5f594e] hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.98]",
                )}
              >
                <link.icon size={16} weight={pathname === link.href ? "fill" : "regular"} aria-hidden="true" />
                {t(link.key, lang)}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            className="rounded-full border border-black/[0.08] px-3 py-1.5 text-xs font-medium text-[#5f594e] transition duration-200 hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.98]"
            title="切换语言 / Switch language"
          >
            {lang === "zh" ? "EN" : "中"}
          </button>
          {email && <span className="hidden max-w-48 truncate text-xs text-[#9a9184] md:block">{email}</span>}
          <button
            onClick={handleLogout}
            className="rounded-full px-3 py-1.5 text-xs font-medium text-[#5f594e] transition duration-200 hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.98]"
          >
            {t("logout", lang)}
          </button>
        </div>
      </div>
    </header>
  );
}
