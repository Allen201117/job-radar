import * as React from "react";
import { cn } from "@/lib/utils";
import { buttonVariants, type ButtonVariantProps } from "@/lib/ui/variants";
import { Spinner } from "@/components/ui/spinner";

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  ButtonVariantProps & {
    /** 加载中：自动禁用 + 显示转圈，并对读屏播报 aria-busy。 */
    loading?: boolean;
    /** 文字左侧图标（Phosphor 图标直接传进来即可）。 */
    leading?: React.ReactNode;
    /** 文字右侧图标。 */
    trailing?: React.ReactNode;
  };

/**
 * 全站按钮。变体表见 lib/ui/variants.ts。
 *
 * variant: ink 主操作（一屏一个）/ soft 卡内次操作 / ghost 大号描边次操作 / quiet 纯文字退让操作
 * size:    xs / sm / md（默认）/ lg
 *
 * 不需要 <button> 语义的场景（比如把 <Link> 做成按钮样子）不要硬套本组件，
 * 直接 `className={buttonVariants({ variant, size })}` —— 这也是 shadcn/ui 的用法，
 * 比引一个 Slot 依赖来做 asChild 划算（现网只有 3 处这种链接按钮）。
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, block, loading, leading, trailing, children, disabled, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // 不写 type 的 <button> 在 <form> 里默认是 submit，会造成「点个次要按钮把表单交了」。
      type={type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(buttonVariants({ variant, size, block }), className)}
      {...rest}
    >
      {loading ? <Spinner className="h-[1em] w-[1em]" label={null} /> : leading}
      {children}
      {trailing}
    </button>
  );
});

export { buttonVariants };
