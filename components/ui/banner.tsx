import * as React from "react";
import { cn } from "@/lib/utils";
import { bannerVariants, type BannerVariantProps } from "@/lib/ui/variants";

export type BannerProps = React.HTMLAttributes<HTMLDivElement> &
  BannerVariantProps & {
    /** 左侧图标。 */
    icon?: React.ReactNode;
    /**
     * 读屏播报强度。报错用 assertive（打断当前朗读立刻播报），
     * 一般提示用 polite（等读屏说完当前内容再播）。传 null 关闭播报（纯静态说明文字）。
     */
    live?: "polite" | "assertive" | null;
  };

/**
 * 整块提示条：表单报错、能力不可用说明、结果反馈。
 *
 * 改造前这套红色样式（border #e0b4ac / bg #f7e6e1 / text #9c4a3c + 一整套暗色）在
 * RegisterModal、ResumeProfilePanel、AddSourceForm、InsightSubmitForm、SourceTable、
 * PreferenceForm 六个文件里被逐字复制，其中只有 RegisterModal 抽成了局部组件（且未导出）。
 *
 * 默认 tone="rose"（报错是它最常见的用途）；提示类显式传 tone="sky"/"amber"。
 */
export const Banner = React.forwardRef<HTMLDivElement, BannerProps>(function Banner(
  { className, tone, size, icon, live = "polite", children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role={live === "assertive" ? "alert" : live ? "status" : undefined}
      aria-live={live ?? undefined}
      className={cn(bannerVariants({ tone, size }), icon ? "flex items-start gap-2" : "", className)}
      {...rest}
    >
      {icon ? <span className="mt-0.5 shrink-0">{icon}</span> : null}
      <div className="min-w-0">{children}</div>
    </div>
  );
});

export { bannerVariants };
