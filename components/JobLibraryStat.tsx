"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowsClockwise,
  Broadcast,
  ClockCounterClockwise,
} from "@phosphor-icons/react";
import { createBrowserClient } from "@/lib/supabaseClient";
import { AnimateNumber } from "@/components/ui/animated-blur-number";
import { AnimatedStat } from "@/components/ui/animated-stat";
import { cn } from "@/lib/utils";

// 岗位库「实时翻动」总数卡（暖光浅色版）。
// - 真数据：主数 = count_valid_active_jobs() RPC（有效在招 = active + 有 JD 正文，杜绝薄卡/失活虚高）；
//   官方源 = count(sources enabled)；24h 确认在招 = count(active 且 last_seen 24h 内)（RLS：所有人可读，匿名也行）。
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
    const supabase = createBrowserClient();
    const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    try {
      const [jobs, src, rec] = await Promise.all([
        // 「有效在招」(active + 有 JD 正文)，非裸 count(active)（含薄卡/失活会虚高）。
        supabase.rpc("count_valid_active_jobs"),
        supabase.from("sources").select("id", { count: "exact", head: true }).eq("enabled", true),
        supabase
          .from("jobs")
          .select("id", { count: "exact", head: true })
          .eq("status", "active")
          .gte("last_seen_at", dayAgo),
      ]);
      if (jobs.error || src.error || rec.error) throw jobs.error || src.error || rec.error;
      if (typeof jobs.data === "number") setActiveJobs(jobs.data);
      if (typeof src.count === "number") setSources(src.count);
      if (typeof rec.count === "number") setRecent(rec.count);
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
    <section className="surface bento-glow relative overflow-hidden p-4 text-[#1a1714] dark:text-[#f3ecdf] sm:p-5">
      <div
        className="pointer-events-none absolute -right-16 -top-20 size-52 rounded-full bg-[#96b6e2]/20 blur-3xl"
        aria-hidden="true"
      />
      <div className="relative flex items-start justify-between gap-4">
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
          <p className="mt-3 text-[13px] text-[#8a8275] dark:text-[#9a9184]">岗位库 · 有效在招</p>
          <div className="mt-1 flex items-baseline gap-2">
            <AnimateNumber
              value={activeJobs}
              duration={700}
              blur={14}
              className="text-[2.1rem] font-semibold leading-none tracking-[-0.03em] text-[#1a1714] dark:text-[#f3ecdf] sm:text-[2.5rem]"
            />
            <span className="pb-0.5 text-base font-medium text-[#9a9184] dark:text-[#837c70]">个</span>
          </div>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="grid size-10 shrink-0 place-items-center rounded-full border border-black/[0.08] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] text-[#3f3a33] dark:text-[#d9d0c2] transition duration-200 hover:-translate-y-0.5 hover:bg-white dark:hover:bg-[#1e1a15] active:scale-[0.96]"
          aria-label="立即刷新岗位库计数"
        >
          <ArrowsClockwise
            size={18}
            weight="bold"
            className={cn(status === "syncing" && "animate-spin")}
            aria-hidden="true"
          />
        </button>
      </div>

      <div className="relative mt-4 grid grid-cols-2 gap-2.5">
        <SubStat icon={Broadcast} label="官方源" value={sources} />
        <SubStat icon={ClockCounterClockwise} label="24h 确认在招" value={recent} />
      </div>

      <div className="relative mt-3.5 flex items-center justify-between gap-3 border-t border-black/[0.06] dark:border-white/[0.1] pt-3">
        <p className="text-xs leading-5 text-[#9a9184] dark:text-[#837c70]">{syncLabel}</p>
        <p className="text-xs font-medium text-[#3f7cc0] dark:text-[#7fb2e8]">轮询间隔 12s</p>
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
    <div className="surface-soft bento-glow px-3.5 py-3">
      <Icon size={16} weight="fill" className="text-[#3f7cc0] dark:text-[#7fb2e8]" aria-hidden="true" />
      <p className="mt-2 text-[11px] text-[#9a9184] dark:text-[#837c70]">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">
        {value === null ? <span className="text-[#c4bdb0] dark:text-[#6f685e]">—</span> : <AnimatedStat value={value} />}
      </p>
    </div>
  );
}
