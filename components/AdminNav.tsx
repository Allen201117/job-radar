"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUUpLeft, ChartLineUp, Lightbulb, Plugs } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

// 管理后台顶栏。取代三个后台页原先挂着的产品导航（今日/岗位/校招/偏好/收藏/投递）——
// 那条导航是给求职者用的，管理员在后台看数据时它既占位置又容易误点。
//
// 只做两件事：① 三个后台页之间互通 ② 留一个明确的回产品出口。
// 刻意不做账号菜单/主题切换：后台页不需要，少一个客户端组件少一份包体。
const ADMIN_LINKS = [
  { href: "/admin/health", label: "运营看板", icon: ChartLineUp },
  { href: "/admin/insights", label: "洞察管理", icon: Lightbulb },
  { href: "/sources", label: "招聘源管理", icon: Plugs },
] as const;

export default function AdminNav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-black/[0.07] bg-[#f4efe6]/85 backdrop-blur-xl dark:border-white/[0.09] dark:bg-[#1c1813]/85">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <span className="t-label hidden shrink-0 items-center gap-2 font-semibold ink-1 sm:inline-flex">
          <span aria-hidden="true" className="grid size-6 place-items-center rounded-[0.5rem] bg-[#1a1714] text-[11px] font-bold text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">管</span>
          管理后台
        </span>
        <nav aria-label="管理后台" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {ADMIN_LINKS.map((link) => {
            // /admin/health 下还有 ?tab=，用 startsWith 才能在切 tab 后保持高亮。
            const active = pathname === link.href || pathname.startsWith(link.href + "/");
            const Icon = link.icon;
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "t-label inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 transition",
                  active
                    ? "bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "ink-2 hover:bg-black/[0.05] dark:hover:bg-white/[0.07]",
                )}
              >
                <Icon size={15} weight={active ? "fill" : "regular"} aria-hidden="true" />
                {link.label}
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
