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
    <div className="bg-editorial grain relative min-h-screen ink-1">
      <div className={cn("relative z-10 mx-auto w-full px-4 pb-16 pt-8 sm:px-6 lg:px-8", maxWidth)}>
        {children}
      </div>
    </div>
  );
}

export function ProductHero({
  title,
  titleClassName,
  icon: Icon = Sparkle,
  action,
  align = "end",
  children,
}: {
  title: string;
  titleClassName?: string;
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
    // 标题直接落在暖纸背景上，靠底部细分隔线收边；
    // 真正承载「数据」的部分（岗位库计数 / 指标卡）仍走卡片，从 action / children 传入。
    //
    // ⚠️ 页头**只有一个页面名**：没有眉标、没有说明小字（2026-09-09 创始人拍板，照大厂做法改）。
    // 原来是三层：眉标「今日机会」+ 标题「今天值得处理的官方岗位」+ 一段说明小字。
    // 实测 BOSS直聘 / 智联招聘 / 猎聘的岗位列表页**连大标题都没有**，页面身份全靠导航项那
    // 两三个字承载（BOSS 列表页就一个「推荐」）；GitHub 的 PR 页 h1 是「Pull requests:
    // vercel/next.js」——名词 + 归属，同样没有说明句。所以这里收敛成一层：图标 + 页面名。
    // ⚠️ 页面名必须与导航项（lib/i18n.ts 的 DICT）逐字一致——点「值得投」进来看到「收藏」是割裂，
    // 这条由 tests/loading-copy.test.js 钉着。要把眉标 / 说明加回来先问创始人，别直接补 prop。
    <section className="relative">
      <div className={cn("flex flex-col gap-5 lg:flex-row lg:justify-between lg:gap-8", alignClass)}>
        {/* 图标与页面名同行：页面名短（多为 3-5 字），图标独占一行会让页头显得空。
            图标尺寸跟着标题走，别缩成脚注。 */}
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="grid size-10 shrink-0 place-items-center rounded-[0.7rem] bg-[#e6eef8] text-tone-sky-fg ring-1 ring-inset ring-[#3f7cc0]/[0.12] dark:bg-[#7fb2e8]/[0.14] dark:ring-[#7fb2e8]/20 sm:size-11"
            aria-hidden="true"
          >
            <Icon size={21} weight="fill" />
          </span>
          <h1
            className={cn(
              "display-tight min-w-0 text-balance text-[1.6rem] font-semibold leading-[1.2] ink-1 sm:text-[1.8rem]",
              titleClassName,
            )}
          >
            {title}
          </h1>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children && <div className="mt-5">{children}</div>}
      {/* 报头分隔线：细发丝线向右淡出，替代原大卡片的边界，给页头收个干净的底 */}
      <div
        aria-hidden="true"
        className="mt-5 h-px w-full bg-gradient-to-r from-black/[0.11] via-black/[0.05] to-transparent dark:from-white/[0.14] dark:via-white/[0.06] dark:to-transparent"
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
    muted: "bg-[#ece7dd] ink-2 dark:bg-white/[0.08]",
  }[tone];

  return (
    // 移动端：横向紧凑（图标在左、数字+标签在右），少占竖向空间；sm+ 恢复竖向卡片。
    <div className="surface-soft bento-glow flex items-center gap-3 px-3.5 py-3 sm:flex-col sm:items-start sm:gap-0 sm:px-4 sm:py-4">
      <div className={cn("grid size-9 shrink-0 place-items-center rounded-xl", toneClass)}>
        <Icon size={19} weight="fill" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <div className="tabular-nums text-2xl font-semibold leading-none ink-1 sm:mt-5 sm:text-3xl">
          {/* 数字值翻动入场 / 实时翻动；非数字（如「私有」）原样展示 */}
          {typeof value === "number" ? <AnimatedStat value={value} /> : value}
        </div>
        <div className="mt-1 text-[12px] ink-3 sm:mt-2 sm:text-[13px]">{label}</div>
      </div>
    </div>
  );
}

export function CountBadge({ children }: { children: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-black/[0.07] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-4 py-2 text-[13px] font-medium ink-2">
      {children}
    </div>
  );
}

// 空状态已收进组件库（components/ui/empty-state.tsx）。这里保留再导出，
// 是为了让 4 个存量调用方不必在同一次改动里跟着改 import 路径。
export { EmptyState as EmptyPanel } from "@/components/ui/empty-state";
