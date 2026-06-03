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
  Database,
  SlidersHorizontal,
  Sparkle,
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
  const [isAdmin, setIsAdmin] = useState(false);
  const [lang, setLang] = useLang();

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      const user = data.user;
      setEmail(user?.email ?? null);
      if (!user) return;
      supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single()
        .then(({ data: profile }) => {
          setIsAdmin(profile?.role === "admin");
        });
    });
  }, []);

  const links = isAdmin
    ? [
        ...LINKS,
        { href: "/admin/insights", key: "insightsAdmin", icon: Sparkle },
        { href: "/sources", key: "sources", icon: Database },
      ]
    : LINKS;

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-white/10 bg-[#08090c]/88 text-white backdrop-blur-xl supports-[backdrop-filter]:bg-[#08090c]/74">
      <div className="mx-auto flex min-h-14 max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 lg:h-14 lg:flex-row lg:items-center lg:justify-between lg:gap-6 lg:py-0 lg:px-8">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:gap-7">
          <Link href="/" className="inline-flex items-center gap-2 text-sm font-semibold text-white transition-colors hover:text-sky-200">
            <span className="grid size-7 place-items-center rounded-xl bg-white text-[#08090c]">
              <Broadcast size={16} weight="fill" aria-hidden="true" />
            </span>
            Job Radar
          </Link>
          <nav className="flex max-w-full gap-1 overflow-x-auto">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition duration-200",
                  pathname === link.href
                    ? "bg-white text-[#08090c]"
                    : "text-white/58 hover:bg-white/10 hover:text-white active:scale-[0.98]",
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
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs font-medium text-white/58 transition duration-200 hover:bg-white/10 hover:text-white active:scale-[0.98]"
            title="切换语言 / Switch language"
          >
            {lang === "zh" ? "EN" : "中"}
          </button>
          {email && <span className="hidden max-w-48 truncate text-xs text-white/46 md:block">{email}</span>}
          <button
            onClick={handleLogout}
            className="rounded-full px-3 py-1.5 text-xs font-medium text-white/58 transition duration-200 hover:bg-white/10 hover:text-white active:scale-[0.98]"
          >
            {t("logout", lang)}
          </button>
        </div>
      </div>
    </header>
  );
}
