import type { ComponentType, ReactNode } from "react";
import { ArrowRight, Sparkle } from "@phosphor-icons/react/ssr";
import { cn } from "@/lib/utils";

type IconComponent = ComponentType<any>;

export function ProductPage({
  children,
  maxWidth = "max-w-6xl",
}: {
  children: ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="min-h-screen bg-[#08090c] text-white">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(56,189,248,0.18),transparent_32%),radial-gradient(circle_at_4%_20%,rgba(163,230,53,0.12),transparent_26%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_28%)]" />
      <div className="pointer-events-none fixed inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,0.9)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.9)_1px,transparent_1px)] [background-size:64px_64px]" />
      <div className={cn("relative mx-auto w-full px-4 pb-16 pt-8 sm:px-6 lg:px-8", maxWidth)}>
        {children}
      </div>
    </div>
  );
}

export function ProductHero({
  eyebrow,
  title,
  description,
  icon: Icon = Sparkle,
  action,
  children,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  icon?: IconComponent;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden rounded-[1.5rem] border border-white/10 bg-white/[0.06] px-5 py-7 shadow-2xl shadow-black/25 sm:px-7 lg:px-8">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_85%_15%,rgba(125,211,252,0.18),transparent_30%),radial-gradient(circle_at_10%_110%,rgba(190,242,100,0.12),transparent_32%)]" />
      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-sm font-medium text-white/72">
            <Icon size={16} weight="fill" className="text-sky-300" aria-hidden="true" />
            {eyebrow}
          </p>
          <h1 className="mt-4 text-balance text-3xl font-semibold leading-tight text-white sm:text-4xl lg:text-5xl">
            {title}
          </h1>
          {description && (
            <p className="mt-3 max-w-2xl text-pretty text-base leading-7 text-white/62">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      {children && <div className="relative mt-7">{children}</div>}
    </section>
  );
}

export function MetricTile({
  label,
  value,
  icon: Icon,
  tone = "sky",
}: {
  label: string;
  value: number | string;
  icon: IconComponent;
  tone?: "sky" | "lime" | "white" | "orange" | "muted";
}) {
  const toneClass = {
    sky: "bg-sky-300 text-sky-950",
    lime: "bg-lime-300 text-lime-950",
    white: "bg-white text-[#111217]",
    orange: "bg-orange-300 text-orange-950",
    muted: "bg-white/14 text-white",
  }[tone];

  return (
    <div className="rounded-[1.25rem] border border-white/10 bg-white/[0.07] px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className={cn("grid size-9 place-items-center rounded-xl", toneClass)}>
        <Icon size={19} weight="fill" aria-hidden="true" />
      </div>
      <div className="mt-5 tabular-nums text-3xl font-semibold leading-none text-white">
        {value}
      </div>
      <div className="mt-2 text-sm text-white/58">{label}</div>
    </div>
  );
}

export function CountBadge({ children }: { children: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white/76">
      {children}
    </div>
  );
}

export function EmptyPanel({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-white/14 bg-white/[0.05] px-6 py-14 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
      <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-white/10 text-sky-300">
        <ArrowRight size={22} weight="bold" aria-hidden="true" />
      </div>
      <h2 className="mt-4 text-lg font-semibold text-white">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-sm leading-6 text-white/56">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
