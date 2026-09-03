"use client";

import Link from "next/link";
import { ArrowUUpLeft } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

// 管理后台顶栏。取代三个后台页原先挂着的产品导航（今日/岗位/校招/偏好/收藏/投递）——
// 那条导航是给求职者用的，管理员在后台看数据时既占位置又容易误点。
//
// 顶栏放的是**运营看板的五个模块**（创始人 2026-09-03 定：洞察管理 / 招聘源管理
// 平时用不上，不占顶栏；两个页面仍在原 URL，只是不再挂导航入口）。
//
// 当前模块由**服务端传进来**（activeTab），不在客户端读 URL：
// 看板页本来就知道自己在哪个 tab，传一个字符串比让客户端再解析一次 search params
// 少一个 Suspense 边界、也不会在水合前闪一下「都没选中」。
const MODULES = [
  { key: "overview", label: "总览" },
  { key: "jobs", label: "岗位库" },
  { key: "supply", label: "必投供给" },
  { key: "users", label: "用户行为" },
  { key: "system", label: "系统运行" },
] as const;

export default function AdminNav({ activeTab }: { activeTab?: string }) {
  return (
    <header className="sticky top-0 z-40 border-b border-black/[0.07] bg-[#f4efe6]/85 backdrop-blur-xl dark:border-white/[0.09] dark:bg-[#1c1813]/85">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <Link href="/admin/health" className="t-label hidden shrink-0 items-center gap-2 font-semibold ink-1 sm:inline-flex">
          <span aria-hidden="true" className="grid size-6 place-items-center rounded-[0.5rem] bg-[#1a1714] text-[11px] font-bold text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">管</span>
          运营看板
        </Link>
        <nav aria-label="运营看板模块" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {MODULES.map((m) => {
            const active = activeTab === m.key;
            return (
              <Link
                key={m.key}
                href={m.key === "overview" ? "/admin/health" : `/admin/health?tab=${m.key}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "t-label shrink-0 rounded-full px-3.5 py-1.5 transition",
                  active
                    ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "ink-2 hover:bg-black/[0.05] dark:hover:bg-white/[0.07]",
                )}
              >
                {m.label}
              </Link>
            );
          })}
        </nav>
        <Link
          href="/today"
          className="t-label inline-flex shrink-0 items-center gap-1.5 rounded-full border border-black/[0.1] px-3 py-1.5 ink-3 transition hover:bg-black/[0.04] dark:border-white/[0.12] dark:hover:bg-white/[0.06]"
        >
          <ArrowUUpLeft size={14} weight="bold" aria-hidden="true" />
          <span className="hidden sm:inline">回到产品</span>
        </Link>
      </div>
    </header>
  );
}
