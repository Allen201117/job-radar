/**
 * 组件库统一出口（barrel）。业务代码一律从 `@/components/ui` 导入，不要深链到具体文件——
 * 这样将来重命名 / 拆分 / 废弃某个组件时，改动能收在库内部。
 *
 * ═══ 维护规矩（改动本目录前先读 DESIGN.md 的「组件库」一节）═══
 * 1. 新增组件 → 建 `components/ui/<name>.tsx`（一组件一文件，不建目录），并在此登记导出。
 *    漏登记会被 tests/design-system-contract.test.js 判红。
 * 2. 变体表（cva）写进 `lib/ui/variants.ts`，不要写在组件文件里 —— 那里的 .ts 才能被单测加载。
 * 3. 本目录内**禁止出现 hex 色值**。颜色一律走 globals.css 的 --tone-* / --ink-* 变量，
 *    或复用 .btn-* / .field-soft / .surface 这些既有类。契约测试会扫。
 * 4. 废弃组件 → 移进 `components/ui/deprecated/` 并加 `@deprecated` JSDoc，**不要直接删**，
 *    让调用方能按自己的节奏迁移（做法学自 GitHub Primer 的 src/deprecated/）。
 */

export { Button, buttonVariants, type ButtonProps } from "./button";
export { Badge, badgeVariants, type BadgeProps } from "./badge";
export { Banner, bannerVariants, type BannerProps } from "./banner";
export { EmptyState, type EmptyStateProps } from "./empty-state";
export { Field, Input, Textarea, Select, type FieldProps, type InputProps } from "./field";
export { Modal, type ModalProps } from "./modal";
export { Popover, type PopoverProps } from "./popover";
export { Segmented, type SegmentedOption, type SegmentedProps } from "./segmented";
export { Spinner, type SpinnerProps } from "./spinner";
export { AnimateNumber, type AnimateNumberProps } from "./animated-blur-number";
export { AnimatedStat } from "./animated-stat";

export { TONES, SIZES, type Tone, type Size } from "@/lib/ui/variants";
