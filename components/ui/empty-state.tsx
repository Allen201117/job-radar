import * as React from "react";
import { cn } from "@/lib/utils";

export type EmptyStateProps = {
  /** 顶部图标 / 插画。 */
  icon?: React.ReactNode;
  /** 一句话说清「这里为什么是空的」。 */
  title: React.ReactNode;
  /** 补充说明：告诉用户下一步能做什么，而不是复述「暂无数据」。 */
  description?: React.ReactNode;
  /** 主操作（最多一个，别并排放两个同等权重的按钮）。 */
  action?: React.ReactNode;
  /** 次要出口，通常是一个文字链接。 */
  secondaryAction?: React.ReactNode;
  className?: string;
};

/**
 * 空状态。改造前 17 个文件各写各的「暂无 / 还没有」。
 *
 * 产品要求（CLAUDE.md「trust through copy and state」）：空状态必须解释**真实原因**
 * 和**下一步动作**，不能只写「暂无数据」——后者等于把用户丢在原地。
 * 所以 title 必填、description 与 action 强烈建议给。
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? <div className="ink-4">{icon}</div> : null}
      <p className="t-h3 ink-1">{title}</p>
      {description ? <p className="t-body-sm ink-3 max-w-md">{description}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
      {secondaryAction ? <div className="t-label">{secondaryAction}</div> : null}
    </div>
  );
}
