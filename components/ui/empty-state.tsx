import * as React from "react";
import { ArrowRight, WarningCircle } from "@phosphor-icons/react/ssr";
import { cn } from "@/lib/utils";

export type EmptyStateProps = {
  /** 一句话说清「这里为什么是空的」。 */
  title: string;
  /** 告诉用户下一步能做什么，而不是复述「暂无数据」。 */
  description: string;
  /** 主操作（最多一个，别并排放两个同等权重的按钮）。 */
  action?: React.ReactNode;
  /** empty = 还没有内容（虚线框）；error = 出错了（红调实框）。 */
  tone?: "empty" | "error";
  /** 覆盖默认图标。不传则 empty 用箭头、error 用警告圈。 */
  icon?: React.ReactNode;
  /** 次要出口，通常是一个文字链接。 */
  secondaryAction?: React.ReactNode;
  className?: string;
};

/**
 * 空状态 / 出错状态。
 *
 * ⚠️ 这个组件是**从 components/ProductChrome.tsx 的 EmptyPanel 原样搬过来的**，不是新写的。
 * 建组件库时我先自己写了一版，之后才发现产品里早有一个更好、且已被 4 个页面采纳的实现
 * ——组件库的职责是**吸收已经跑通的东西**，不是另起炉灶跟它并存。所以渲染结果一字不差保留，
 * 只把 icon / secondaryAction 作为可选参数加上（不传时行为与原来完全相同）。
 *
 * 产品要求（CLAUDE.md「trust through copy and state」）：空状态必须解释**真实原因**
 * 和**下一步动作**，不能只写「暂无数据」——后者等于把用户丢在原地。
 * 所以 title 与 description 都是必填。
 */
export function EmptyState({
  title,
  description,
  action,
  tone,
  icon,
  secondaryAction,
  className,
}: EmptyStateProps) {
  const resolvedTone = tone ?? "empty";

  return (
    <div
      className={cn(
        "rounded-[1.5rem] border px-6 py-14 text-center",
        resolvedTone === "error"
          ? "border-tone-rose-border-soft bg-tone-rose-bg-soft"
          : "border-dashed border-black/[0.12] bg-white/45 dark:border-white/[0.1] dark:bg-white/[0.05]",
        className,
      )}
    >
      <div
        className={cn(
          "mx-auto grid size-12 place-items-center rounded-2xl",
          resolvedTone === "error"
            ? "bg-tone-rose-bg text-tone-rose-fg"
            : "bg-action-ink text-action-ink-fg",
        )}
      >
        {icon ??
          (resolvedTone === "error" ? (
            <WarningCircle size={22} weight="fill" aria-hidden="true" />
          ) : (
            <ArrowRight size={22} weight="bold" aria-hidden="true" />
          ))}
      </div>
      <h2 className="mt-4 text-lg font-semibold ink-1">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-[14px] leading-6 ink-2">{description}</p>
      {action && <div className="mt-5">{action}</div>}
      {secondaryAction && <div className="t-label mt-3">{secondaryAction}</div>}
    </div>
  );
}

/**
 * @deprecated 改名为 `EmptyState`（对齐业界叫法），从 `@/components/ui` 导入。
 * 这个别名只是为了让存量调用方不必在同一次改动里全部跟着改，新代码不要再用。
 */
export const EmptyPanel = EmptyState;
