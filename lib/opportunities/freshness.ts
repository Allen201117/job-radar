// 岗位新鲜度（§6.4）：只用 job.last_seen_at + source.crawl_method，不访问网络。
// SLA 表（小时）：
//   http       verified<=18  aging<=36
//   playwright verified<=36  aging<=72
//   manual/未知 verified<=72  aging<=144
import type { FreshnessState } from "./types";

interface Sla {
  verified: number;
  aging: number;
}

const SLA: Record<string, Sla> = {
  http: { verified: 18, aging: 36 },
  playwright: { verified: 36, aging: 72 },
  manual: { verified: 72, aging: 144 },
};

function slaFor(crawlMethod: string | null): Sla {
  if (crawlMethod && SLA[crawlMethod]) return SLA[crawlMethod];
  // null 或未知 method 一律按 manual 兜底（最宽松）
  return SLA.manual;
}

// last_seen_at 缺失或非法 → unknown；否则按年龄分档。
export function freshnessState(
  lastSeenAt: string | null | undefined,
  crawlMethod: string | null,
  now: Date
): FreshnessState {
  if (!lastSeenAt) return "unknown";
  const seen = new Date(lastSeenAt).getTime();
  if (Number.isNaN(seen)) return "unknown";

  const ageHours = (now.getTime() - seen) / 3_600_000;
  const sla = slaFor(crawlMethod);

  if (ageHours <= sla.verified) return "verified";
  if (ageHours <= sla.aging) return "aging";
  return "stale";
}
