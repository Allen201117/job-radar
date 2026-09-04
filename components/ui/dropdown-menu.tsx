"use client";

// 行为层基于 Radix DropdownMenu（MIT，Copyright (c) WorkOS）——见 LICENSES/。
import * as React from "react";
import * as RD from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export type MenuItem = {
  key: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  /** 破坏性操作（删除/下架）：红色文字 + 与其它项之间自动加分隔。 */
  destructive?: boolean;
};

export type DropdownMenuProps = {
  trigger: React.ReactElement;
  items: readonly MenuItem[];
  ariaLabel: string;
  align?: "start" | "center" | "end";
  className?: string;
};

/**
 * 下拉菜单（卡片右上角「更多」那类）。
 *
 * 为什么用 Radix：难点全在键盘与焦点——上下键循环、首字母跳转（typeahead）、
 * Esc 关闭并把焦点还给触发器、菜单贴边时自动翻转、菜单打开时背景不可 Tab。
 * 这几条自己写基本一定会漏掉 typeahead 和焦点归还。
 *
 * ⚠️ 破坏性操作必须视觉上分出来（红字 + 分隔线），否则「删除」和「编辑」长得一样，
 * 手滑的代价不对等。
 */
export function DropdownMenu({
  trigger,
  items,
  ariaLabel,
  align = "end",
  className,
}: DropdownMenuProps) {
  return (
    <RD.Root>
      <RD.Trigger asChild>{trigger}</RD.Trigger>
      <RD.Portal>
        <RD.Content
          aria-label={ariaLabel}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            "surface z-[140] min-w-[10rem] overflow-hidden p-1 shadow-lg",
            "data-[state=open]:animate-in data-[state=closed]:animate-out motion-reduce:animate-none",
            className,
          )}
          style={{
            animationDuration: "var(--dur-toggle, 180ms)",
            animationTimingFunction: "var(--spring-snappy, cubic-bezier(0.38, 1.21, 0.22, 1))",
          }}
        >
          {items.map((item, i) => {
            const prevDestructive = i > 0 && items[i - 1].destructive;
            const needsRule = item.destructive && !prevDestructive && i > 0;
            return (
              <React.Fragment key={item.key}>
                {needsRule ? <RD.Separator className="my-1 h-px bg-tone-neutral-border" /> : null}
                <RD.Item
                  disabled={item.disabled}
                  onSelect={item.onSelect}
                  className={cn(
                    "t-body-sm flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-2 outline-none",
                    "data-[highlighted]:bg-black/[0.05] dark:data-[highlighted]:bg-white/[0.08]",
                    "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40",
                    item.destructive ? "text-tone-rose-fg" : "ink-2",
                  )}
                >
                  {item.icon}
                  {item.label}
                </RD.Item>
              </React.Fragment>
            );
          })}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}
