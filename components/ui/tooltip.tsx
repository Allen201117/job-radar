"use client";

// 行为层基于 Radix Tooltip（MIT，Copyright (c) WorkOS）——见 LICENSES/。
// 只用它的定位/延迟/触发逻辑，视觉全部换成本产品的暖色皮肤。
import * as React from "react";
import * as RT from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

export type TooltipProps = {
  /** 提示内容。一句话，别放长段落——长内容该用 Popover 或直接写在页面上。 */
  content: React.ReactNode;
  children: React.ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  /** 悬停多久才出现。默认 300ms：太快会在鼠标划过时乱闪，太慢又像没反应。 */
  delayMs?: number;
  className?: string;
};

/**
 * 悬浮提示。
 *
 * 为什么用 Radix 而不自己写：难点不在样式，在**定位与触发**——
 * 贴近屏幕边缘时要自动翻转方向、要区分鼠标悬停与键盘聚焦两套触发、
 * 触屏上不能用 hover（没有 hover）而要长按。这三件事自己写必然漏掉其中一件。
 *
 * ⚠️ tooltip 里的信息**不能是唯一出处**：触屏用户很难触发它，读屏用户在某些模式下也读不到。
 * 关键信息必须写在页面上，tooltip 只做补充说明。
 */
export function Tooltip({ content, children, side = "top", delayMs = 300, className }: TooltipProps) {
  return (
    <RT.Provider delayDuration={delayMs} skipDelayDuration={200}>
      <RT.Root>
        <RT.Trigger asChild>{children}</RT.Trigger>
        <RT.Portal>
          <RT.Content
            side={side}
            sideOffset={6}
            collisionPadding={8}
            className={cn(
              "t-caption z-[140] max-w-[16rem] rounded-xl border border-black/[0.08] bg-action-ink px-2.5 py-1.5 text-action-ink-fg shadow-lg",
              "dark:border-white/[0.1]",
              // 进场用 snappy：干脆出现，不拖泥带水。data-state 由 Radix 给。
              "data-[state=delayed-open]:animate-in data-[state=closed]:animate-out",
              "motion-reduce:animate-none",
              className,
            )}
            style={{
              animationDuration: "var(--dur-toggle, 180ms)",
              animationTimingFunction: "var(--spring-snappy, cubic-bezier(0.38, 1.21, 0.22, 1))",
            }}
          >
            {content}
            <RT.Arrow className="fill-[var(--action-ink-bg)]" width={10} height={5} />
          </RT.Content>
        </RT.Portal>
      </RT.Root>
    </RT.Provider>
  );
}
