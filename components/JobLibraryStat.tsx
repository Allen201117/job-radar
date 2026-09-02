"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowsClockwise } from "@phosphor-icons/react";
import { AnimateNumber } from "@/components/ui/animated-blur-number";
import { AnimatedStat } from "@/components/ui/animated-stat";
import { createJobStatsRefresher, installVisiblePolling } from "@/lib/job-stats-refresh";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 60_000;

// 岗位库数据条（报头 dateline 形态）。
//
// 为什么从「右侧竖卡」改成「标题下的横条」：旧形态是一张 280×200 的卡片浮在报头右边，
// 三个问题——① 它把筛选器整体压到 y≈550，1440×900 视口里一条岗位都看不到（走查实测）；
// ② 卡里的大数字 40px 比页面 H1 的 32px 还大，视觉权重倒置，用户第一眼落在计数上而不是
// 页面标题上；③ surface 卡里又嵌两张 surface-soft 小卡，「卡中卡」层级冗余。
// 横条把 ~200px 垂直空间压到 ~52px，数字降到 22px（明确小于 H1），三组数据平级用细竖线分隔。
//
// 文案同时去黑话（走查里普通求职者看不懂的词）：
//   「有效在招」→「在招岗位」、「官方源」→「家企业官方源」、「24h 确认在招」→「24 小时内核验有效」；
//   「轮询间隔 60s」「首屏服务端计数」是内部实现细节，对求职者零信息量，直接删。
//
// 真数据仍走 /api/jobs/stats（有效在招 / 24h 核验读自建香港 jobs 库，官方源读 Supabase）；
// 首屏不闪：initialTotal 由服务端 SSR 传入，挂载即有真实值。
interface Props {
  initialTotal: number;
}

interface JobStats {
  validActive?: number;
  sources?: number;
  recent24h?: number;
}

async function fetchJobStats(): Promise<JobStats> {
  const resp = await fetch("/api/jobs/stats");
  const data = await resp.json();
  if (!resp.ok || !data?.ok) throw new Error("stats_failed");
  return data;
}

export default function JobLibraryStat({ initialTotal }: Props) {
  const [activeJobs, setActiveJobs] = useState(0);
  const [sources, setSources] = useState<number | null>(null);
  const [recent, setRecent] = useState<number | null>(null);
  const [status, setStatus] = useState<"live" | "syncing" | "stale">("live");
  const [syncedAt, setSyncedAt] = useState<Date | null>(null);
  const refreshRef = useRef<() => Promise<void>>(() => Promise.resolve());

  // 入场翻动：下一帧把 0 推到 SSR 已知的真实总数。
  useEffect(() => {
    const id = requestAnimationFrame(() => setActiveJobs(initialTotal));
    return () => cancelAnimationFrame(id);
  }, [initialTotal]);

  useEffect(() => {
    const refresher = createJobStatsRefresher({
      fetchStats: fetchJobStats,
      onStart: () => setStatus("syncing"),
      onSuccess: (data) => {
        if (typeof data.validActive === "number") setActiveJobs(data.validActive);
        if (typeof data.sources === "number") setSources(data.sources);
        if (typeof data.recent24h === "number") setRecent(data.recent24h);
        setSyncedAt(new Date());
        setStatus("live");
      },
      onError: () => setStatus("stale"),
    });
    refreshRef.current = refresher.refresh;
    const cleanupPolling = installVisiblePolling({
      documentLike: document,
      windowLike: window,
      refresh: refresher.refresh,
      intervalMs: POLL_INTERVAL_MS,
    });

    return () => {
      cleanupPolling();
      refresher.dispose();
      if (refreshRef.current === refresher.refresh) {
        refreshRef.current = () => Promise.resolve();
      }
    };
  }, []);

  // 只说人话：已同步过就报「几点几分更新」，没同步过就报机制「每分钟更新」。
  // ⚠️ 不许写「实时」——这个数是 60s 轮询来的，自称实时是骗用户；
  // 旧文案「轮询间隔 60s」诚实但是黑话（走查实测求职者看不懂），所以换成「每分钟更新」：
  // 既保住「这是定时刷新、不是实时」的诚实底线，又不用技术词。契约由 ux-hardening-contract 守。
  const syncLabel = syncedAt
    ? `${syncedAt.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })} 更新`
    : `每分钟更新`;
  const statusText = status === "stale" ? "连接暂不可用" : status === "syncing" ? "更新中" : syncLabel;

  return (
    <section
      className="flex flex-wrap items-center gap-x-1 gap-y-2 rounded-2xl border border-black/[0.07] bg-white/55 px-4 py-2.5 dark:border-white/[0.09] dark:bg-white/[0.04]"
      aria-label="岗位库概况"
      title={`每 ${POLL_INTERVAL_MS / 1000} 秒自动更新`}
    >
      <StatCell
        value={activeJobs}
        unit="个"
        label="在招岗位"
        primary
        animated
      />
      <Divider />
      <StatCell value={sources} unit="家" label="企业官方源" />
      <Divider />
      <StatCell value={recent} unit="个" label="24 小时内核验有效" />

      {/* 状态与刷新推到最右：它是「元信息」，不该和三组业务数字抢注意力 */}
      <div className="ml-auto flex items-center gap-2 pl-3">
        <span
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            status === "stale"
              ? "bg-[#d08a4a]"
              : status === "syncing"
                ? "animate-pulse bg-[#3f7cc0]"
                : "bg-[#3fae6a]",
          )}
          aria-hidden="true"
        />
        <span className="t-caption whitespace-nowrap">{statusText}</span>
        <button
          type="button"
          onClick={() => void refreshRef.current()}
          className="grid size-7 shrink-0 place-items-center rounded-full border border-black/[0.08] bg-white/70 ink-2 transition duration-200 hover:bg-white active:scale-[0.94] dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-[#1e1a15]"
          aria-label="立即刷新岗位库计数"
        >
          <ArrowsClockwise
            size={13}
            weight="bold"
            className={cn(status === "syncing" && "animate-spin")}
            aria-hidden="true"
          />
        </button>
      </div>
    </section>
  );
}

// 一格数据：数字在前、单位与标签紧随，横向排列扫读最快。
// primary 那格略大（22px）但明确小于页面 H1（≈38px），避免旧版「数字比标题还大」的权重倒置。
function StatCell({
  value,
  unit,
  label,
  primary = false,
  animated = false,
}: {
  value: number | null;
  unit: string;
  label: string;
  primary?: boolean;
  animated?: boolean;
}) {
  const numberClass = cn(
    "t-num font-semibold ink-1",
    primary ? "text-[1.375rem] leading-none" : "text-[0.9375rem] leading-none",
  );
  return (
    <div className="flex items-baseline gap-1.5 px-2">
      {value === null ? (
        <span className={cn(numberClass, "ink-4")}>—</span>
      ) : animated ? (
        <AnimateNumber value={value} duration={700} blur={14} className={numberClass} />
      ) : (
        <span className={numberClass}>
          <AnimatedStat value={value} />
        </span>
      )}
      {/* 单位与标签之间留一个细间隔：直接相连会渲染成「个24 小时内核验有效」，数字和文案糊成一团 */}
      <span className="t-caption whitespace-nowrap">
        {unit}
        <span className="pl-1">{label}</span>
      </span>
    </div>
  );
}

function Divider() {
  return (
    <span
      aria-hidden="true"
      className="hidden h-4 w-px shrink-0 bg-black/[0.09] dark:bg-white/[0.12] sm:block"
    />
  );
}
