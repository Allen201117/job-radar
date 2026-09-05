"use client";

// 行为层基于 Radix Tabs（MIT，Copyright (c) WorkOS）——见 LICENSES/。
import * as React from "react";
import * as RT from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export type TabItem = {
  value: string;
  label: React.ReactNode;
  /** 右侧计数徽标，如「值得投 12」。 */
  badge?: React.ReactNode;
  disabled?: boolean;
};

export type TabsProps = {
  items: readonly TabItem[];
  value: string;
  onChange: (value: string) => void;
  /** 读屏用：这组 tab 在切什么。必填。 */
  ariaLabel: string;
  className?: string;
  children?: React.ReactNode;
};

/**
 * 标签页。
 *
 * 为什么用 Radix：难点是**方向键导航**（左右键在 tab 间移动、Home/End 跳首尾、
 * 只有选中项进入 Tab 顺序，即 roving tabindex）。这套自己写很容易只做对一半。
 *
 * ⚠️ 选中态用「墨色下划线滑动」而不是整块变底色：这个产品一屏只允许一个墨色实心块
 * （那是主操作的信号），tab 用实心块会和主按钮抢「点我」的注意力。
 */
export function Tabs({ items, value, onChange, ariaLabel, className, children }: TabsProps) {
  return (
    <RT.Root value={value} onValueChange={onChange} className={className}>
      <RT.List
        aria-label={ariaLabel}
        className="relative flex items-center gap-1 overflow-x-auto border-b border-tone-neutral-border scrollbar-hide"
      >
        {items.map((item) => (
          <RT.Trigger
            key={item.value}
            value={item.value}
            disabled={item.disabled}
            className={cn(
              "press-feedback-subtle t-label relative -mb-px shrink-0 whitespace-nowrap px-3 py-2.5 outline-none",
              "border-b-2 border-transparent transition-colors",
              "hover:ink-1 focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2",
              "disabled:cursor-not-allowed disabled:opacity-40",
              "data-[state=active]:border-[var(--action-ink-bg)] data-[state=active]:ink-1",
            )}
            style={{
              transitionDuration: "var(--dur-toggle, 180ms)",
              transitionTimingFunction: "var(--spring-smooth, cubic-bezier(0.25, 0, 0, 1))",
            }}
          >
            {item.label}
            {item.badge != null ? <span className="t-num ml-1.5 ink-3">{item.badge}</span> : null}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}

export const TabPanel = RT.Content;
