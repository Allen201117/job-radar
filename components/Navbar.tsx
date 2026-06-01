"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createBrowserClient } from "@/lib/supabaseClient";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useLang, t } from "@/lib/i18n";

const LINKS = [
  { href: "/", key: "today" },
  { href: "/jobs", key: "jobs" },
  { href: "/preferences", key: "preferences" },
  { href: "/me", key: "me" },
  { href: "/saved", key: "saved" },
  { href: "/applied", key: "applied" },
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

  const links = isAdmin ? [...LINKS, { href: "/sources", key: "sources" }] : LINKS;

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-semibold text-primary">
            Job Radar
          </Link>
          <nav className="flex gap-1">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  pathname === link.href
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t(link.key, lang)}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            className="rounded-md border px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            title="切换语言 / Switch language"
          >
            {lang === "zh" ? "EN" : "中"}
          </button>
          {email && <span className="text-xs text-muted-foreground">{email}</span>}
          <button
            onClick={handleLogout}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            {t("logout", lang)}
          </button>
        </div>
      </div>
    </header>
  );
}
