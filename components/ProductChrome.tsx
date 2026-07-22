import type { ComponentType, ReactNode } from "react";
import { ArrowRight, Sparkle, WarningCircle } from "@phosphor-icons/react/ssr";
import { AnimatedStat } from "@/components/ui/animated-stat";
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
    <div className="bg-editorial grain relative min-h-screen text-[#1a1714] dark:text-[#f3ecdf]">
      <div className={cn("relative z-10 mx-auto w-full px-4 pb-16 pt-8 sm:px-6 lg:px-8", maxWidth)}>
        {children}
      </div>
    </div>
  );
}

export function ProductHero({
  eyebrow,
  title,
  titleClassName,
  description,
  icon: Icon = Sparkle,
  action,
  align = "end",
  children,
}: {
  eyebrow: string;
  title: string;
  titleClassName?: string;
  description?: string;
  icon?: IconComponent;
  action?: ReactNode;
  // 标题块与 action 在 lg 下的纵向对齐：默认 end（底对齐）；start = 标题上提（action 较高时更省空间）。
  align?: "start" | "center" | "end";
  children?: ReactNode;
}) {
  const alignClass = {
    start: "lg:items-start",
    center: "lg:items-center",
    end: "lg:items-end",
  }[align];
  return (
    // 页头改为「编辑部报头」式排版：不再套大卡片 + 四色径向渐变（那是本页最丑的部分），
    // 标题/说明这类导航性文字直接落在暖纸背景上，靠底部细分隔线收边；
    // 真正承载「数据」的部分（岗位库计数 / 指标卡）仍走卡片，从 action / children 传入。
    <section className="relative">
      <div className={cn("flex flex-col gap-5 lg:flex-row lg:justify-between lg:gap-8", alignClass)}>
        <div className="max-w-3xl">
          {/* 眉标：图标嵌入品牌天蓝小方块 + 克制的段首标签，比浮动的描边胶囊更像刻意的编辑部小节标 */}
          <div className="flex items-center gap-2.5">
            <span
              className="grid size-7 shrink-0 place-items-center rounded-[0.6rem] bg-[#e6eef8] text-[#3f7cc0] ring-1 ring-inset ring-[#3f7cc0]/[0.12] dark:bg-[#7fb2e8]/[0.14] dark:text-[#7fb2e8] dark:ring-[#7fb2e8]/20"
              aria-hidden="true"
            >
              <Icon size={15} weight="fill" />
            </span>
            <span className="text-[13px] font-semibold tracking-[0.01em] text-[#8a8275] dark:text-[#9a9184]">
              {eyebrow}
            </span>
          </div>
          <h1
            className={cn(
              "display-tight mt-4 text-balance text-[1.85rem] font-semibold leading-[1.18] text-[#1a1714] dark:text-[#f3ecdf] sm:text-[2.15rem] lg:text-[2.4rem]",
              titleClassName,
            )}
          >
            {title}
          </h1>
          {description && (
            <p className="mt-3 max-w-2xl text-pretty text-[15px] leading-7 text-[#5f594e] dark:text-[#b6ad9d]">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children && <div className="mt-6 sm:mt-7">{children}</div>}
      {/* 报头分隔线：细发丝线向右淡出，替代原大卡片的边界，给页头收个干净的底 */}
      <div
        aria-hidden="true"
        className="mt-6 h-px w-full bg-gradient-to-r from-black/[0.11] via-black/[0.05] to-transparent dark:from-white/[0.14] dark:via-white/[0.06] dark:to-transparent"
      />
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
    sky: "bg-[#dbe9fa] text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]",
    lime: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]",
    white: "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]",
    orange: "bg-[#fbe6d1] text-[#9a6326] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]",
    muted: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]",
  }[tone];

  return (
    // 移动端：横向紧凑（图标在左、数字+标签在右），少占竖向空间；sm+ 恢复竖向卡片。
    <div className="surface-soft bento-glow flex items-center gap-3 px-3.5 py-3 sm:flex-col sm:items-start sm:gap-0 sm:px-4 sm:py-4">
      <div className={cn("grid size-9 shrink-0 place-items-center rounded-xl", toneClass)}>
        <Icon size={19} weight="fill" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <div className="tabular-nums text-2xl font-semibold leading-none text-[#1a1714] dark:text-[#f3ecdf] sm:mt-5 sm:text-3xl">
          {/* 数字值翻动入场 / 实时翻动；非数字（如「私有」）原样展示 */}
          {typeof value === "number" ? <AnimatedStat value={value} /> : value}
        </div>
        <div className="mt-1 text-[12px] text-[#8a8275] dark:text-[#9a9184] sm:mt-2 sm:text-[13px]">{label}</div>
      </div>
    </div>
  );
}

export function CountBadge({ children }: { children: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-black/[0.07] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-4 py-2 text-[13px] font-medium text-[#5f594e] dark:text-[#b6ad9d]">
      {children}
    </div>
  );
}

export function EmptyPanel({
  title,
  description,
  action,
  tone,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  tone?: "empty" | "error";
}) {
  const resolvedTone = tone ?? "empty";

  return (
    <div
      className={cn(
        "rounded-[1.5rem] border px-6 py-14 text-center",
        resolvedTone === "error"
          ? "border-[#e7b7ac] bg-[#fff7f4] dark:border-[#e6a99f]/[0.25] dark:bg-[#3a201a]/[0.16]"
          : "border-dashed border-black/[0.12] bg-white/45 dark:border-white/[0.1] dark:bg-white/[0.05]",
      )}
    >
      <div
        className={cn(
          "mx-auto grid size-12 place-items-center rounded-2xl",
          resolvedTone === "error"
            ? "bg-[#f7e6e1] text-[#9c4a3c] dark:bg-[#3a201a] dark:text-[#e6a99f]"
            : "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]",
        )}
      >
        {resolvedTone === "error" ? (
          <WarningCircle size={22} weight="fill" aria-hidden="true" />
        ) : (
          <ArrowRight size={22} weight="bold" aria-hidden="true" />
        )}
      </div>
      <h2 className="mt-4 text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-[14px] leading-6 text-[#6b655a] dark:text-[#b6ad9d]">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
