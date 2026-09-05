import * as React from "react";
import { cn } from "@/lib/utils";

export type ProgressProps = {
  /** 0-100。传 null 表示「在跑但不知道还要多久」，显示来回扫掠的不确定态。 */
  value: number | null;
  /** 读屏用：这条进度在说什么（「简历解析进度」而不是「进度」）。 */
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
};

/**
 * 进度条。
 *
 * ⚠️ 什么时候才该用它：**只有能给出真实百分比时**。给不出真实百分比却硬放一条进度条，
 * 是在骗用户——它走到 90% 卡住比转圈更伤信任。不确定时长的操作传 value=null，
 * 走不确定态（来回扫掠，只说明「在跑」，不承诺进度）。
 *
 * 判断标准（来自 NN/g 的等待反馈研究，也是 iOS 的做法）：
 *   < 300ms   什么都不显示（显示了反而制造「这很慢」的暗示）
 *   0.3s - 1s 转圈 Spinner
 *   1s - 10s  骨架屏（布局可预知时）或不确定态进度条
 *   > 10s     必须给真实百分比，否则用户会以为卡死了
 */
export function Progress({ value, ariaLabel, size = "md", className }: ProgressProps) {
  const indeterminate = value === null;
  const pct = indeterminate ? 0 : Math.max(0, Math.min(100, value));

  return (
    <div
      role="progressbar"
      aria-label={ariaLabel}
      aria-valuemin={indeterminate ? undefined : 0}
      aria-valuemax={indeterminate ? undefined : 100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      // 不确定态必须显式说明，否则读屏会念「进度 0%」，比不说更糟
      aria-valuetext={indeterminate ? "进行中，剩余时间未知" : undefined}
      className={cn(
        "relative w-full overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/[0.08]",
        size === "sm" ? "h-1" : "h-1.5",
        className,
      )}
    >
      {indeterminate ? (
        <div className="jr-scan absolute inset-y-0 w-1/3 rounded-full bg-action-ink" />
      ) : (
        <div
          className="h-full rounded-full bg-action-ink"
          style={{
            width: `${pct}%`,
            transitionProperty: "width",
            transitionDuration: "var(--dur-panel, 300ms)",
            transitionTimingFunction: "var(--spring-smooth, cubic-bezier(0.25, 0, 0, 1))",
          }}
        />
      )}
    </div>
  );
}
