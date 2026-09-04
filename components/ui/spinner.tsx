import * as React from "react";
import { cn } from "@/lib/utils";

export type SpinnerProps = React.SVGAttributes<SVGSVGElement> & {
  /** 直径（px）。默认 16，跟现网最常见的 CircleNotch size={16} 一致。 */
  size?: number;
  /** 给读屏用的说明。装饰性场景（旁边已有「加载中」文字）传 null 即可。 */
  label?: string | null;
};

/**
 * 加载转圈。改造前 9 个文件各写各的 `<CircleNotch className="animate-spin">`。
 *
 * 两处刻意的设计：
 * - `motion-reduce:animate-none`：全站尊重 prefers-reduced-motion，转圈也不例外。
 * - 默认带 role="status" + 读屏文字：光转不说话的话，读屏用户只会觉得页面卡住了。
 */
export function Spinner({ size = 16, label = "加载中", className, ...rest }: SpinnerProps) {
  return (
    <>
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className={cn("animate-spin motion-reduce:animate-none", className)}
        {...rest}
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      {label ? (
        <span role="status" aria-live="polite" className="sr-only">
          {label}
        </span>
      ) : null}
    </>
  );
}
