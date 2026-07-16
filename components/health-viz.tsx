import type { ReactNode } from "react";
import type { BandTone } from "@/lib/admin-health";
import { cn } from "@/lib/utils";

export const RING_STROKE: Record<BandTone, string> = {
  success: "stroke-[#6f9738] dark:stroke-[#a3d06a]",
  warning: "stroke-[#c78d3c] dark:stroke-[#e0b15a]",
  danger: "stroke-[#b4523f] dark:stroke-[#e6a99f]",
  muted: "stroke-[#cbc3b4] dark:stroke-white/20",
};

export const RING_TRACK = "stroke-[#e7e0d3] dark:stroke-white/[0.08]";

export const BAR_FILL: Record<BandTone, string> = {
  success: "bg-[#7fa844] dark:bg-[#a3d06a]",
  warning: "bg-[#d09a45] dark:bg-[#e0b15a]",
  danger: "bg-[#c15f4b] dark:bg-[#e6a99f]",
  muted: "bg-[#cfc7b8] dark:bg-white/20",
};

export const BAR_TRACK = "bg-black/[0.06] dark:bg-white/[0.08]";

export const CELL_BG: Record<BandTone, string> = {
  success: "bg-[#e6f2d3] dark:bg-[#a3d06a]/25",
  warning: "bg-[#fbecd7] dark:bg-[#825d28]/45",
  danger: "bg-[#f7e6e1] dark:bg-[#7a392e]/45",
  muted: "bg-[#ece7dd] dark:bg-white/[0.08]",
};

function clampRatio(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(1, value));
}

export function StatRing({
  pct,
  tone,
  size = 132,
  stroke = 12,
  target,
  children,
  className,
}: {
  pct: number | null;
  tone: BandTone;
  size?: number;
  stroke?: number;
  target?: number;
  children: ReactNode;
  className?: string;
}) {
  const value = clampRatio(pct);
  const targetValue = clampRatio(target);
  const radius = (size - stroke) / 2;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;
  const visualTone = value == null ? "muted" : tone;
  const dash = value == null ? circumference : value * circumference;

  return (
    <div className={cn("relative grid shrink-0 place-items-center", className)} style={{ width: size, height: size }}>
      <svg
        aria-hidden="true"
        className="absolute inset-0"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
      >
        <circle
          className={RING_TRACK}
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={stroke}
        />
        <circle
          className={RING_STROKE[visualTone]}
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
        {targetValue != null && (
          <g transform={`rotate(${targetValue * 360} ${center} ${center})`}>
            <line
              x1={center}
              y1={stroke / 2 + 2}
              x2={center}
              y2={stroke + 9}
              className="stroke-[#1a1714]/35 dark:stroke-white/50"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </g>
        )}
      </svg>
      <div className="relative z-10 flex max-w-[74%] flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

export function MiniBar({
  pct,
  tone,
  className,
}: {
  pct: number | null;
  tone: BandTone;
  className?: string;
}) {
  const value = clampRatio(pct);

  return (
    <div className={cn("h-2.5 overflow-hidden rounded-full", BAR_TRACK, className)} aria-hidden="true">
      {value != null && (
        <div
          className={cn("h-full rounded-full", BAR_FILL[tone])}
          style={{ width: `${value * 100}%` }}
        />
      )}
    </div>
  );
}

export function StackedBar({
  segments,
  total,
  className,
}: {
  segments: Array<{ value: number; tone: BandTone }>;
  total: number;
  className?: string;
}) {
  const safeTotal = total > 0 ? total : 0;

  return (
    <div className={cn("flex h-2.5 overflow-hidden rounded-full", BAR_TRACK, className)} aria-hidden="true">
      {safeTotal > 0 &&
        segments
          .filter((segment) => segment.value > 0)
          .map((segment, index) => (
            <div
              key={`${segment.tone}-${index}`}
              className={cn("h-full border-r-2 border-[#f7f1e6] last:border-r-0 dark:border-[#16130f]", BAR_FILL[segment.tone])}
              style={{
                width: `${Math.max(0, Math.min(100, (segment.value / safeTotal) * 100))}%`,
                minWidth: segment.value > 0 ? 3 : undefined,
              }}
            />
          ))}
    </div>
  );
}

export function CoverageGrid({
  cells,
  className,
}: {
  cells: Array<{ tone: BandTone; label: string }>;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-10 gap-2", className)} role="list" aria-label="必投清单逐家公司状态">
      {cells.map((cell, index) => (
        <div
          key={`${cell.label}-${index}`}
          role="img"
          title={cell.label}
          aria-label={cell.label}
          className={cn("aspect-square rounded-[6px] border border-black/[0.04] dark:border-white/[0.06]", CELL_BG[cell.tone])}
        />
      ))}
    </div>
  );
}

export function StatusDot({ tone, className }: { tone: BandTone; className?: string }) {
  return <span aria-hidden="true" className={cn("inline-block size-2.5 shrink-0 rounded-full", BAR_FILL[tone], className)} />;
}

export function FunnelBars({
  steps,
}: {
  steps: Array<{ label: string; value: number | null | undefined }>;
}) {
  const max = Math.max(0, ...steps.map((step) => (typeof step.value === "number" ? step.value : 0)));
  return (
    <div className="space-y-3" role="list" aria-label="用户漏斗">
      {steps.map((step, index) => {
        const previous = index > 0 ? steps[index - 1]?.value : null;
        const conversion = typeof step.value === "number" && typeof previous === "number" && previous > 0
          ? `${((step.value / previous) * 100).toFixed(1)}%`
          : null;
        return (
          <div key={step.label} role="listitem" className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-3">
            <div><p className="text-sm font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{step.label}</p>{index > 0 && <p className="text-[11px] text-[#8a8275] dark:text-[#9a9184]">{conversion ? `转化 ${conversion}` : "—"}</p>}</div>
            <div className={cn("h-7 overflow-hidden rounded-full", BAR_TRACK)}>
              {typeof step.value === "number" && max > 0 && <div className={cn("h-full rounded-full", index === 0 ? BAR_FILL.muted : BAR_FILL.success)} style={{ width: `${(step.value / max) * 100}%` }} />}
            </div>
            <p className="min-w-10 text-right text-sm font-semibold tabular-nums text-[#1a1714] dark:text-[#f3ecdf]">{typeof step.value === "number" ? step.value.toLocaleString("zh-CN") : "—"}</p>
          </div>
        );
      })}
    </div>
  );
}
