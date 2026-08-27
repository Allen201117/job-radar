// v3 动态分区（04 spec §7）：按身份×强度×已触发信号生成有序 sections。纯函数。
// 入参 opps 已是 eligible 且各自 signals 已派生（service 负责）；本模块只做分区/截断/去重，不重算匹配/信号。
//
// 分区落点按 primary signal + 强度：
//   critical : 任一 signal isCritical（关键提醒：收藏岗关闭/校招快截止）—— 永远置顶、总条数不截断、不受强度压制，但守放宽后的公司上限。
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
const SEMANTIC_PUNCTUATION_RE = new RegExp("[\\s\\p{P}]+", "gu");

function primaryOf(o: Opportunity): OpportunitySignal | null {
  return o.signals.length ? o.signals[0] : null;
}
function firstSeenMillis(value: string | Date | null | undefined): number {
  let millis = NaN;
  if (value instanceof Date) millis = value.getTime();
  else if (typeof value === "string") millis = Date.parse(value);
  return Number.isFinite(millis) ? millis : Number.NEGATIVE_INFINITY;
}
function cmpFirstSeenDesc(a: Opportunity, b: Opportunity): number {
  // node-pg 可能交付 Date，其他路径交付 ISO；统一比较 epoch millis，避免 String(Date) 的 weekday 字典序。
  const aTime = firstSeenMillis(a.firstSeenAt);
  const bTime = firstSeenMillis(b.firstSeenAt);
  if (aTime !== bTime) return bTime - aTime;
  const aId = String(a.job.id);
  const bId = String(b.job.id);
  return aId < bId ? -1 : aId > bId ? 1 : 0;
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

function isCriticalOpportunity(opportunity: Opportunity): boolean {
  return opportunity.signals.some((signal) => signal.isCritical);
}

interface SemanticRankContext {
  intensity: RadarIntensity;
  mainThreshold: number;
}

function semanticDisplayRank(opportunity: Opportunity, context: SemanticRankContext): number {
  if (isCriticalOpportunity(opportunity)) return 0;
  const primary = primaryOf(opportunity);
  if (isMainSignal(opportunity) && opportunity.score >= context.mainThreshold) return 1;
  if (
    context.intensity === "active" &&
    isMainSignal(opportunity) &&
    opportunity.exploreEligible &&
    opportunity.score >= 30 &&
    opportunity.score < context.mainThreshold
  ) return 2;
  if (primary?.type === "CLOSED_OR_STALE" && !primary.isCritical) return 3;
  return 4;
}

function bySemanticSurvivorPriority(
  a: Opportunity,
  b: Opportunity,
  context: SemanticRankContext,
): number {
  const aRank = semanticDisplayRank(a, context);
  const bRank = semanticDisplayRank(b, context);
  if (aRank !== bRank) return aRank - bRank;
  return aRank === 0 ? byCriticalThenScore(a, b) : byScore(a, b);
}

function normalizeSemanticPart(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  return value
    .normalize("NFKC")
    .toLowerCase()
    .replace(SEMANTIC_PUNCTUATION_RE, "");
}

function semanticJobKey(opportunity: Opportunity): string {
  const company = normalizeSemanticPart(opportunity.job.company);
  const title = normalizeSemanticPart(opportunity.job.title);
  let location = normalizeSemanticPart(opportunity.job.location);
  if (!company || !title || !location) return `id:${opportunity.job.id}`;
  if (location.length > 1 && location.endsWith("市")) location = location.slice(0, -1);
  return `semantic:${company}|${title}|${location}`;
}

function dedupeBySemanticJob(opportunities: Opportunity[], context: SemanticRankContext): Opportunity[] {
  const seen = new Set<string>();
  return [...opportunities].sort((a, b) => bySemanticSurvivorPriority(a, b, context)).filter((opportunity) => {
    const key = semanticJobKey(opportunity);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function companyKeyOf(opportunity: Opportunity): string {
  return normalizeSemanticPart(opportunity.job.company) || `id:${opportunity.job.id}`;
}

// 公司配额与「放宽后的回填上限」。
// ⚠️ 回填曾是「无条件把刚被配额拒掉的岗原样放回来」，等于配额自己把自己撤销了
// （线上 30 张卡：字节 9 个封顶 → 回填又塞回 6 个 → 一家占 15 张 = 半屏，2026-08-27 实测）。
// 现在回填也守配额，只是把上限放宽到 cap + floor(cap/2)（30 张时 9 → 13）：
// 宁可少给几张卡，也不让一家公司占掉半屏。
// ⚠️ 这里是 floor 不是 ceil：ceil 在 limit=10 时给出 3+2=5，正好是半屏，等于放行本条规则要拦的事；
// floor 让单公司恒定 <50%（30 张 → 13、10 张 → 4）。
function companyCapsFor(basis: number): { perCompanyCap: number; backfillCap: number } {
  const perCompanyCap = Math.max(2, Math.ceil(basis * 0.3));
  return { perCompanyCap, backfillCap: perCompanyCap + Math.floor(perCompanyCap / 2) };
}

// limit = 本区总条数上限（critical 区不截断，传 Infinity）；capBasis = 算公司配额的基数，默认同 limit。
function takeWithCompanyDiversity(
  opportunities: Opportunity[],
  limit: number,
  capBasis: number = limit,
): Opportunity[] {
  const { perCompanyCap, backfillCap } = companyCapsFor(capBasis);
  const companyCounts = new Map<string, number>();
  const picked: Opportunity[] = [];
  const overflow: Opportunity[] = [];

  for (const opportunity of opportunities) {
    if (picked.length >= limit) break;
    const company = companyKeyOf(opportunity);
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
      const company = companyKeyOf(opportunity);
      const count = companyCounts.get(company) ?? 0;
      if (count >= backfillCap) continue;
      companyCounts.set(company, count + 1);
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
  const candidates = dedupeBySemanticJob(opps, { intensity, mainThreshold });

  // isNew 仅供展示（NEWLY_DISCOVERED 信号未上时不用于分区）
  if (options.noveltySince) {
    for (const o of candidates) o.isNew = Boolean(o.firstSeenAt) && o.firstSeenAt! > options.noveltySince;
  }

  const used = new Set<string>();
  const take = (list: Opportunity[]) => {
    for (const o of list) used.add(o.job.id);
    return list;
  };

  // critical：任一信号关键。语义去重已统一前置；本区不截断、不受强度影响，
  // 且**故意不受公司配额约束**——这里装的是「你收藏/投递过的那个岗关闭了 / 快截止了」，
  // 是对用户自己动作的告警，不是发现流。同一家公司收藏了 20 个岗同时关闭，20 条都得告诉他；
  // 给告警做多样性限流 = 悄悄吞掉用户自己的东西。
  // ⚠️ 2026-08-27 一度按「回填撤销配额那个坑的第二处」给它加过配额，随即撤回：那个坑的前提是
  // 「有配额 + 有回填」，critical 两样都没有，不是同一个问题。别再加。
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
