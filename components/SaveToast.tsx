"use client";

import { useEffect } from "react";
import { CheckCircle, CircleNotch, XCircle } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export type SaveState = "idle" | "saving" | "done" | "error";

/**
 * 统一的「保存中 / 已保存 / 失败」弹窗卡片（带入场 + 对勾弹动）。
 * 个人主页 / 求职偏好等个性化保存共用：saving 显示转圈，done/error 弹一下后自动消失。
 */
export default function SaveToast({
  state,
  savingText = "保存中…",
  doneText = "已保存",
  errorText = "保存失败",
  onDismiss,
}: {
  state: SaveState;
  savingText?: string;
  doneText?: string;
  errorText?: string;
  onDismiss: () => void;
}) {
  useEffect(() => {
    if (state === "done" || state === "error") {
      const t = window.setTimeout(onDismiss, state === "done" ? 1300 : 2400);
      return () => window.clearTimeout(t);
    }
  }, [state, onDismiss]);

  if (state === "idle") return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-[120] grid place-items-center px-4">
      {/* 保存中给一层极淡遮罩聚焦（不阻断点击，按钮本身已禁用防重复提交） */}
      {state === "saving" && (
        <div className="absolute inset-0 bg-black/[0.06] backdrop-blur-[1px] dark:bg-black/30" aria-hidden="true" />
      )}
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "save-pop pointer-events-auto relative flex min-w-[190px] max-w-[320px] flex-col items-center gap-3 rounded-2xl border px-8 py-6 text-center",
          "border-black/[0.06] bg-white shadow-[0_30px_70px_-30px_rgba(40,34,28,0.55)] dark:border-white/[0.1] dark:bg-[#1e1a15] dark:shadow-[0_30px_70px_-30px_rgba(0,0,0,0.7)]",
        )}
      >
        {state === "saving" && (
          <>
            <CircleNotch size={30} weight="bold" className="animate-spin text-[#1a1714] dark:text-[#f3ecdf]" aria-hidden="true" />
            <p className="text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">{savingText}</p>
          </>
        )}
        {state === "done" && (
          <>
            <span className="save-check grid size-11 place-items-center rounded-full bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
              <CheckCircle size={26} weight="fill" aria-hidden="true" />
            </span>
            <p className="text-base font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{doneText}</p>
          </>
        )}
        {state === "error" && (
          <>
            <span className="save-check grid size-11 place-items-center rounded-full bg-[#f7e6e1] text-[#9c4a3c] dark:bg-[#3a201a] dark:text-[#e6a99f]">
              <XCircle size={26} weight="fill" aria-hidden="true" />
            </span>
            <p className="max-w-[260px] text-sm font-medium text-[#9c4a3c] dark:text-[#e6a99f]">{errorText}</p>
          </>
        )}
      </div>
    </div>
  );
}
