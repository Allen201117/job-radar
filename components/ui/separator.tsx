import * as React from "react";
import { cn } from "@/lib/utils";

export type SeparatorProps = {
  orientation?: "horizontal" | "vertical";
  /**
   * 纯装饰（两侧内容本来就分得清）→ true，对读屏隐藏。
   * 真的用来划分语义分组 → false，读屏会念一声「分隔符」。默认 true：
   * 绝大多数分隔线是装饰，把它们都念出来只会制造噪音。
   */
  decorative?: boolean;
  className?: string;
};

/**
 * 分隔线。全站 25 处手写 `border-t border-black/[0.08]` 之类，透明度有 5 种取值。
 * 这里统一到 neutral 令牌，深浅一次改全站。
 */
export function Separator({
  orientation = "horizontal",
  decorative = true,
  className,
}: SeparatorProps) {
  return (
    <div
      role={decorative ? "none" : "separator"}
      aria-orientation={decorative ? undefined : orientation}
      className={cn(
        "shrink-0 bg-tone-neutral-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
    />
  );
}
