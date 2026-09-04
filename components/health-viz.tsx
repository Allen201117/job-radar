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
    label: "要注意",
    symbol: "◐",
    badge: "bg-[#f7ebd8] text-[#805e28] dark:bg-[#4a381e] dark:text-[#edc978]",
    cell: "border-[#dfbd82] bg-[#f5e5c9] text-[#876126] dark:border-[#9d7332] dark:bg-[#59431f] dark:text-[#f0ce7e]",
    stroke: "stroke-[#b88337] dark:stroke-[#dfb566]",
    fill: "bg-[#b88337] dark:bg-[#dfb566]",
  },
  danger: {
    label: "得处理",
    symbol: "×",
    badge: "bg-[#f3e2dc] text-[#914d40] dark:bg-[#4d2923] dark:text-[#e7aaa0]",
    cell: "border-[#d6a39a] bg-[#efd8d1] text-[#944d40] dark:border-[#92594e] dark:bg-[#5b302a] dark:text-[#efb8ae]",
    stroke: "stroke-[#b4523f] dark:stroke-[#e6a99f]",
    fill: "bg-[#b4523f] dark:bg-[#e6a99f]",
  },
  muted: {
    label: "没有数据",
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
      <div className="mt-2 min-h-10 text-[1.75rem] font-semibold leading-none tracking-[-0.035em] tabular-nums ink-1">{value}</div>
      <div className="mt-3 min-h-5">{status || <StatusBadge tone={tone} />}</div>
      <p className="mt-2 text-xs leading-5 ink-3">{detail}</p>
      {footnote && <p className="mt-4 border-t border-black/[0.06] pt-2 text-[10px] leading-4 ink-3 dark:border-white/[0.08]">{footnote}</p>}
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
              <p className="truncate text-sm font-medium ink-1">{item.label}</p>
              {item.caption && <p className="mt-0.5 truncate text-[11px] ink-3">{item.caption}</p>}
            </div>
            <div className="text-right tabular-nums text-sm font-semibold ink-2">
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
  return <aside className={cn("flex items-start gap-2 rounded-xl border border-black/[0.07] bg-white/45 px-3.5 py-3 text-sm leading-5 ink-2 dark:border-white/[0.09] dark:bg-white/[0.04]", className)}><StatusDot tone={tone} className="mt-1" /><p>{children}</p></aside>;
}

// ── 以下三个原语为「用户行为」模块新增（2026-09-03） ──────────────────────
// 复用同一套 HEALTH_STATUS_META 配色与语义，不新造第二套视觉语言。

// SVG 的 fill/stroke 不吃 Tailwind 的 bg-* 类（那是 background-color）。
// 折线的面积填充走 currentColor，所以这里单独给一份**文字色**类，与 HEALTH_STATUS_META
// 的描边色同源，保证明暗两套主题下线与面同色。
const CHART_INK: Record<BandTone, string> = {
  success: "text-[#6f9738] dark:text-[#a3d06a]",
  warning: "text-[#b88337] dark:text-[#dfb566]",
  danger: "text-[#b4523f] dark:text-[#e6a99f]",
  muted: "text-[#a59c8d] dark:text-[#bfb5a5]",
};

// 折线趋势：每日活跃、回访曲线用。
// 为什么不用现成图表库：全站唯一依赖是 Tailwind + Phosphor，为一条折线引入 recharts
// 会给管理员页多打进上百 KB；这里的形状简单到纯 SVG 就够。
export function TrendLine({
  points,
  tone = "success",
  ariaLabel,
  height = 96,
  className,
  formatValue = (v: number) => String(v),
}: {
  points: Array<{ label: string; value: number }>;
  tone?: BandTone;
  ariaLabel: string;
  height?: number;
  className?: string;
  formatValue?: (value: number) => string;
}) {
  if (!points.length) {
    return <p className={cn("text-xs ink-3", className)}>暂无数据</p>;
  }
  const width = 600;
  const padY = 8;
  const max = Math.max(1, ...points.map((p) => p.value));
  const stepX = points.length > 1 ? width / (points.length - 1) : 0;
  const y = (v: number) => padY + (1 - v / max) * (height - padY * 2);
  const coords = points.map((p, i) => [points.length > 1 ? i * stepX : width / 2, y(p.value)] as const);
  const line = coords.map(([x, yy], i) => `${i === 0 ?"M":"L"}${x.toFixed(1)},${yy.toFixed(1)}`).join("");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${height} L${coords[0][0].toFixed(1)},${height} Z`;
  const meta = HEALTH_STATUS_META[tone];
  const last = points[points.length - 1];
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a), points[0]);

  return (
    <div className={className}>
      <svg
        role="img"
        aria-label={`${ariaLabel}：最新 ${last.label} ${formatValue(last.value)}，峰值 ${peak.label} ${formatValue(peak.value)}`}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-24 w-full"
      >
        <g className={CHART_INK[tone]}>
          <path d={area} fill="currentColor" className="opacity-[0.16]" />
          <path d={line} fill="none" className={meta.stroke} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {coords.map(([x, yy], i) => (
            <circle key={i} cx={x} cy={yy} r={points.length > 40 ? 0 : 2.5} fill="currentColor" />
          ))}
        </g>
      </svg>
      {/* 折线本身不带刻度：管理员要的是「趋势 + 最新值」，加满坐标轴反而挤。
          首尾标签 + 峰值三个锚点足够读出走向。 */}
      <div className="mt-1.5 flex items-center justify-between text-[10px] ink-3">
        <span>{points[0].label}</span>
        <span className="tabular-nums">峰值 {formatValue(peak.value)}</span>
        <span>{last.label}</span>
      </div>
    </div>
  );
}

// 漏斗：每级「到达人数」+ 级与级之间的流失注记。
// 刻意**不强制单调**：真实数据里确实存在「没设求职目标就直接逛岗位库」的人，
// 把后一级压到不超过前一级会把这种真行为抹平。后一级更多时显示为「多 N 人」并说明。
export function FunnelSteps({
  steps,
  baseline,
  ariaLabel,
  className,
}: {
  steps: Array<{ key: string; label: string; users: number; note?: string }>;
  baseline: number;
  ariaLabel: string;
  className?: string;
}) {
  const base = Math.max(1, baseline);
  return (
    <ol className={cn("space-y-0", className)} aria-label={ariaLabel}>
      {steps.map((step, index) => {
        const prev = index === 0 ? null : steps[index - 1];
        const delta = prev ? step.users - prev.users : 0;
        const pct = Math.round((step.users / base) * 100);
        const keepRate = prev && prev.users > 0 ? Math.round((step.users / prev.users) * 100) : null;
        const tone: BandTone = index === 0 ? "muted" : keepRate == null ? "muted" : keepRate >= 70 ? "success" : keepRate >= 40 ? "warning" : "danger";
        return (
          <li key={step.key}>
            {prev && (
              <div className="flex items-center gap-2 py-1 pl-3 text-[11px] ink-3">
                <span aria-hidden="true" className="h-4 w-px bg-black/[0.12] dark:bg-white/[0.16]" />
                {delta < 0
                  ? <span>掉了 <span className="font-semibold tabular-nums text-[#944d40] dark:text-[#efb8ae]">{Math.abs(delta)}</span> 人，留下 {keepRate}%</span>
                  : delta > 0
                    ? <span>比上一步多 <span className="font-semibold tabular-nums">{delta}</span> 人（有人跳过了上一步）</span>
                    : <span>没有流失</span>}
              </div>
            )}
            <div className="relative isolate overflow-hidden rounded-xl border border-black/[0.06] dark:border-white/[0.08]">
              <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 -z-10 opacity-[0.26]", HEALTH_STATUS_META[tone].fill)} style={{ width: `${Math.max(2, pct)}%` }} />
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3.5 py-3">
                <div className="min-w-0">
                  <p className="t-body-sm font-semibold ink-1">{step.label}</p>
                  {step.note && <p className="mt-0.5 truncate text-[11px] ink-3">{step.note}</p>}
                </div>
                <div className="text-right">
                  <span className="text-xl font-semibold tabular-nums ink-1">{step.users}</span>
                  <span className="ml-1 text-[11px] ink-3 tabular-nums">人 · {pct}%</span>
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// 章节锚点小卡：顶部一排「一个数 + 一句话」，点击滚到对应章节。
// 与 KpiCard 的区别：这个是导航件，必须矮、必须一屏排得下，所以不带状态徽标与脚注。
export function JumpTile({
  label,
  value,
  hint,
  href,
  tone = "muted",
}: {
  label: string;
  value: ReactNode;
  hint: string;
  href: string;
  tone?: BandTone;
}) {
  return (
    <a href={href} className="surface-soft surface-hover relative flex flex-col overflow-hidden p-4 focus-visible:outline-none">
      <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-[2px]", HEALTH_STATUS_META[tone].fill)} />
      <p className="text-xs font-medium text-[#625c51] dark:text-[#c5bbaa]">{label}</p>
      <div className="mt-1.5 text-[1.6rem] font-semibold leading-none tracking-[-0.035em] tabular-nums ink-1">{value}</div>
      <p className="mt-2 text-[11px] leading-4 ink-3">{hint}</p>
    </a>
  );
}
