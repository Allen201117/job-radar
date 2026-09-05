"use client";

import * as React from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type AlertDialogProps = {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  /** 说清**会发生什么**，不要只写「确定吗」。不可逆操作必须写明不可逆。 */
  description: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 破坏性操作：确认按钮变红，且默认焦点落在「取消」上。 */
  destructive?: boolean;
  /** 提交中：确认按钮转圈，且此时点遮罩/按 ESC 都不关（避免半路丢状态）。 */
  pending?: boolean;
  className?: string;
};

/**
 * 确认对话框。用来替掉 `window.confirm`。
 *
 * 为什么不能用原生 confirm：它阻塞主线程、样式完全不受控、移动端体验很差，
 * 而且文案只能是一行纯文本——说不清「这个操作会删掉什么、能不能撤销」。
 *
 * ⚠️ 破坏性操作的默认焦点放在「取消」上，不是「确认」。
 * 这样连按回车不会误删；想删的人多按一次 Tab，代价不对等才是对的。
 */
export function AlertDialog({
  open,
  onCancel,
  onConfirm,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  destructive,
  pending,
  className,
}: AlertDialogProps) {
  const cancelRef = React.useRef<HTMLButtonElement>(null);

  // 破坏性操作进场后把焦点挪到「取消」——Modal 的焦点陷阱默认聚焦第一个可聚焦元素，
  // 而 DOM 顺序里取消在前，所以这里只需在非破坏性时把焦点让给确认。
  React.useEffect(() => {
    if (open && destructive) cancelRef.current?.focus();
  }, [open, destructive]);

  return (
    <Modal
      open={open}
      onClose={pending ? () => {} : onCancel}
      ariaLabel={title}
      closeOnBackdrop={!pending}
      closeOnEscape={!pending}
      className={cn("surface w-full max-w-sm p-6", className)}
    >
      <h2 className="t-h3 ink-1">{title}</h2>
      <div className="t-body-sm ink-2 mt-2">{description}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button ref={cancelRef} variant="soft" size="sm" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button
          variant={destructive ? "soft" : "ink"}
          size="sm"
          loading={pending}
          onClick={() => void onConfirm()}
          className={destructive ? "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg" : undefined}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
