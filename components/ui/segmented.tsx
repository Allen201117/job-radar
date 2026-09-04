"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { Size } from "@/lib/ui/variants";

export type SegmentedOption<T extends string> = {
  value: T;
  label: React.ReactNode;
  /** 单个选项禁用（如「海外」在未开通时）。 */
  disabled?: boolean;
};

export type SegmentedProps<T extends string> = {
  /** 读屏用：这组按钮在选什么。必填——缺了读屏只会念一串孤立按钮。 */
  ariaLabel: string;
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: Extract<Size, "xs" | "sm" | "md">;
  className?: string;
};

const SIZE_CLASS: Record<"xs" | "sm" | "md", string> = {
  xs: "px-2.5 py-1 text-[0.6875rem]",
  sm: "px-3 py-1.5 text-[0.8125rem]",
  md: "px-4 py-2 text-[0.8125rem]",
};

/**
 * 分段控件（互斥选项组）：招聘类型、求职阶段、中英简历、国内/海外范围。
 *
 * 改造前 4 处各写各的，**行为参差**：四个都记得写 aria-pressed，但只有 JobFilters 的
 * RecruitmentType 加了 role="group" + aria-label，其余三个缺 —— 读屏用户听到的是三四个
 * 互不相干的按钮，不知道它们是一组、更不知道这组在选什么。
 *
 * 这里把 role="group" + aria-label 做成**必填**（ariaLabel 是必需 prop），从类型上堵死漏写。
 */
export function Segmented<T extends string>({
  ariaLabel,
  options,
  value,
  onChange,
  size = "sm",
  className,
}: SegmentedProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn("inline-flex flex-wrap items-center gap-1.5", className)}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            disabled={option.disabled}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "select-none rounded-full border font-medium transition duration-200 ease-out disabled:cursor-not-allowed disabled:opacity-50",
              SIZE_CLASS[size],
              active
                ? // 选中态复用主操作的墨色，与全站「一个墨色 = 当前生效」的语言一致。
                  "btn-ink-sm"
                : "btn-soft",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
