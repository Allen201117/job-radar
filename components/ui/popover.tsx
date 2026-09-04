"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import {
  useAnchoredPosition,
  useClickOutside,
  useEscapeKey,
  type AnchorAlign,
} from "@/lib/ui/hooks";

export type PopoverProps = {
  open: boolean;
  onClose: () => void;
  /** 触发按钮的 ref：既用来算位置，也用来豁免「点外部关闭」。 */
  anchorRef: React.RefObject<HTMLElement | null>;
  align?: AnchorAlign;
  /** 与触发元素的垂直间距（px）。 */
  gap?: number;
  /** 弹层宽度跟随触发元素（下拉筛选常用）。 */
  matchAnchorWidth?: boolean;
  ariaLabel?: string;
  className?: string;
  children: React.ReactNode;
};

/**
 * 锚定浮层（筛选下拉、菜单）。收编自 JobFilters 里那个唯一写对的实现。
 *
 * ⚠️ 三条不能退回去的规矩，每条都是线上踩过的：
 *
 * 1. **必须 portal 到 body，不能 absolute 在触发元素的容器里。**
 *    筛选条内层是 overflow-x-auto（移动端要横滑），而滚动容器**两个轴都裁剪** ——
 *    400 多 px 高的弹层会被裁进 42px 高的条里：DOM 里查得到、屏幕上什么都不出现，
 *    用户只会得出「这些按钮点不了」的结论。
 *
 * 2. **scroll 监听必须用 capture。** 祖先容器的滚动不冒泡到 window，不捕获就跟不上位置。
 *
 * 3. **「点外部关闭」必须豁免触发按钮自己。** 触发按钮本来就不在弹层里，不豁免的话点它
 *    会先被判成「点了外面」而关闭、紧接着的 click 又把它开回来 —— 净效果是这颗按钮永远关不掉。
 */
export function Popover({
  open,
  onClose,
  anchorRef,
  align = "start",
  gap = 8,
  matchAnchorWidth = false,
  ariaLabel,
  className,
  children,
}: PopoverProps) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const position = useAnchoredPosition(anchorRef, open, { align, gap });
  useEscapeKey(onClose, open);
  useClickOutside(panelRef, onClose, open, anchorRef);

  if (!open || !mounted || !position) return null;

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label={ariaLabel}
      style={{
        position: "fixed",
        top: position.top,
        left: position.left,
        width: matchAnchorWidth ? position.width : undefined,
        transform:
          align === "end" ? "translateX(-100%)" : align === "center" ? "translateX(-50%)" : undefined,
      }}
      className={cn("z-[130]", className)}
    >
      {children}
    </div>,
    document.body,
  );
}
