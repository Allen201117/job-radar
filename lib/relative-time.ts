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
