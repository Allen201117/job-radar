"use client";

import { useEffect, useState } from "react";
import { Sun, Moon } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

/**
 * 深 / 浅色切换。无 next-themes 依赖：直接增删 <html> 的 .dark 类并写入 localStorage。
 * 初值由 app/layout.tsx 的 no-flash 脚本在首帧前设好，这里只读当前态。
 */
export default function ThemeToggle({ className }: { className?: string }) {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("jr-theme", next ? "dark" : "light");
    } catch {
      /* localStorage 不可用时仅本次会话生效 */
    }
    setDark(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "切换到浅色模式" : "切换到深色模式"}
      className={cn(
        "grid size-9 place-items-center rounded-full border border-black/[0.08] text-[#3f3a33] transition duration-200 hover:bg-black/[0.05] active:scale-[0.96] dark:border-white/[0.12] dark:text-[#d9d0c2] dark:hover:bg-white/[0.06]",
        className,
      )}
    >
      {dark ? (
        <Sun size={17} weight="bold" aria-hidden="true" />
      ) : (
        <Moon size={17} weight="bold" aria-hidden="true" />
      )}
    </button>
  );
}
