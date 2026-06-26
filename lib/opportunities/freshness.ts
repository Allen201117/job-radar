// 岗位新鲜度（§6.4）：只用 job.last_seen_at + source.crawl_method，不访问网络。
// SLA 表（小时）：
//   http       verified<=18  aging<=36
//   playwright verified<=36  aging<=72
//   manual/未知 verified<=72  aging<=144
import type { FreshnessState, VerifyTier, Job } from "./types";

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

// 分层核验 SLA（01 spec §2）：叠加在 freshnessState（源侧抓取新鲜度）之上的「逐岗核验新鲜度」，
// 按 jobs.enrich_checked_at 的年龄判定该岗在某场景下是否「够新鲜可主推」。两者都要满足才进 today 主清单。
//
// 时限（小时）：today ≤24h；search ≤72h（超时仍展示但标「待确认」）；admin 无时限（禁写「仍在招」）。
// enrich_checked_at 为 NULL（从未核验）：一律不算 verified，今日 tier 一律不通过——不能假装核验过。
const VERIFY_TIER_HOURS: Record<VerifyTier, number | null> = {
  today: 24,
  search: 72,
  admin: null, // 无时限
};

export function meetsVerifyTier(
  job: Pick<Job, "enrich_checked_at">,
  tier: VerifyTier,
  now: Date
): { ok: boolean; freshness: FreshnessState; checkedAgeHours: number | null } {
  const raw = job.enrich_checked_at ?? null;
  const checkedAt = raw ? new Date(raw).getTime() : NaN;

  // 从未核验 / 非法时间戳 → unknown，且 today/search 一律不算满足（admin 无时限放行但 freshness 仍 unknown）。
  if (!raw || Number.isNaN(checkedAt)) {
    return { ok: tier === "admin", freshness: "unknown", checkedAgeHours: null };
  }

  const ageHours = (now.getTime() - checkedAt) / 3_600_000;
  const limit = VERIFY_TIER_HOURS[tier];

  // 核验新鲜度档：≤24h verified / ≤72h aging / 否则 stale（与 today/search 阈值同口径）。
  const freshness: FreshnessState = ageHours <= 24 ? "verified" : ageHours <= 72 ? "aging" : "stale";

  const ok = limit === null ? true : ageHours <= limit;
  return { ok, freshness, checkedAgeHours: ageHours };
}
