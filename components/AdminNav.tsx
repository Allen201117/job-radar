"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUUpLeft } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

// 管理后台顶栏。取代三个后台页原先挂着的产品导航（今日/岗位/校招/偏好/收藏/投递）——
// 那条导航是给求职者用的，管理员在后台看数据时它既占位置又容易误点。
//
// 刻意不做账号菜单/主题切换：后台页不需要，少一个客户端组件少一份包体。
// 顶栏放的是运营看板的五个模块本身——创始人定的：这五块是天天要看的，
// 洞察管理 / 招聘源管理是偶尔才进一次的维护页，不值得占顶栏位置（仍可直接访问 URL）。
const BOARD_TABS = [
  { key: "overview", label: "总览" },
  { key: "jobs", label: "岗位库" },
  { key: "supply", label: "必投供给" },
  { key: "users", label: "用户行为" },
  { key: "system", label: "系统运行" },
] as const;

function tabHref(key: string) {
  return key === "overview" ? "/admin/health" : `/admin/health?tab=${key}`;
}

// 不在顶栏里的后台页（洞察管理 / 招聘源管理）：只有正处在这个页面时才显示一枚胶囊，
// 否则用户会站在一个页面上、而顶栏没有任何一项是高亮的，不知道自己在哪。
const SIDE_PAGES: Record<string, string> = {
  "/admin/insights": "洞察管理",
  "/sources": "招聘源管理",
};

export default function AdminNav({ activeTab }: { activeTab?: string }) {
  const pathname = usePathname();
  const onBoard = pathname === "/admin/health";
  const sideLabel = SIDE_PAGES[pathname];

  return (
    <header className="sticky top-0 z-40 border-b border-black/[0.07] bg-[#f4efe6]/85 backdrop-blur-xl dark:border-white/[0.09] dark:bg-[#1c1813]/85">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <Link
          href="/admin/health"
          className="t-label hidden shrink-0 items-center gap-2 font-semibold ink-1 sm:inline-flex"
        >
          <span aria-hidden="true" className="grid size-6 place-items-center rounded-[0.5rem] bg-[#1a1714] text-[11px] font-bold text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">管</span>
          管理后台
        </Link>
        <nav aria-label="管理后台" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {sideLabel && (
            <span
              aria-current="page"
              className="t-label inline-flex shrink-0 items-center gap-1.5 rounded-full bg-[#1a1714] px-3 py-1.5 text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
            >
              {sideLabel}
            </span>
          )}
          {BOARD_TABS.map((tab) => {
            const active = onBoard && (activeTab || "overview") === tab.key;
            return (
              <Link
                key={tab.key}
                href={tabHref(tab.key)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "t-label inline-flex shrink-0 items-center rounded-full px-3 py-1.5 transition",
                  active
                    ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "ink-2 hover:bg-black/[0.05] dark:hover:bg-white/[0.07]",
                )}
              >
                {tab.label}
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
