// v3 动态分区（04 spec §7）：按身份×强度×已触发信号生成有序 sections。纯函数。
// 入参 opps 已是 eligible 且各自 signals 已派生（service 负责）；本模块只做分区/截断/去重，不重算匹配/信号。
//
// 分区落点按 primary signal + 强度：
//   critical : 任一 signal isCritical（关键提醒：收藏岗关闭/校招快截止）—— 永远置顶、不截断、不受强度压制。
//   main     : primary ∈ STILL_OPEN/OPEN_UNVERIFIED/DEADLINE_SOON 且 score ≥ 强度门槛（active 45 / passive 70）。
//   explore  : 仅 active；primary ∈ STILL_OPEN/OPEN_UNVERIFIED/DEADLINE_SOON、score 30–门槛、exploreEligible。最多 5。
//   waiting  : primary=CLOSED_OR_STALE 且非关键。小批，最多 8。
//   momentum : 恒空（依赖 job_events，Phase 3 前不上 C 端「猛招」）。
import type {
  Opportunity,
  FeedSections,
  FeedCounts,
  RadarIntensity,
  OpportunitySignal,
  OpportunitySignalType,
} from "./types";

// 首次访问窗口：无 last_opened_at → now-72h（不把全部历史算成新增）；有则原样。
export function resolveNoveltySince(lastOpenedAt: string | null, now: Date): string {
  if (lastOpenedAt) return lastOpenedAt;
  return new Date(now.getTime() - 72 * 3_600_000).toISOString();
}

const WAITING_CAP = 8;
const EXPLORE_CAP = 5;

function primaryOf(o: Opportunity): OpportunitySignal | null {
  return o.signals.length ? o.signals[0] : null;
}
function cmpFirstSeenDesc(a: Opportunity, b: Opportunity): number {
  // String() 兜底：firstSeenAt 正常是 ISO 字符串，但若上游传来 Date 对象（node-pg 时间列默认解析）
  // 直接 .localeCompare 会抛 TypeError（2026-06-26 事故）。根因已在 jobs-store/client.ts 用 type parser 修，
  // 这里再裹一层 String 作防御，杜绝任何时间列类型漂移把整个 Feed 排序打挂。
  return String(b.firstSeenAt || "").localeCompare(String(a.firstSeenAt || ""));
}
function byScore(a: Opportunity, b: Opportunity): number {
  return b.score - a.score || cmpFirstSeenDesc(a, b);
}
// 关键提醒排序：信号优先级升序（关闭=1 先于截止=2），再 score 降序。
function byCriticalThenScore(a: Opportunity, b: Opportunity): number {
  const pa = primaryOf(a)?.priority ?? 99;
  const pb = primaryOf(b)?.priority ?? 99;
  return pa - pb || byScore(a, b);
}

function normalizeSemanticPart(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  return value
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[\s\p{P}]+/gu, "");
}

function semanticJobKey(opportunity: Opportunity): string {
  const company = normalizeSemanticPart(opportunity.job.company);
  const title = normalizeSemanticPart(opportunity.job.title);
  let location = normalizeSemanticPart(opportunity.job.location);
  if (!company || !title || !location) return `id:${opportunity.job.id}`;
  if (location.length > 1 && location.endsWith("市")) location = location.slice(0, -1);
  return `semantic:${company}|${title}|${location}`;
}

function dedupeBySemanticJob(opportunities: Opportunity[]): Opportunity[] {
  const seen = new Set<string>();
  return [...opportunities].sort(byScore).filter((opportunity) => {
    const key = semanticJobKey(opportunity);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function takeWithCompanyDiversity(opportunities: Opportunity[], limit: number): Opportunity[] {
  const perCompanyCap = Math.max(2, Math.ceil(limit * 0.3));
  const companyCounts = new Map<string, number>();
  const picked: Opportunity[] = [];
  const overflow: Opportunity[] = [];

  for (const opportunity of opportunities) {
    if (picked.length >= limit) break;
    const company = normalizeSemanticPart(opportunity.job.company) || `id:${opportunity.job.id}`;
    const count = companyCounts.get(company) ?? 0;
    if (count >= perCompanyCap) {
      overflow.push(opportunity);
      continue;
    }
    companyCounts.set(company, count + 1);
    picked.push(opportunity);
  }

  if (picked.length < limit) {
    for (const opportunity of overflow) {
      if (picked.length >= limit) break;
      picked.push(opportunity);
    }
  }

  return picked;
}

function isMainSignal(o: Opportunity): boolean {
  const p = primaryOf(o);
  return !!p && (p.type === "STILL_OPEN" || p.type === "OPEN_UNVERIFIED" || p.type === "DEADLINE_SOON");
}

export interface GroupOptions {
  dailyLimit: number;
  intensity: RadarIntensity;
  noveltySince?: string | null;
  now?: Date;
}

export function groupOpportunities(
  opps: Opportunity[],
  options: GroupOptions
): { sections: FeedSections; counts: FeedCounts } {
  const { intensity, dailyLimit } = options;
  // 强度调量与门槛：passive 偏少、门槛偏高（只高价值）；active 偏多、含拓展。
  const effectiveLimit = intensity === "active" ? dailyLimit : Math.max(5, Math.min(dailyLimit, 10));
  const mainThreshold = intensity === "active" ? 45 : 70;
  const candidates = dedupeBySemanticJob(opps);

  // isNew 仅供展示（NEWLY_DISCOVERED 信号未上时不用于分区）
  if (options.noveltySince) {
    for (const o of candidates) o.isNew = Boolean(o.firstSeenAt) && o.firstSeenAt! > options.noveltySince;
  }

  const used = new Set<string>();
  const take = (list: Opportunity[]) => {
    for (const o of list) used.add(o.job.id);
    return list;
  };

  // critical：任一信号关键。语义去重已统一前置；本区不截断、不受公司配额或强度影响。
  const critical = take(
    candidates.filter((o) => o.signals.some((s) => s.isCritical)).sort(byCriticalThenScore)
  );

  // main：主信号 + 强度门槛，封顶 effectiveLimit。
  const main = take(
    takeWithCompanyDiversity(
      candidates
        .filter((o) => !used.has(o.job.id) && isMainSignal(o) && o.score >= mainThreshold)
        .sort(byScore),
      effectiveLimit,
    )
  );

  // explore：仅 active；主信号、score 30–门槛、exploreEligible，最多 5。
  let explore: Opportunity[] = [];
  if (intensity === "active") {
    explore = take(
      takeWithCompanyDiversity(
        candidates
          .filter(
            (o) =>
              !used.has(o.job.id) &&
              isMainSignal(o) &&
              o.exploreEligible &&
              o.score >= 30 &&
              o.score < mainThreshold
          )
          .sort(byScore),
        EXPLORE_CAP,
      )
    );
  }

  // waiting：长时间未确认（active 但超 today SLA）非关键，小批。
  const waiting = take(
    candidates
      .filter((o) => {
        if (used.has(o.job.id)) return false;
        const p = primaryOf(o);
        return !!p && p.type === "CLOSED_OR_STALE" && !p.isCritical;
      })
      .sort(byScore)
      .slice(0, WAITING_CAP)
  );

  const sections: FeedSections = { critical, main, explore, momentum: [], waiting };

  const by_signal: Partial<Record<OpportunitySignalType, number>> = {};
  const shown = [...critical, ...main, ...explore, ...waiting];
  for (const o of shown) {
    const p = primaryOf(o);
    if (!p) continue;
    by_signal[p.type] = (by_signal[p.type] ?? 0) + 1;
  }

  const counts: FeedCounts = {
    total: shown.length,
    critical: critical.length,
    main: main.length,
    by_signal,
  };

  return { sections, counts };
}
