import type { BandTone } from "./admin-health";

export type DailyRunStatus = {
  runs?: number;
  failed?: number;
  partial?: number;
} | null | undefined;

// Tracker 一格只表达当天是否有记录及最严重的运行状态，不能把无记录伪装成 0 或成功。
export function dailyTrackerTone(run: DailyRunStatus): BandTone {
  if (!run || run.runs == null) return "muted";
  if ((run.failed || 0) > 0) return "danger";
  if ((run.partial || 0) > 0) return "warning";
  return "success";
}

export function nullableShare(numerator: number | null | undefined, denominator: number | null | undefined): number | null {
  if (numerator == null || denominator == null || denominator <= 0) return null;
  return numerator / denominator;
}
