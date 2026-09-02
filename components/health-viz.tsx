import type { ReactNode } from "react";
import type { BandTone } from "@/lib/admin-health";
import { cn } from "@/lib/utils";

export type TrackerItem = {
  label: string;
  tone: BandTone;
};

export const HEALTH_STATUS_META: Record<BandTone, { label: string; symbol: string; badge: string; cell: string; stroke: string; fill: string }> = {
  success: {
    label: "正常",
    symbol: "●",
    badge: "bg-[#e6f0db] text-[#48642b] dark:bg-[#344622] dark:text-[#c4dd9d]",
    cell: "border-[#b9cea0] bg-[#dbe9c9] text-[#4f6e2d] dark:border-[#69884b] dark:bg-[#3e552c] dark:text-[#d5e8ae]",
    stroke: "stroke-[#6f9738] dark:stroke-[#a3d06a]",
    fill: "bg-[#6f9738] dark:bg-[#a3d06a]",
  },
  warning: {
    label: "关注",
    symbol: "◐",
    badge: "bg-[#f7ebd8] text-[#805e28] dark:bg-[#4a381e] dark:text-[#edc978]",
    cell: "border-[#dfbd82] bg-[#f5e5c9] text-[#876126] dark:border-[#9d7332] dark:bg-[#59431f] dark:text-[#f0ce7e]",
    stroke: "stroke-[#b88337] dark:stroke-[#dfb566]",
    fill: "bg-[#b88337] dark:bg-[#dfb566]",
  },
  danger: {
    label: "处理",
    symbol: "×",
    badge: "bg-[#f3e2dc] text-[#914d40] dark:bg-[#4d2923] dark:text-[#e7aaa0]",
    cell: "border-[#d6a39a] bg-[#efd8d1] text-[#944d40] dark:border-[#92594e] dark:bg-[#5b302a] dark:text-[#efb8ae]",
    stroke: "stroke-[#b4523f] dark:stroke-[#e6a99f]",
    fill: "bg-[#b4523f] dark:bg-[#e6a99f]",
  },
  muted: {
    label: "暂无数据",
    symbol: "·",
    badge: "bg-[#ece7dd] text-[#625c51] dark:bg-white/[0.08] dark:text-[#c5bbaa]",
    cell: "border-[#d6cfc2] bg-[#e9e4da] text-[#746d62] dark:border-white/[0.12] dark:bg-white/[0.08] dark:text-[#bfb5a5]",
    stroke: "stroke-[#cbc3b4] dark:stroke-white/20",
    fill: "bg-[#a59c8d] dark:bg-[#bfb5a5]",
  },
};

const RING_TRACK = "stroke-[#e7e0d3] dark:stroke-white/[0.08]";
const BAR_TRACK = "bg-black/[0.05] dark:bg-white/[0.07]";

function clampRatio(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(1, value));
}

export function StatusDot({ tone, className }: { tone: BandTone; className?: string }) {
  const meta = HEALTH_STATUS_META[tone];
  return (
    <span aria-hidden="true" className={cn("inline-grid size-3 shrink-0 place-items-center text-[10px] font-bold leading-none", tone === "muted" ? "text-[#746d62] dark:text-[#bfb5a5]" : tone === "success" ? "text-[#4f6e2d] dark:text-[#d5e8ae]" : tone === "warning" ? "text-[#876126] dark:text-[#f0ce7e]" : "text-[#944d40] dark:text-[#efb8ae]", className)}>{meta.symbol}</span>
  );
}

export function StatusBadge({ tone, label }: { tone: BandTone; label?: string }) {
  const meta = HEALTH_STATUS_META[tone];
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold", meta.badge)}><StatusDot tone={tone} />{label || meta.label}</span>;
}

export function KpiCard({
  title,
  value,
  tone = "muted",
  status,
  detail,
  footnote,
  href,
  className,
  weight = "soft",
}: {
  title: string;
  value: ReactNode;
  tone?: BandTone;
  status?: ReactNode;
  detail: ReactNode;
  footnote?: ReactNode;
  href?: string;
  className?: string;
  weight?: "strong" | "soft";
}) {
  const content = (
    <>
      <p className="text-xs font-medium text-[#625c51] dark:text-[#c5bbaa]">{title}</p>
      <div className="mt-2 min-h-10 text-[1.75rem] font-semibold leading-none tracking-[-0.035em] tabular-nums ink-1 ">{value}</div>
      <div className="mt-3 min-h-5">{status || <StatusBadge tone={tone} />}</div>
      <p className="mt-2 text-xs leading-5 ink-3">{detail}</p>
      {footnote && <p className="mt-4 border-t border-black/[0.06] pt-2 text-[10px] leading-4 ink-3 dark:border-white/[0.08] ">{footnote}</p>}
    </>
  );
  const cardClass = cn(
    weight === "strong" ? "surface ring-1 ring-black/[0.06] dark:ring-white/[0.10]" : "surface-soft",
    "relative flex min-h-[12.25rem] flex-col overflow-hidden p-4",
    href && "surface-hover focus-visible:outline-none",
    className,
  );
  const accent = weight === "strong" ? (
    <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-[2px]", HEALTH_STATUS_META[tone].fill)} />
  ) : null;
  return href
    ? <a href={href} className={cardClass}>{accent}{content}</a>
    : <article className={cardClass}>{accent}{content}</article>;
}

export function BarList({
  items,
  ariaLabel,
  className,
}: {
  items: Array<{
    key: string;
    label: string;
    value: ReactNode;
    ratio: number | null;
    tone?: BandTone;
    caption?: ReactNode;
    valueDetail?: ReactNode;
  }>;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div className={cn("divide-y divide-black/[0.06] overflow-hidden rounded-xl border border-black/[0.06] dark:divide-white/[0.08] dark:border-white/[0.08]", className)} role="list" aria-label={ariaLabel}>
      {items.map((item) => {
        const ratio = clampRatio(item.ratio);
        const tone = ratio == null ? "muted" : item.tone || "success";
        return (
          <div key={item.key} role="listitem" className="relative isolate grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 overflow-hidden px-3 py-2.5 sm:px-4">
            <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 -z-10 opacity-[0.28]", HEALTH_STATUS_META[tone].fill)} style={{ width: ratio == null ? "0%" : `${ratio * 100}%` }} />
            {/* 左沿状态条：覆盖率场景里「条越短 = 越糟」，只靠条长会让最该注意的行最不显眼。
                这一竖条宽度恒定、只由 tone 决定，给「差」一个与数值无关的强调通道。 */}
            <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", HEALTH_STATUS_META[tone].fill, tone === "muted" && "opacity-40")} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium ink-1 ">{item.label}</p>
              {item.caption && <p className="mt-0.5 truncate text-[11px] ink-3">{item.caption}</p>}
            </div>
            <div className="text-right tabular-nums text-sm font-semibold ink-2 ">
              {item.value}
              {item.valueDetail && <p className="mt-0.5 text-[11px] font-normal ink-3">{item.valueDetail}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Tracker({
  items,
  ariaLabel,
  className,
  columns = "grid-cols-10 sm:grid-cols-[repeat(30,minmax(0,1fr))]",
}: {
  items: TrackerItem[];
  ariaLabel: string;
  className?: string;
  columns?: string;
}) {
  return (
    <div className={className}>
      <div className={cn("grid gap-1.5", columns)} role="list" aria-label={ariaLabel}>
        {items.map((item, index) => {
          const meta = HEALTH_STATUS_META[item.tone];
          return <span key={`${item.label}-${index}`} role="img" title={item.label} aria-label={item.label} className={cn("grid aspect-square min-w-0 place-items-center rounded-[4px] border text-[9px] font-bold leading-none", meta.cell)}>{meta.symbol}</span>;
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] ink-3" aria-label="状态图例">
        {(Object.keys(HEALTH_STATUS_META) as BandTone[]).map((tone) => <span key={tone} className="inline-flex items-center gap-1"><StatusDot tone={tone} />{HEALTH_STATUS_META[tone].label}</span>)}
      </div>
    </div>
  );
}

export function StatRing({
  pct,
  tone,
  size = "section",
  target,
  children,
  className,
}: {
  pct: number | null;
  tone: BandTone;
  size?: "northstar" | "section";
  target?: number;
  children: ReactNode;
  className?: string;
}) {
  const value = clampRatio(pct);
  const targetValue = clampRatio(target);
  const dimensions = size === "northstar" ? { edge: 176, stroke: 14 } : { edge: 120, stroke: 11 };
  const radius = (dimensions.edge - dimensions.stroke) / 2;
  const center = dimensions.edge / 2;
  const circumference = 2 * Math.PI * radius;
  const visualTone = value == null ? "muted" : tone;
  const dash = value == null ? circumference : value * circumference;

  return (
    <div className={cn("relative grid shrink-0 place-items-center", className)} style={{ width: dimensions.edge, height: dimensions.edge }}>
      <svg aria-hidden="true" className="absolute inset-0" width={dimensions.edge} height={dimensions.edge} viewBox={`0 0 ${dimensions.edge} ${dimensions.edge}`}>
        <circle className={RING_TRACK} cx={center} cy={center} r={radius} fill="none" strokeWidth={dimensions.stroke} />
        <circle className={HEALTH_STATUS_META[visualTone].stroke} cx={center} cy={center} r={radius} fill="none" strokeWidth={dimensions.stroke} strokeLinecap="round" strokeDasharray={`${dash} ${circumference}`} transform={`rotate(-90 ${center} ${center})`} />
        {targetValue != null && <g transform={`rotate(${targetValue * 360} ${center} ${center})`}><line x1={center} y1={dimensions.stroke / 2 + 2} x2={center} y2={dimensions.stroke + 9} className="stroke-[#1a1714]/35 dark:stroke-white/50" strokeWidth="2" strokeLinecap="round" /></g>}
      </svg>
      <div className={cn("relative z-10 flex flex-col items-center justify-center text-center", size === "northstar" ? "max-w-[80%]" : "max-w-[74%]")}>{children}</div>
    </div>
  );
}

export function Callout({ tone = "muted", children, className }: { tone?: BandTone; children: ReactNode; className?: string }) {
  return <aside className={cn("flex items-start gap-2 rounded-xl border border-black/[0.07] bg-white/45 px-3.5 py-3 text-sm leading-5 ink-2 dark:border-white/[0.09] dark:bg-white/[0.04] ", className)}><StatusDot tone={tone} className="mt-1" /><p>{children}</p></aside>;
}
