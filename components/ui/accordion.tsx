"use client";

// 行为层基于 Radix Accordion（MIT，Copyright (c) WorkOS）——见 LICENSES/。
import * as React from "react";
import * as RA from "@radix-ui/react-accordion";
import { CaretDown } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export type AccordionItem = {
  value: string;
  title: React.ReactNode;
  /** 标题右侧的补充信息（计数、状态徽标）。 */
  meta?: React.ReactNode;
  content: React.ReactNode;
};

export type AccordionProps = {
  items: readonly AccordionItem[];
  /** single = 一次只能开一个（手风琴）；multiple = 各自独立开合。 */
  mode?: "single" | "multiple";
  defaultValue?: string | string[];
  className?: string;
};

/**
 * 折叠面板。全站 9 个文件手写过展开/收起。
 *
 * 为什么用 Radix：它把 `aria-expanded` / `aria-controls` / `id` 三者的配对做对了，
 * 手写时最常见的错就是 aria-controls 指向了不存在的 id，读屏用户听到「可展开」却跳不过去。
 *
 * ⚠️ 高度动画的坑：`height: auto` 不可动画。Radix 在展开时把真实高度写进
 * `--radix-accordion-content-height`，下面的 keyframes 用它来做 0 ↔ 实高 的过渡。
 * 自己写就得先量 scrollHeight，量的时机稍有不对就会闪一下。
 */
export function Accordion({ items, mode = "single", defaultValue, className }: AccordionProps) {
  const common = {
    className: cn("space-y-2", className),
    defaultValue: defaultValue as never,
  };
  const body = items.map((item) => (
    <RA.Item
      key={item.value}
      value={item.value}
      className="surface-soft overflow-hidden rounded-xl"
    >
      <RA.Header>
        <RA.Trigger
          className={cn(
            "press-feedback-subtle group flex w-full items-center justify-between gap-3 px-4 py-3 text-left outline-none",
            "focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-inset",
          )}
        >
          <span className="t-h3 ink-1 min-w-0">{item.title}</span>
          <span className="flex shrink-0 items-center gap-2">
            {item.meta}
            <CaretDown
              size={15}
              weight="bold"
              aria-hidden="true"
              className="ink-3 transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none"
              style={{
                transitionDuration: "var(--dur-toggle, 180ms)",
                transitionTimingFunction: "var(--spring-snappy, cubic-bezier(0.38, 1.21, 0.22, 1))",
              }}
            />
          </span>
        </RA.Trigger>
      </RA.Header>
      <RA.Content className="accordion-content overflow-hidden">
        <div className="t-body-sm px-4 pb-4">{item.content}</div>
      </RA.Content>
    </RA.Item>
  ));

  return mode === "single" ? (
    <RA.Root type="single" collapsible {...common}>
      {body}
    </RA.Root>
  ) : (
    <RA.Root type="multiple" {...common}>
      {body}
    </RA.Root>
  );
}
