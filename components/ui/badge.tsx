import * as React from "react";
import { cn } from "@/lib/utils";
import { badgeVariants, type BadgeVariantProps } from "@/lib/ui/variants";

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> &
  BadgeVariantProps & {
    /** 文字左侧的小图标 / 圆点。 */
    icon?: React.ReactNode;
  };

/**
 * 状态与维度小标签。
 *
 * 收编的是改造前散在各处的 chip：其中 `CHIP_TONE` 这张配色表在 SavedCompare.tsx 与
 * CompanyInsightDrawer.tsx 里被**逐字复制了两份**（连键名都一样，只换了变量名），
 * 典型的「改一处漏一处」在等着发生。现在颜色统一走 --tone-* 变量。
 *
 * tone 语义（沿用现网，别自己发明新含义）：
 *   sky 社招 · green 校招/已核实 · amber 实习/转陈 · teal 招聘动态 ·
 *   rose 失败/风险 · lilac 职业洞察 · neutral 不表态
 */
export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, tone, size, icon, children, ...rest },
  ref,
) {
  return (
    <span ref={ref} className={cn(badgeVariants({ tone, size }), className)} {...rest}>
      {icon}
      {children}
    </span>
  );
});

export { badgeVariants };
