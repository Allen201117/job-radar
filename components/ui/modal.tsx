"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { useBodyScrollLock, useEscapeKey, useFocusTrap } from "@/lib/ui/hooks";

export type ModalProps = {
  open: boolean;
  onClose: () => void;
  /** 读屏用的对话框名字。没有可见标题时必填，否则读屏只会念「对话框」。 */
  ariaLabel?: string;
  /** 有可见标题时传标题元素的 id，优先于 ariaLabel。 */
  ariaLabelledBy?: string;
  /** 版式：center 居中弹窗（重提交）/ sheet 移动端底部抽屉 / drawer 右侧抽屉（详情浏览）。 */
  variant?: "center" | "sheet" | "drawer";
  /** 点遮罩是否关闭。提交进行中应传 false，避免误触丢失填写内容。 */
  closeOnBackdrop?: boolean;
  /** ESC 是否关闭。同上。 */
  closeOnEscape?: boolean;
  className?: string;
  /** 容器额外样式（遮罩层）。 */
  backdropClassName?: string;
  children: React.ReactNode;
};

/**
 * 模态层。全站 5 个弹层（CompanyInsightDrawer / SavedCompare / RegisterModal /
 * FeedbackButton / JobFilters 全屏筛选）此前各写各的，行为参差：
 *
 *   焦点陷阱     5 个全都没有 —— 键盘用户 Tab 能穿到被遮住的背景内容上，看不见光标在哪
 *   role/aria    RegisterModal 连 role="dialog" 和 aria-modal 都缺，读屏不当它是对话框
 *   锁滚动+ESC   逻辑一模一样地抄了 6 遍
 *
 * 本组件把这三件事做成默认行为。**它只改焦点与读屏语义，不改任何像素**——
 * 外观（圆角、暖白面、落影、进场动画）继续由传入的 className 与 globals.css 决定。
 */
export function Modal({
  open,
  onClose,
  ariaLabel,
  ariaLabelledBy,
  variant = "center",
  closeOnBackdrop = true,
  closeOnEscape = true,
  className,
  backdropClassName,
  children,
}: ModalProps) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  // portal 要等挂载后才有 document.body；SSR 阶段直接不渲染。
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  useBodyScrollLock(open);
  useEscapeKey(onClose, open && closeOnEscape);
  useFocusTrap(panelRef, open);

  if (!open || !mounted) return null;

  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-[120] flex",
        variant === "center" && "items-center justify-center p-4",
        variant === "sheet" && "items-end justify-center",
        variant === "drawer" && "items-stretch justify-end",
        backdropClassName,
      )}
    >
      {/*
        遮罩必须够深：此前用 bg-black/30，在暖纸浅底上几乎看不出来，背景看着还是亮的、
        像还能点，用户点上去才发现点到的是遮罩（线上实测反馈过）。
        aria-hidden + 非语义 div：它只是视觉遮挡，不该被读屏当成一个可交互元素念出来。
      */}
      <div
        aria-hidden="true"
        onClick={closeOnBackdrop ? onClose : undefined}
        className="absolute inset-0 bg-overlay backdrop-blur-[2px]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabelledBy ? undefined : ariaLabel}
        aria-labelledby={ariaLabelledBy}
        // tabIndex 让「面板里一个可聚焦元素都没有」时焦点仍能落在面板本身，
        // 不至于掉回 body 让键盘用户失去位置。
        tabIndex={-1}
        className={cn("relative outline-none", className)}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
