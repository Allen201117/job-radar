/**
 * 后台表单用的旧输入框样式串。
 *
 * 它此前在 AddSourceForm.tsx 与 InsightSubmitForm.tsx 里**逐字节重复了两份**，
 * 收到这里是为了消掉重复本身（改一处漏一处是迟早的事），而不是认可这个样式。
 *
 * 它和组件库的 `<Input>`（走 globals.css 的 .field-soft）在三处对不上，所以不能直接替换
 * ——那会改动像素：
 *   圆角   rounded-lg      vs .field-soft 的 rounded-xl
 *   内距   px-3 py-2       vs px-3.5 py-2.5
 *   聚焦   没有聚焦光环     vs .field-soft 有 4px 墨色光环
 *   暗色   border 0.1      vs 0.12，且聚焦态取值不同
 *
 * @deprecated 新表单一律用 `<Field>` + `<Input>`（`@/components/ui`）。
 * 这两处存量要迁移的话，需要先确认「后台表单可以采用与产品页一致的输入框外观」——
 * 那是一次有意的视觉改动，得单独决定，不能顺手改掉。
 */
export const LEGACY_INPUT_CLASS =
  "w-full rounded-lg border border-black/[0.09] bg-white/70 px-3 py-2 text-sm ink-1 outline-none placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:placeholder:text-[#8b8478] dark:focus:border-white/40 dark:focus:bg-[#1e1a15]";
