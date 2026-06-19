"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowsClockwise,
  Broadcast,
  ClockCounterClockwise,
} from "@phosphor-icons/react";
import { AnimateNumber } from "@/components/ui/animated-blur-number";
import { AnimatedStat } from "@/components/ui/animated-stat";
import { cn } from "@/lib/utils";

// 岗位库「实时翻动」总数卡（暖光浅色版）。
// - 真数据：走服务端 /api/jobs/stats，有效在招 + 24h 确认在招读自建香港 jobs 库（Phase 1 真实源），
//   官方源 = count(sources enabled)。取代旧的「浏览器直连 Supabase」——jobs 迁香港库后 Supabase 已是空表，
//   客户端直连会读到空/失活计数，与 SSR 真实总数对不上。
// - 实时：入场从 0 翻到 SSR 已知的真实总数（无需等网络），之后每 12s 轮询一次，数字变化即翻动。
// - 首屏不闪：initialTotal 由服务端 SSR 传入，挂载即有真实值。
interface Props {
  initialTotal: number;
}

export default function JobLibraryStat({ initialTotal }: Props) {
  const [activeJobs, setActiveJobs] = useState(0);
  const [sources, setSources] = useState<number | null>(null);
  const [recent, setRecent] = useState<number | null>(null);
  const [status, setStatus] = useState<"live" | "syncing" | "stale">("live");
  const [syncedAt, setSyncedAt] = useState<Date | null>(null);

  // 入场翻动：下一帧把 0 推到 SSR 已知的真实总数。
  useEffect(() => {
    const id = requestAnimationFrame(() => setActiveJobs(initialTotal));
    return () => cancelAnimationFrame(id);
  }, [initialTotal]);

  const refresh = useCallback(async () => {
    setStatus("syncing");
    try {
      // 服务端聚合：有效在招 / 24h 确认在招读香港 jobs 库，官方源读 Supabase（见 /api/jobs/stats）。
      const resp = await fetch("/api/jobs/stats", { cache: "no-store" });
      const data = await resp.json();
      if (!resp.ok || !data?.ok) throw new Error("stats_failed");
      if (typeof data.validActive === "number") setActiveJobs(data.validActive);
      if (typeof data.sources === "number") setSources(data.sources);
      if (typeof data.recent24h === "number") setRecent(data.recent24h);
      setSyncedAt(new Date());
      setStatus("live");
    } catch {
      setStatus("stale");
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 12000);
    return () => window.clearInterval(iv);
  }, [refresh]);

  const syncLabel = syncedAt
    ? `${syncedAt.toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      })} 已同步`
    : "首屏服务端计数";

  const statusText =
    status === "stale" ? "连接暂不可用" : status === "syncing" ? "正在刷新" : "实时刷新";

  return (
    <section className="surface bento-glow relative overflow-hidden p-3.5 text-[#1a1714] dark:text-[#f3ecdf] sm:p-4">
      <div
        className="pointer-events-none absolute -right-12 -top-16 size-40 rounded-full bg-[#96b6e2]/20 blur-3xl"
        aria-hidden="true"
      />
      <div className="relative flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="chip">
            <span
              className={cn(
                "size-2 rounded-full",
                status === "stale"
                  ? "bg-[#d08a4a]"
                  : status === "syncing"
                    ? "animate-pulse bg-[#3f7cc0]"
                    : "bg-[#3fae6a]",
              )}
              aria-hidden="true"
            />
            {statusText}
          </div>
          <p className="mt-2 text-[12px] text-[#8a8275] dark:text-[#9a9184]">岗位库 · 有效在招</p>
          <div className="mt-0.5 flex items-baseline gap-1.5">
            <AnimateNumber
              value={activeJobs}
              duration={700}
              blur={14}
              className="text-[1.8rem] font-semibold leading-none tracking-[-0.03em] text-[#1a1714] dark:text-[#f3ecdf] sm:text-[2.05rem]"
            />
            <span className="text-sm font-medium text-[#9a9184] dark:text-[#837c70]">个</span>
          </div>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="grid size-9 shrink-0 place-items-center rounded-full border border-black/[0.08] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] text-[#3f3a33] dark:text-[#d9d0c2] transition duration-200 hover:-translate-y-0.5 hover:bg-white dark:hover:bg-[#1e1a15] active:scale-[0.96]"
          aria-label="立即刷新岗位库计数"
        >
          <ArrowsClockwise
            size={16}
            weight="bold"
            className={cn(status === "syncing" && "animate-spin")}
            aria-hidden="true"
          />
        </button>
      </div>

      <div className="relative mt-3 grid grid-cols-2 gap-2">
        <SubStat icon={Broadcast} label="官方源" value={sources} />
        <SubStat icon={ClockCounterClockwise} label="24h 确认在招" value={recent} />
      </div>

      <div className="relative mt-2.5 flex items-center justify-between gap-3 border-t border-black/[0.06] dark:border-white/[0.1] pt-2.5">
        <p className="text-[11px] leading-5 text-[#9a9184] dark:text-[#837c70]">{syncLabel}</p>
        <p className="text-[11px] font-medium text-[#3f7cc0] dark:text-[#7fb2e8]">轮询间隔 12s</p>
      </div>
    </section>
  );
}

function SubStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Broadcast;
  label: string;
  value: number | null;
}) {
  return (
    <div className="surface-soft bento-glow px-3 py-2.5">
      <Icon size={15} weight="fill" className="text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
      <p className="mt-1.5 text-[11px] text-[#9a9184] dark:text-[#837c70]">{label}</p>
      <p className="mt-0.5 text-base font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
        {value === null ? <span className="text-[#c4bdb0] dark:text-[#6f685e]">—</span> : <AnimatedStat value={value} />}
      </p>
    </div>
  );
}
