// 展示回填（P0-1 性能）：召回为省跨区传输只取硬门/打分必需的少量列（截断 summary）；
// 最终入选的少量岗位（≤ dailyLimit + aging）在此按 id 用**完整行**替换，拿回完整 summary / apply_url /
// posted_at / experience / deadline 等展示字段。纯函数，便于单测；DB 取数在 service 里做。
import type { FeedSections, Job, Opportunity } from "./types";

export function hydrateOpportunityJobs(sections: FeedSections, rows: Job[]): void {
  const fullById = new Map(rows.map((row) => [row.id, row]));
  // 泛型遍历所有分区（不硬编码 key），新增/改名分区无需改这里。
  const opportunities = Object.values(sections).flat() as Opportunity[];
  for (const opportunity of opportunities) {
    const full = fullById.get(opportunity.job.id);
    if (full) opportunity.job = full;
  }
}
