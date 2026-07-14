"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChatCircleDots, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

// 用户反馈群二维码：微信群码会定期失效，换群时只需替换 public/ 下这张图。
const QR_SRC = "/wechat-group-qr.png";

export default function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [qrFailed, setQrFailed] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="用户反馈"
        className="group relative grid size-9 place-items-center rounded-full text-[#5f594e] outline-none transition duration-200 hover:bg-black/[0.05] hover:text-[#1a1714] active:scale-[0.95] focus-visible:ring-2 focus-visible:ring-[#1a1714]/25 dark:text-[#b6ad9d] dark:hover:bg-white/[0.06] dark:hover:text-[#f3ecdf] dark:focus-visible:ring-[#f3ecdf]/30"
      >
        <ChatCircleDots size={19} aria-hidden="true" />
        {/* 气泡标签：与一级导航同款，纯视觉，无障碍名走 aria-label */}
        <span
          role="tooltip"
          className="pointer-events-none absolute left-1/2 top-full z-50 mt-2.5 -translate-x-1/2 translate-y-1 whitespace-nowrap rounded-lg bg-[#1a1714] px-2.5 py-1 text-xs font-medium text-[#f7f1e6] opacity-0 shadow-[0_12px_30px_-14px_rgba(26,23,20,0.7)] transition duration-200 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100 dark:bg-[#f3ecdf] dark:text-[#16130f]"
        >
          <span
            aria-hidden="true"
            className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rotate-45 rounded-[2px] bg-[#1a1714] dark:bg-[#f3ecdf]"
          />
          用户反馈
        </span>
      </button>
      {/* Navbar 有 backdrop-blur，会给 fixed 子元素造 containing block，弹窗必须 portal 到 body */}
      {mounted &&
        open &&
        createPortal(
          <div
            className="fixed inset-0 z-[130] flex items-center justify-center overflow-y-auto bg-[#1a1714]/40 p-4 backdrop-blur-sm dark:bg-black/60"
            onClick={() => setOpen(false)}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="feedback-dialog-title"
              onClick={(e) => e.stopPropagation()}
              className="save-pop relative my-auto w-full max-w-sm rounded-3xl border border-black/[0.08] bg-[#f7f1e6] p-6 text-center shadow-[0_30px_70px_-30px_rgba(40,34,28,0.6)] dark:border-white/[0.12] dark:bg-[#1e1a15] dark:shadow-[0_30px_70px_-30px_rgba(0,0,0,0.8)]"
            >
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="关闭"
                className="absolute right-4 top-4 grid size-8 place-items-center rounded-full text-[#8a8275] transition hover:bg-black/[0.05] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:bg-white/[0.06] dark:hover:text-[#f3ecdf]"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>

              <h2
                id="feedback-dialog-title"
                className="text-lg font-semibold text-[#1a1714] dark:text-[#f3ecdf]"
              >
                加入用户反馈群
              </h2>
              <p className="mx-auto mt-1.5 max-w-[16rem] text-sm leading-relaxed text-[#5f594e] dark:text-[#b6ad9d]">
                用得不顺手、岗位不准、想要什么功能，微信扫码进群直接说，我们看得到。
              </p>

              <div className="mt-5 flex justify-center">
                {qrFailed ? (
                  <p className="rounded-2xl border border-dashed border-black/[0.12] px-6 py-10 text-sm text-[#8a8275] dark:border-white/[0.16] dark:text-[#9a9184]">
                    二维码暂时加载不出来，稍后再试
                  </p>
                ) : (
                  <Image
                    src={QR_SRC}
                    alt="职达反馈群 微信群二维码"
                    width={939}
                    height={1455}
                    unoptimized
                    onError={() => setQrFailed(true)}
                    className="h-auto w-full max-w-[248px] rounded-2xl ring-1 ring-black/[0.06] dark:ring-white/[0.08]"
                  />
                )}
              </div>

              {/* 有效期提示已印在群码图里，这里不重复 */}
              <p className="mt-4 text-xs text-[#9a9184] dark:text-[#837c70]">
                打开微信「扫一扫」即可进群
              </p>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
