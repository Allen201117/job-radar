"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const SHOW_AFTER_PX = 600;

export default function BackToTop() {
  const [visible, setVisible] = useState(false);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const updateVisibility = () => {
      frameRef.current = null;
      setVisible(window.scrollY > SHOW_AFTER_PX);
    };

    const handleScroll = () => {
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(updateVisibility);
    };

    updateVisibility();
    window.addEventListener("scroll", handleScroll, { passive: true });

    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, []);

  const scrollToTop = () => {
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
  };

  return (
    <button
      type="button"
      onClick={scrollToTop}
      aria-label="回到顶部"
      aria-hidden={!visible}
      tabIndex={visible ? 0 : -1}
      className={cn(
        "fixed bottom-[max(1.5rem,env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-40 grid size-11 place-items-center rounded-full border border-black/[0.08] bg-white/70 text-[#3f3a33] shadow-lg shadow-black/[0.06] transition duration-200 ease-out hover:-translate-y-0.5 hover:bg-white active:scale-[0.96] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:shadow-black/20 dark:hover:bg-[#1e1a15]",
        visible ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-2 opacity-0",
      )}
    >
      <ArrowUp size={18} weight="bold" aria-hidden="true" />
    </button>
  );
}
