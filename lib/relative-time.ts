const MS_PER_DAY = 24 * 60 * 60 * 1000;

export function relativeTimeLabel(
  input: string | Date | null | undefined,
  now: Date = new Date(),
): string | null {
  if (input == null) return null;

  const date = input instanceof Date ? input : new Date(input);
  const time = date.getTime();
  const nowTime = now.getTime();
  if (!Number.isFinite(time) || !Number.isFinite(nowTime)) return null;

  const days = Math.floor((nowTime - time) / MS_PER_DAY);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days <= 6) return `${days}天前`;
  if (days <= 29) return `${Math.floor(days / 7)}周前`;
  if (days <= 364) return `${Math.floor(days / 30)}个月前`;
  return `${Math.floor(days / 365)}年前`;
}

/**
 * 展示口径的业务时区。岗位发布日 / 截止日 / 投递日都是「北京时间的哪一天」，与看的人在哪儿无关。
 */
export const DISPLAY_TIME_ZONE = "Asia/Shanghai";

/**
 * 绝对日期文案（如 `2026/8/31`）。
 *
 * ⚠️ **必须显式钉死 timeZone，别退回裸 `toLocaleDateString`**：后者按**运行时**时区格式化，
 * 而 Vercel 函数跑 UTC、浏览器跑用户本地时区（国内 UTC+8）。于是同一个时间戳
 * SSR 出「8/30」、hydration 出「8/31」，React 判定文本不一致 → 生产 #418 水合报错
 * （2026-09-02 实测 /today /jobs /campus 每次加载必现）。凡是会被服务端渲染进 HTML 的
 * 日期，一律走本函数。
 */
export function formatDateLabel(
  input: string | number | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = {},
): string | null {
  if (input == null || input === "") return null;

  const date = input instanceof Date ? input : new Date(input);
  if (!Number.isFinite(date.getTime())) return null;

  return new Intl.DateTimeFormat("zh-CN", { timeZone: DISPLAY_TIME_ZONE, ...options }).format(date);
}
