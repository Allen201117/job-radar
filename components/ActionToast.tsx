"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export type ActionToastData = {
  /** 每次 show 递增，用来重置自动消失的计时器（同一句文案连点两次也要重新计时） */
  id: number;
  text: string;
  tone?: "default" | "error";
  actionLabel?: string;
  onAction?: () => void;
};

/**
 * 就地操作的轻量反馈：底部胶囊，不遮挡、不阻断，1.8s 自动消失。
 *
 * 与 SaveToast 的分工（改这块前先看 CLAUDE.md「点击反馈分档」）：
 * - SaveToast = 低频重提交（保存画像 / 保存偏好 / AI 解析 / 提交表单），居中 + 转圈 + 打勾，用户要等结果。
 * - ActionToast = 高频就地操作（收藏 / 忽略 / 投递 / 复制 / 关注），结果已经写在按钮上了，
 *   这里只补一句「确实生效了」，所以绝不能挡住内容、也不能等它。
 */
export default function ActionToast({
  toast,
  onDismiss,
  duration = 1800,
}: {
  toast: ActionToastData | null;
  onDismiss: () => void;
  duration?: number;
}) {
  useEffect(() => {
    if (!toast) return;
    // 带操作（如「撤销」）的多留一会儿，否则用户还没伸手就没了。
    const ms = toast.onAction ? Math.max(duration, 4000) : duration;
    const t = window.setTimeout(onDismiss, ms);
    return () => window.clearTimeout(t);
  }, [toast, duration, onDismiss]);

  if (!toast) return null;

  return (
    <div className="above-mobile-nav pointer-events-none fixed inset-x-0 z-[110] flex justify-center px-4">
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "action-toast-pop t-body-sm pointer-events-auto flex items-center gap-3 rounded-full border px-4 py-2.5 shadow-lg",
          toast.tone === "error"
            ? "border-[#e0b4ac] bg-[#f7e6e1] text-[#9c4a3c] dark:border-[#7a392e]/[0.6] dark:bg-[#3a201a] dark:text-[#e6a99f]"
            : "border-black/[0.1] bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]",
        )}
      >
        <span>{toast.text}</span>
        {toast.actionLabel && toast.onAction && (
          <button
            type="button"
            onClick={toast.onAction}
            className="t-label underline underline-offset-2 hover:opacity-80"
          >
            {toast.actionLabel}
          </button>
        )}
      </div>
    </div>
  );
}

/** 岗位卡三个主动作的反馈文案（/jobs /saved /campus 共用一份，别各写各的）。 */
export function jobActionToastText(action: "saved" | "applied" | "ignored" | null, ok: boolean) {
  if (!ok) return "操作失败，已恢复原状态";
  if (action === "saved") return "已加入值得投";
  if (action === "applied") return "已标记投递";
  if (action === "ignored") return "已忽略，不再推荐";
  return "已撤销";
}

/** 配套状态：show(文案) 即可，自增 id 让连点也能重新计时。 */
export function useActionToast() {
  const [toast, setToast] = useState<ActionToastData | null>(null);
  const seq = useRef(0);

  const show = useCallback((data: Omit<ActionToastData, "id">) => {
    seq.current += 1;
    setToast({ ...data, id: seq.current });
  }, []);

  const dismiss = useCallback(() => setToast(null), []);

  return { toast, show, dismiss };
}
