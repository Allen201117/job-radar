import * as React from "react";
import { Check } from "@phosphor-icons/react/ssr";
import { cn } from "@/lib/utils";

export type Step = {
  key: string;
  label: React.ReactNode;
  /** 该步的补充信息，如日期。 */
  meta?: React.ReactNode;
};

export type StepperProps = {
  steps: readonly Step[];
  /** 当前进行到第几步（0 起）。等于 steps.length 表示全部走完。 */
  current: number;
  ariaLabel: string;
  orientation?: "horizontal" | "vertical";
  className?: string;
};

/**
 * 步骤条。产品里对应「投递进展」：笔试 → 面试 → offer → 已结束。
 *
 * ⚠️ 用 `<ol>` 而不是一堆 div：步骤天然有顺序，读屏会念「列表，共 4 项，第 2 项」，
 * 这正是用户需要知道的。当前步加 `aria-current="step"`。
 *
 * ⚠️ 已完成的步骤用对勾而不是只变颜色：颜色是唯一区分手段时，色觉障碍用户读不出来
 * （WCAG 1.4.1 不能只用颜色传达信息）。
 */
export function Stepper({
  steps,
  current,
  ariaLabel,
  orientation = "horizontal",
  className,
}: StepperProps) {
  return (
    <ol
      aria-label={ariaLabel}
      className={cn(
        "flex",
        orientation === "horizontal" ? "items-start gap-2" : "flex-col gap-3",
        className,
      )}
    >
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={step.key}
            aria-current={active ? "step" : undefined}
            className={cn(
              "flex min-w-0 gap-2",
              orientation === "horizontal" ? "flex-1 flex-col items-center text-center" : "items-start",
            )}
          >
            <span className={cn("flex items-center gap-2", orientation === "horizontal" && "w-full")}>
              {orientation === "horizontal" && i > 0 ? (
                <span
                  aria-hidden="true"
                  className={cn("h-px flex-1", done || active ? "bg-action-ink" : "bg-tone-neutral-border")}
                />
              ) : null}
              <span
                aria-hidden="true"
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-full border text-[0.6875rem] font-semibold",
                  done && "border-transparent bg-action-ink text-action-ink-fg",
                  active && "border-[var(--action-ink-bg)] ink-1",
                  !done && !active && "border-tone-neutral-border ink-4",
                )}
                style={{
                  transitionProperty: "background-color, border-color, color",
                  transitionDuration: "var(--dur-toggle, 180ms)",
                  transitionTimingFunction: "var(--spring-smooth, cubic-bezier(0.25, 0, 0, 1))",
                }}
              >
                {done ? <Check size={13} weight="bold" /> : i + 1}
              </span>
              {orientation === "horizontal" && i < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={cn("h-px flex-1", done ? "bg-action-ink" : "bg-tone-neutral-border")}
                />
              ) : null}
            </span>
            <span className="min-w-0">
              <span className={cn("t-label block truncate", (done || active) && "ink-1")}>
                {step.label}
              </span>
              {step.meta ? <span className="t-caption block">{step.meta}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
