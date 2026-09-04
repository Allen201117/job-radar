"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * 表单字段外壳：标签 + 控件 + 说明 + 错误，并把三者用 aria 正确串起来。
 *
 * 改造前四个表单各写各的：AddSourceForm 有个没导出的局部 Field（唯一带字段级错误的），
 * ResumeProfilePanel 内联 label 套 input，RegisterModal 手写 htmlFor/id 配对，
 * InsightSubmitForm 用 <label> 包裹但只有整块 Banner 报错。
 * 更直接的证据：`inputCls` 这个样式字符串在 AddSourceForm 和 InsightSubmitForm 里**值完全一样**。
 *
 * 这里统一的是**可访问性接线**，不是外观：错误文案要通过 aria-describedby 关联到控件，
 * 否则读屏用户听不到「这一栏为什么红了」。外观仍然由 globals.css 的 .field-soft 提供。
 */

const FieldContext = React.createContext<{
  controlId: string;
  describedBy?: string;
  invalid: boolean;
} | null>(null);

export type FieldProps = {
  label?: React.ReactNode;
  /** 字段说明，出现在控件下方、错误上方。 */
  hint?: React.ReactNode;
  /** 有值即视为出错：控件描红 + aria-invalid + 读屏播报。 */
  error?: string | null;
  /** 标签后加必填星号（仅视觉提示，真正的必填靠控件的 required）。 */
  required?: boolean;
  /** 自定义控件 id；不传则自动生成。 */
  htmlFor?: string;
  className?: string;
  children: React.ReactNode;
};

export function Field({
  label,
  hint,
  error,
  required,
  htmlFor,
  className,
  children,
}: FieldProps) {
  const auto = React.useId();
  const controlId = htmlFor ?? `field-${auto}`;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <FieldContext.Provider value={{ controlId, describedBy, invalid: Boolean(error) }}>
      <div className={cn("space-y-1.5", className)}>
        {label ? (
          <label htmlFor={controlId} className="t-label block">
            {label}
            {required ? (
              <span className="text-tone-rose-fg" aria-hidden="true">
                {" *"}
              </span>
            ) : null}
          </label>
        ) : null}
        {children}
        {hint ? (
          <p id={hintId} className="t-caption">
            {hint}
          </p>
        ) : null}
        {error ? (
          <p id={errorId} role="alert" className="t-caption text-tone-rose-fg">
            {error}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  );
}

/** 控件从 Field 拿 id / aria 接线；不在 Field 里也能单独用（此时不接线）。 */
type AriaWiring = {
  id?: string;
  "aria-describedby"?: string;
  // React 的 aria-invalid 还接受 "grammar" | "spelling"，用 React 自己的类型别写窄。
  "aria-invalid"?: React.AriaAttributes["aria-invalid"];
};

function useFieldWiring(props: AriaWiring) {
  const ctx = React.useContext(FieldContext);
  return {
    id: props.id ?? ctx?.controlId,
    "aria-describedby": props["aria-describedby"] ?? ctx?.describedBy,
    "aria-invalid": props["aria-invalid"] ?? (ctx?.invalid ? true : undefined),
    invalid: Boolean(ctx?.invalid),
  };
}

/** 出错时的描红。只加边框色，不动尺寸——避免报错时布局跳动。 */
const INVALID_RING = "border-tone-rose-border focus:border-tone-rose-fg";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref,
) {
  const wiring = useFieldWiring(rest);
  return (
    <input
      ref={ref}
      {...rest}
      id={wiring.id}
      aria-describedby={wiring["aria-describedby"]}
      aria-invalid={wiring["aria-invalid"]}
      className={cn("field-soft", wiring.invalid && INVALID_RING, className)}
    />
  );
});

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, ...rest },
  ref,
) {
  const wiring = useFieldWiring(rest);
  return (
    <textarea
      ref={ref}
      {...rest}
      id={wiring.id}
      aria-describedby={wiring["aria-describedby"]}
      aria-invalid={wiring["aria-invalid"]}
      className={cn("field-soft", wiring.invalid && INVALID_RING, className)}
    />
  );
});

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  const wiring = useFieldWiring(rest);
  return (
    <select
      ref={ref}
      {...rest}
      id={wiring.id}
      aria-describedby={wiring["aria-describedby"]}
      aria-invalid={wiring["aria-invalid"]}
      className={cn("field-soft", wiring.invalid && INVALID_RING, className)}
    >
      {children}
    </select>
  );
});
