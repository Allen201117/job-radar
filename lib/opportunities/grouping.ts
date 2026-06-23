// Feed 分区、截断、去重（§7.3）+ 新鲜度窗口（§7.2）。纯函数：输入已打分的 Opportunity[]，输出四区 + 计数。
// 入参 opps 应已是 eligible 且 score>=30（service 负责）；本模块只做分区与封顶，不重算匹配。
import type { Opportunity, FeedSections, FeedCounts } from "./types";

// 首次访问窗口：无 last_opened_at → now-72h（不把全部历史算成新增）；有则原样。
export function resolveNoveltySince(lastOpenedAt: string | null, now: Date): string {
  if (lastOpenedAt) return lastOpenedAt;
  return new Date(now.getTime() - 72 * 3_600_000).toISOString();
}

function cmpFirstSeenDesc(a: Opportunity, b: Opportunity): number {
  return (b.firstSeenAt || "").localeCompare(a.firstSeenAt || "");
}
function byScore(a: Opportunity, b: Opportunity): number {
  return b.score - a.score || cmpFirstSeenDesc(a, b);
}

export function groupOpportunities(
  opps: Opportunity[],
  dailyLimit: number,
  noveltySince: string
): { sections: FeedSections; counts: FeedCounts } {
  const verified = opps.filter((o) => o.freshness === "verified" && o.score >= 30);
  const aging = opps.filter((o) => o.freshness === "aging" && o.score >= 30);

  for (const o of opps) o.isNew = Boolean(o.firstSeenAt) && o.firstSeenAt! > noveltySince;

  const used = new Set<string>();

  // A 新出现：isNew + score>=45 + verified。排序 score desc, first_seen desc。上限 min(10, dailyLimit)。
  const candidatesA = verified.filter((o) => o.isNew && o.score >= 45).sort(byScore);
  const A = candidatesA.slice(0, Math.min(10, dailyLimit));
  A.forEach((o) => used.add(o.job.id));

  // B 高匹配待处理：不在 A + score>=70 + verified。排序 未 viewed 优先, score desc, first_seen desc。填到 dailyLimit。
  const candidatesB = verified
    .filter((o) => !used.has(o.job.id) && o.score >= 70)
    .sort((a, b) => (a.viewed ? 1 : 0) - (b.viewed ? 1 : 0) || byScore(a, b));
  const B = candidatesB.slice(0, Math.max(0, dailyLimit - A.length));
  B.forEach((o) => used.add(o.job.id));

  // C 拓展：score 30-44 + exploreEligible（related 或命中公司）+ 仅当 A+B 未满。最多 5。
  let C: Opportunity[] = [];
  const usedAfterB = A.length + B.length;
  if (usedAfterB < dailyLimit) {
    const candidatesC = verified
      .filter((o) => !used.has(o.job.id) && o.score >= 30 && o.score <= 44 && o.exploreEligible)
      .sort(byScore);
    C = candidatesC.slice(0, Math.min(5, dailyLimit - usedAfterB));
    C.forEach((o) => used.add(o.job.id));
  }

  // D 等待再次确认：仅当「整个 verified 队列」<5 时出现，最多 3 个 aging（不计入主队列承诺）。
  let D: Opportunity[] = [];
  if (verified.length < 5) {
    D = aging.filter((o) => !used.has(o.job.id)).sort(byScore).slice(0, 3);
    D.forEach((o) => used.add(o.job.id));
  }

  const counts: FeedCounts = {
    new_since_last_open: candidatesA.length,
    high_match: verified.filter((o) => o.score >= 70).length,
    verified: verified.length,
    aging: D.length,
  };

  return { sections: { new: A, priority: B, explore: C, aging: D }, counts };
}
