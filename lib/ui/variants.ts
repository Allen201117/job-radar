/**
 * 组件库的变体表（单一事实源）。
 *
 * 为什么变体表住在 lib/ 的 .ts 而不是跟组件放一起：
 * tests/_load-ts.js 只递归转译 .ts，加载不了 .tsx。变体表放这里，契约测试就能**真的把它
 * 加载进来断言**（「ink 的小号必须不带落影」这种规则可以被机器验证），而不是只能 grep 字符串。
 * 这也是 Radix Themes 把 button.props.ts 与 button.tsx 分开的同一个理由。
 *
 * ═══ 一条必须守住的不变量：颜色不在这里 ═══
 * 按钮/输入框的颜色仍然由 app/globals.css 的 .btn-ink / .btn-soft / .field-soft 提供，
 * 这里**只加尺寸轴**。原因是全站改造前的病根就是「CSS 类每个只有一个写死的尺寸」——
 * 想换个 padding 就得把整串样式连暗色一起抄出来（实测墨色按钮被手抄成 11 种尺寸、
 * 白底次按钮 10 种，而 CSS 只提供 2 种和 1 种）。
 *
 * 补尺寸而不重抄颜色，靠的是 Tailwind 的层序：@layer components 排在 @layer utilities 之前，
 * 所以 `btn-ink px-4 py-2` 里的 px-4 必然覆盖 .btn-ink 自带的 px-6，而颜色/暗色/hover 全部
 * 原样继承。**收益是颜色永远只有一份定义，改一处全站生效；代价是不要在这里写任何 hex。**
 * 契约测试 tests/design-system-contract.test.js 会守着「本文件与 components/ui 内不出现 hex」。
 */
import { cva, type VariantProps } from "class-variance-authority";

/** 语义色调七族。值住在 globals.css 的 --tone-* 变量里，明暗自动切换。 */
export const TONES = ["neutral", "sky", "green", "amber", "teal", "rose", "lilac"] as const;
export type Tone = (typeof TONES)[number];

/** 控件尺寸四档。取值来自现网实际用量的前四名，不是拍脑袋定的。 */
export const SIZES = ["xs", "sm", "md", "lg"] as const;
export type Size = (typeof SIZES)[number];

/* ─────────────────────────── Button ─────────────────────────── */

/**
 * 尺寸取值对照（改前的手写分布 → 现在的档位）：
 *   xs = px-3  py-1.5 13px   现网手写 3 次
 *   sm = px-4  py-2   13px   等于 .btn-ink-sm 自带尺寸，现网手写 6 次
 *   md = px-5  py-2.5 13px   现网手写（today-client 顶部两颗主按钮）
 *   lg = px-6  py-3   15px   等于 .btn-ink 自带尺寸
 *
 * ⚠️ ink 的落影只属于 lg：.btn-ink 有 box-shadow、.btn-ink-sm 没有，这是原设计的刻意区分
 * （大按钮要「浮起来」，卡内小按钮不能抢视线）。所以 ink 用 compoundVariants 按尺寸切换
 * 底座类，而不是一律套 .btn-ink 再想办法关掉落影——后者会引入 !important，且破坏 1:1。
 */
export const buttonVariants = cva(
  // 底座留空：形状/排布/过渡全部由各 variant 对应的 CSS 类提供，此处不重复声明。
  "",
  {
    variants: {
      variant: {
        /** 主操作：墨黑实心胶囊，一屏只该有一个。底座类由 compoundVariants 按尺寸给。 */
        ink: "",
        /** 次操作：暖白软底胶囊，卡内 / 行内用。 */
        soft: "btn-soft",
        /** 次操作：描边幽灵胶囊，用于大号并列场景（登录页那种）。 */
        ghost: "btn-ghost",
        /** 纯文字按钮：没有底、没有边，只有文字与下划线，用于「取消」这类退让操作。 */
        quiet:
          "inline-flex select-none items-center justify-center gap-1.5 rounded-full underline-offset-2 transition duration-200 ease-out hover:underline disabled:cursor-not-allowed disabled:opacity-50",
      },
      size: {
        xs: "px-3 py-1.5 text-[0.8125rem] gap-1.5",
        sm: "px-4 py-2 text-[0.8125rem] gap-1.5",
        md: "px-5 py-2.5 text-[0.8125rem] gap-1.5",
        lg: "px-6 py-3 text-[0.9375rem] gap-2",
      },
      /** 撑满一行（表单提交按钮、移动端主操作）。 */
      block: { true: "w-full", false: "" },
    },
    compoundVariants: [
      { variant: "ink", size: ["xs", "sm", "md"], class: "btn-ink-sm" },
      { variant: "ink", size: "lg", class: "btn-ink" },
    ],
    defaultVariants: { variant: "ink", size: "md", block: false },
  },
);

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;

/* ─────────────────────────── Badge ─────────────────────────── */

/**
 * 状态 / 维度小标签。tone 决定语义颜色，全部指向 --tone-* 变量。
 * 语义分工沿用现网：sky 社招 · green 校招/已核实 · amber 实习/转陈 · teal 招聘动态 ·
 * rose 失败/风险 · lilac 职业洞察 · neutral 不表态。
 */
export const badgeVariants = cva(
  "inline-flex select-none items-center gap-1.5 rounded-full border font-medium",
  {
    variants: {
      tone: {
        neutral: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
        sky: "border-tone-sky-border bg-tone-sky-bg text-tone-sky-fg",
        green: "border-tone-green-border bg-tone-green-bg text-tone-green-fg",
        amber: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
        teal: "border-tone-teal-border bg-tone-teal-bg text-tone-teal-fg",
        rose: "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg",
        lilac: "border-tone-lilac-border bg-tone-lilac-bg text-tone-lilac-fg",
      },
      size: {
        // 11px，现网最常用（67 次）
        xs: "px-2 py-0.5 text-[0.6875rem] leading-[1.45] tracking-[0.02em]",
        // 12px，等于 .chip 的口径（37 次）
        sm: "px-2.5 py-1 text-[0.75rem] leading-[1.5]",
        md: "px-3 py-1 text-[0.8125rem] leading-[1.5]",
        lg: "px-3.5 py-1.5 text-[0.8125rem] leading-[1.5]",
      },
    },
    defaultVariants: { tone: "neutral", size: "sm" },
  },
);

export type BadgeVariantProps = VariantProps<typeof badgeVariants>;

/* ─────────────────────────── Banner ─────────────────────────── */

/**
 * 整块提示条（表单报错、能力不可用说明）。
 * 改造前这套红色样式在 6 个文件里被逐字复制；tone 一收，改一次全站生效。
 */
export const bannerVariants = cva("rounded-2xl border px-4 py-3", {
  variants: {
    tone: {
      neutral: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
      sky: "border-tone-sky-border bg-tone-sky-bg text-tone-sky-fg",
      green: "border-tone-green-border bg-tone-green-bg text-tone-green-fg",
      amber: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
      teal: "border-tone-teal-border bg-tone-teal-bg text-tone-teal-fg",
      rose: "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg",
      lilac: "border-tone-lilac-border bg-tone-lilac-bg text-tone-lilac-fg",
    },
    size: {
      sm: "rounded-xl px-3 py-2 text-[0.8125rem]",
      md: "text-[0.875rem]",
    },
  },
  defaultVariants: { tone: "rose", size: "md" },
});

export type BannerVariantProps = VariantProps<typeof bannerVariants>;
