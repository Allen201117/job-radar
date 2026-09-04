"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { useBodyScrollLock, useEscapeKey, useFocusTrap } from "@/lib/ui/hooks";

export type SheetProps = {
  open: boolean;
  onClose: () => void;
  ariaLabel: string;
  /** 面板最大高度，默认 88dvh。用 dvh 不用 vh：移动端地址栏收起时 vh 会算错。 */
  maxHeight?: string;
  className?: string;
  children: React.ReactNode;
};

/** 关闭判定：拖过这么远，或松手瞬间速度超过这个值。两者满足其一即关。 */
const DISMISS_DISTANCE_RATIO = 0.28; // 拖过面板高度的 28%
const DISMISS_VELOCITY = 0.5; // px/ms —— 快速下甩即使没拖多远也该关

/**
 * 底部抽屉（移动端主力弹层）。
 *
 * 这是本轮最贴近「iPhone 手感」的一个组件，关键不在样子，在三件事：
 *
 * 1. **拖拽跟手**：手指按住就跟着走，中途松手按「距离 + 速度」判定去留。
 *    只看距离是不够的——用户快速下甩时只拖了 40px 也期待它关掉；
 *    只看速度也不够——慢慢拖到底了却不关会很别扭。所以两个判据是「或」的关系。
 * 2. **橡皮筋阻尼**：往上拖（超出边界）时位移按 0.3 衰减，手感是「拉不动但有回应」，
 *    而不是纹丝不动（死板）或跟着跑（散架）。
 * 3. **只在内容滚到顶时才接管拖拽**：否则用户想滚内容却把整个面板拖走了。
 *    这一条是最容易漏的，漏了就会被抱怨「列表滚不了」。
 *
 * ⚠️ touch-action 必须精确声明：面板本身 pan-y（允许纵向滚动交给浏览器），
 * 把手区域 none（那一块完全归我们）。声明错了会出现「滚动和拖拽互相打架」。
 */
export function Sheet({ open, onClose, ariaLabel, maxHeight = "88dvh", className, children }: SheetProps) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = React.useState(false);
  const [drag, setDrag] = React.useState(0);
  const [dragging, setDragging] = React.useState(false);
  const start = React.useRef<{ y: number; t: number } | null>(null);
  const last = React.useRef<{ y: number; t: number } | null>(null);

  React.useEffect(() => setMounted(true), []);
  useBodyScrollLock(open);
  useEscapeKey(onClose, open);
  useFocusTrap(panelRef, open);

  // 关闭后把位移清零，否则下次打开会从上次拖到的位置开始。
  React.useEffect(() => {
    if (!open) {
      setDrag(0);
      setDragging(false);
    }
  }, [open]);

  const onPointerDown = (e: React.PointerEvent) => {
    // 内容没滚到顶时不接管：用户是想滚列表，不是想关面板。
    if ((scrollRef.current?.scrollTop ?? 0) > 0) return;
    start.current = { y: e.clientY, t: e.timeStamp };
    last.current = start.current;
    setDragging(true);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    const dy = e.clientY - start.current.y;
    last.current = { y: e.clientY, t: e.timeStamp };
    // 往上拖是越界方向：加阻尼，拉得动但明显在抗拒（橡皮筋）。
    setDrag(dy >= 0 ? dy : dy * 0.3);
  };

  const finishDrag = (e: React.PointerEvent) => {
    if (!start.current) return;
    const height = panelRef.current?.offsetHeight ?? 1;
    const dy = Math.max(0, e.clientY - start.current.y);
    // 用最后一小段的位移算瞬时速度，而不是全程平均——全程平均会把「先慢后快甩出去」算成慢。
    const dt = Math.max(1, e.timeStamp - (last.current?.t ?? e.timeStamp) || 16);
    const velocity = (e.clientY - (last.current?.y ?? e.clientY)) / dt;
    start.current = null;
    setDragging(false);
    if (dy > height * DISMISS_DISTANCE_RATIO || velocity > DISMISS_VELOCITY) {
      onClose();
    } else {
      setDrag(0); // 没到阈值 → 弹回原位
    }
  };

  if (!open || !mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-end justify-center">
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-overlay backdrop-blur-[2px] motion-safe:animate-in"
        style={{
          // 拖得越远遮罩越透明，给「正在离开」一个连续的视觉交代
          opacity: Math.max(0, 1 - drag / 320),
          animationDuration: "var(--dur-sheet, 450ms)",
        }}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        tabIndex={-1}
        className={cn(
          "relative w-full max-w-lg rounded-t-3xl bg-surface-panel shadow-2xl outline-none",
          "pb-[env(safe-area-inset-bottom)]",
          className,
        )}
        style={{
          maxHeight,
          transform: `translateY(${Math.max(0, drag)}px)`,
          // 拖拽中不要过渡（要跟手）；松手才用弹簧弹回或滑出。
          transition: dragging
            ? "none"
            : `transform var(--dur-sheet, 450ms) var(--spring-snappy, cubic-bezier(0.38, 1.21, 0.22, 1))`,
          touchAction: "pan-y",
        }}
      >
        {/* 把手：既是可拖区域，也是「这个能拖」的视觉暗示。iOS 上没有把手的抽屉用户不会去拖。 */}
        <div
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={finishDrag}
          onPointerCancel={finishDrag}
          className="flex cursor-grab touch-none justify-center py-3 active:cursor-grabbing"
        >
          <span aria-hidden="true" className="h-1 w-9 rounded-full bg-black/[0.18] dark:bg-white/[0.22]" />
        </div>
        <div ref={scrollRef} className="max-h-[inherit] overflow-y-auto overscroll-contain px-5 pb-6">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
