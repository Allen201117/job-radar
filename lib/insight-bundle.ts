// ============================================================
// 洞察展示门 — 共享的「过校验门 + 按维度分组」逻辑
// /api/insights 与 /api/career-path 共用，避免重复（来源：原 insights 路由内联逻辑）。
// ============================================================

import {
  evaluateInsight,
  type InsightEvaluation,
} from "./insight-verification";
import type {
  InsightDimension,
  InsightItem,
  InsightItemView,
  InsightSource,
} from "./types";

export const INSIGHT_DIMENSIONS: InsightDimension[] = [
  "timing",
  "hiring",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];

export const ITEM_COLUMNS =
  "id, company_id, dimension, grade, title, content, sample_size, payload, time_window, valid_from, valid_until, last_verified_at, deidentified, status, created_at, updated_at";

export function emptyDimensions(): Record<InsightDimension, InsightItemView[]> {
  return { timing: [], hiring: [], listing: [], compensation_intensity: [], path: [], culture: [] };
}

// Supabase 嵌套 select 返回 { insight_sources: {...} }[]，拍平为 InsightSource[]
export function flattenSources(item: any): InsightSource[] {
  const rows = (item?.insight_item_sources || []) as Array<{
    insight_sources: InsightSource | null;
  }>;
  return rows.map((r) => r.insight_sources).filter(Boolean) as InsightSource[];
}

// 输入：某公司的 active 洞察原始行（含嵌套来源）；输出：过门后的分组展示态 + 评估结果
export function groupGatedInsights(
  rawItems: any[],
  now: Date = new Date(),
): {
  dimensions: Record<InsightDimension, InsightItemView[]>;
  evaluations: InsightEvaluation[];
} {
  const dimensions = emptyDimensions();
  const evaluations: InsightEvaluation[] = [];

  for (const raw of rawItems || []) {
    const item = raw as InsightItem;
    const sources = flattenSources(raw);
    const ev = evaluateInsight(item, sources, now);
    evaluations.push(ev);
    if (!ev.displayable) continue;
    dimensions[item.dimension]?.push({ ...item, sources, outdated: ev.outdated });
  }

  // 每个维度内：新鲜在前、过时在后，再按 last_verified_at 倒序
  for (const dim of INSIGHT_DIMENSIONS) {
    dimensions[dim].sort((a, b) => {
      if (a.outdated !== b.outdated) return a.outdated ? 1 : -1;
      return (
        new Date(b.last_verified_at).getTime() - new Date(a.last_verified_at).getTime()
      );
    });
  }

  return { dimensions, evaluations };
}
