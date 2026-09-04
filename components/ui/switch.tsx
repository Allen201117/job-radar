"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export type SwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** 读屏用的名字。有可见 label 时传 labelledBy 代替。 */
  ariaLabel?: string;
  ariaLabelledBy?: string;
  disabled?: boolean;
  /** 切换中（等服务端确认）：显示忙碌态且不可再点，避免连点产生竞态。 */
  busy?: boolean;
  size?: "sm" | "md";
  className?: string;
};

const TRACK = {
  sm: "h-[22px] w-[38px]",
  md: "h-[28px] w-[48px]",
};
const KNOB = {
  sm: "size-[18px]",
  md: "size-[24px]",
};
const TRAVEL = {
  sm: "translate-x-[16px]",
  md: "translate-x-[20px]",
};

/**
 * 开关。全站 13 个文件手写过 toggle，形态和无障碍都不一致。
 *
 * 为什么自己写而不用 Radix：Radix Switch 只提供状态与 aria，视觉与动效仍要自己做，
 * 而这个组件的价值恰恰在动效（见下），所以引依赖没有收益。
 *
 * ⚠️ iOS 手感的关键在**滑块按下时会横向拉长**（像被推着走的橡皮），松手才回圆。
 * 只做位移不做形变，就是「Web 味」的开关。这里用 :active 时加宽滑块 + snappy 弹簧实现。
 * 轨道颜色用 smooth（不回弹）——颜色回弹会显得轻浮；滑块位移用 snappy（微回弹）才跟手。
 */
export function Switch({
  checked,
  onChange,
  ariaLabel,
  ariaLabelledBy,
  disabled,
  busy,
  size = "md",
  className,
}: SwitchProps) {
  const locked = disabled || busy;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabelledBy ? undefined : ariaLabel}
      aria-labelledby={ariaLabelledBy}
      aria-busy={busy || undefined}
      disabled={locked}
      onClick={() => onChange(!checked)}
      className={cn(
        "group relative inline-flex shrink-0 items-center rounded-full border p-[2px] outline-none",
        "focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        TRACK[size],
        checked
          ? "border-transparent bg-action-ink"
          : "border-black/[0.08] bg-black/[0.06] dark:border-white/[0.1] dark:bg-white/[0.08]",
        className,
      )}
      style={{
        transitionProperty: "background-color, border-color",
        transitionDuration: "var(--dur-toggle, 180ms)",
        transitionTimingFunction: "var(--spring-smooth, cubic-bezier(0.25, 0, 0, 1))",
      }}
    >
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none rounded-full shadow-sm",
          // 滑块颜色跟着轨道走：开态用轨道的反色（--action-ink-fg 明暗两套都自动成立），
          // 关态用 --switch-knob-off。写死白色会在暗色下变成「白滑块躺在米白轨道上」。
          checked ? "bg-action-ink-fg" : "bg-switch-knob",
          // 按下时横向拉长——这是 iOS 开关最标志性的细节，只位移不形变就没有那个「被推着走」的感觉
          "group-active:w-[calc(100%_*_0.62)] motion-reduce:group-active:w-auto",
          KNOB[size],
          checked ? TRAVEL[size] : "translate-x-0",
        )}
        style={{
          transitionProperty: "transform, width",
          transitionDuration: "var(--dur-toggle, 180ms)",
          transitionTimingFunction: "var(--spring-snappy, cubic-bezier(0.38, 1.21, 0.22, 1))",
        }}
      />
    </button>
  );
}
